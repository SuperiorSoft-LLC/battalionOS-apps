#!/usr/bin/env python3
"""End-to-end check of a catalog entry that a pull request adds or bumps (ARMORY-CHECK-1).

For each channel of the entry: fetch the feed (https only; file paths only in offline mode), then for every
platform in the feed download the package and check its size and sha256, verify its minisign signature against
the entry's publicKey, and read app.json from the package: id, version, contract and permissions must match the
entry and the feed. A publicKey change on an id the base catalog already lists is never OK by itself: it is
reported for human review.

Usage:
  verify_entry.py catalog.json [--base base-catalog.json] [--all] [--offline] [--summary FILE]
    --base     the catalog before the PR (CI: the target branch); only new or changed entries are verified
    --all      verify every entry, not only the changed ones
    --offline  allow file: urls and plain paths (relative to the catalog file); for tests and dry runs
    --summary  append a markdown summary to FILE (CI passes $GITHUB_STEP_SUMMARY)
Exit 0 = every check passed, 1 = a check failed, 2 = passed but needs human review (key change).
Needs the `cryptography` package for the signature check.
"""
import base64, hashlib, io, json, sys, urllib.parse, urllib.request, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_catalog

FETCH_TIMEOUT_S = 30          # one feed or package download
MAX_FEED_BYTES = 1 << 20      # a feed is a small json
MAX_PACKAGE_BYTES = 512 << 20  # refuse anything larger before hashing


class Fetcher:
    """https only; with offline=True also file: urls and paths relative to `base_dir`."""

    def __init__(self, base_dir, offline=False):
        self.base_dir, self.offline = Path(base_dir), offline

    def get(self, url, limit):
        if url.startswith("https://"):
            req = urllib.request.Request(url, headers={"User-Agent": "battalionos-apps-catalog-check"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as r:
                data = r.read(limit + 1)
        elif self.offline:
            if url.startswith("file:"):
                p = Path(urllib.request.url2pathname(urllib.parse.urlparse(url).path))
            else:
                p = self.base_dir / url
            data = p.read_bytes()
        else:
            raise ValueError(f"{url!r} is not https")
        if len(data) > limit:
            raise ValueError(f"{url} is larger than {limit} bytes")
        return data


# ---- minisign -------------------------------------------------------------------------------------------------

def _b64(s, what):
    try:
        return base64.b64decode(s.strip(), validate=True)
    except Exception:
        raise ValueError(f"{what} is not base64")


def parse_public_key(text):
    """The base64 line of a minisign .pub (or the whole file). Returns (key_id, raw 32-byte key)."""
    lines = [l for l in text.strip().splitlines() if l.strip() and not l.startswith("untrusted comment:")]
    raw = _b64(lines[-1] if lines else "", "publicKey")
    if len(raw) != 42 or raw[:2] != b"Ed":
        raise ValueError("publicKey is not a minisign Ed25519 key")
    return raw[2:10], raw[10:]


def verify_minisign(data, sig_text, public_key):
    """Raise ValueError unless `sig_text` (a .minisig) signs `data` with `public_key` (the base64 line)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key_id, pk = parse_public_key(public_key)
    lines = sig_text.strip().splitlines()
    if len(lines) < 4 or not lines[0].startswith("untrusted comment:") or not lines[2].startswith("trusted comment:"):
        raise ValueError("signature is not a minisign signature (4 lines)")
    raw = _b64(lines[1], "signature")
    if len(raw) != 74 or raw[:2] not in (b"Ed", b"ED"):
        raise ValueError("signature is not a minisign Ed25519 signature")
    if raw[2:10] != key_id:
        raise ValueError("signature was made by another key than the entry's publicKey")
    message = hashlib.blake2b(data, digest_size=64).digest() if raw[:2] == b"ED" else data
    trusted = lines[2][len("trusted comment:"):].lstrip(" ").encode()
    gsig = _b64(lines[3], "global signature")
    key = Ed25519PublicKey.from_public_bytes(pk)
    try:
        key.verify(raw[10:], message)
    except InvalidSignature:
        raise ValueError("signature does not verify against the entry's publicKey")
    try:
        key.verify(gsig, raw[10:] + trusted)
    except InvalidSignature:
        raise ValueError("trusted comment signature does not verify")


# ---- one entry --------------------------------------------------------------------------------------------------

class Report:
    def __init__(self, app_id):
        self.app_id, self.checks, self.review = app_id, [], []

    def ok(self, name, detail=""):
        self.checks.append(("PASS", name, detail))

    def fail(self, name, detail):
        self.checks.append(("FAIL", name, detail))

    @property
    def failed(self):
        return any(s == "FAIL" for s, _, _ in self.checks)


def read_manifest(pkg):
    with zipfile.ZipFile(io.BytesIO(pkg)) as z:
        return json.loads(z.read("app.json").decode("utf-8"))


def verify_app(app, fetcher, base_app=None):
    r = Report(app.get("id"))
    errs = check_catalog.check({"schema": 2, "apps": [app]})
    if fetcher.offline:  # file feeds are allowed offline; every other schema rule still applies
        errs = [e for e in errs if "is not https" not in e or "channel" not in e]
    for e in errs:
        r.fail("schema", e)
    if not errs:
        r.ok("schema", "id, name, key, contract, permissions, channels")
    perms = sorted(app.get("permissions") or [])
    r.ok("permissions shown", ", ".join(perms) if perms else "(none)")

    if base_app is not None and base_app.get("publicKey") != app.get("publicKey"):
        r.review.append(f"publicKey of '{app.get('id')}' changed: {base_app.get('publicKey')} -> {app.get('publicKey')}. "
                        "A key change can hand the app to someone else; a maintainer must confirm it with the publisher.")
    if any("unknown permission" not in e for e in errs):
        return r  # the package checks need a sound id, key, contract and channels

    contract = app["contract"]
    for channel, url in app["channels"].items():
        tag = f"{channel}"
        try:
            feed = json.loads(fetcher.get(url, MAX_FEED_BYTES).decode("utf-8"))
            version, platforms = feed["version"], feed["platforms"]
            if not isinstance(version, str) or not isinstance(platforms, dict) or not platforms:
                raise ValueError("needs a version string and a non-empty platforms map")
        except Exception as e:
            r.fail(f"{tag}: feed", f"{url}: {e}")
            continue
        r.ok(f"{tag}: feed", f"{url} version {version}")
        fc = feed.get("contract")
        if not (type(fc) is int and contract["min"] <= fc <= contract["max"]):
            r.fail(f"{tag}: feed contract", f"feed contract {fc!r} is outside the entry's {contract['min']}..{contract['max']}")
        for plat, p in platforms.items():
            ptag = f"{tag}/{plat}"
            try:
                pkg = fetcher.get(p["url"], MAX_PACKAGE_BYTES)
            except Exception as e:
                r.fail(f"{ptag}: download", f"{p.get('url')}: {e}")
                continue
            r.ok(f"{ptag}: download", f"{len(pkg)} bytes")
            if len(pkg) != p.get("size"):
                r.fail(f"{ptag}: size", f"package is {len(pkg)} bytes, feed says {p.get('size')}")
            else:
                r.ok(f"{ptag}: size")
            sha = hashlib.sha256(pkg).hexdigest()
            if sha != str(p.get("sha256", "")).lower():
                r.fail(f"{ptag}: sha256", f"package is {sha}, feed says {p.get('sha256')}")
            else:
                r.ok(f"{ptag}: sha256")
            try:
                verify_minisign(pkg, p.get("signature") or "", app["publicKey"])
                r.ok(f"{ptag}: signature", "minisign, entry publicKey")
            except Exception as e:
                r.fail(f"{ptag}: signature", str(e))
            try:
                m = read_manifest(pkg)
            except Exception as e:
                r.fail(f"{ptag}: manifest", f"no readable app.json in the package: {e}")
                continue
            bad = []
            if m.get("id") != app["id"]:
                bad.append(f"id {m.get('id')!r} != entry {app['id']!r}")
            if m.get("version") != version:
                bad.append(f"version {m.get('version')!r} != feed {version!r}")
            if m.get("contract") != contract:
                bad.append(f"contract {m.get('contract')!r} != entry {contract!r}")
            mp = sorted(m.get("permissions") or [])
            if mp != perms:
                bad.append(f"permissions {mp} != entry {perms}")
            unknown = [x for x in mp if x not in check_catalog.PERMISSIONS]
            if unknown:
                bad.append(f"package asks for unknown permission(s) {unknown}")
            if bad:
                r.fail(f"{ptag}: manifest", "; ".join(bad))
            else:
                r.ok(f"{ptag}: manifest", f"id, version {version}, contract, permissions")
    return r


def changed_apps(doc, base):
    old = {a.get("id"): a for a in (base or {}).get("apps", []) if isinstance(a, dict)}
    return [(a, old.get(a.get("id"))) for a in doc.get("apps", []) if isinstance(a, dict) and a != old.get(a.get("id"))]


def summary_markdown(reports, schema_errs):
    out = ["## Catalog check", ""]
    if schema_errs:
        out += ["**Catalog schema: FAIL**", ""] + [f"- {e}" for e in schema_errs] + [""]
    if not reports:
        out.append("No app entry was added or changed.")
    for r in reports:
        verdict = "FAIL" if r.failed else ("NEEDS REVIEW" if r.review else "PASS")
        out += [f"### `{r.app_id}`: {verdict}", "", "| Result | Check | Detail |", "|---|---|---|"]
        out += [f"| {s} | {n} | {d.replace('|', '/')} |" for s, n, d in r.checks]
        out += [""] + [f"> **Human review:** {x}" for x in r.review] + [""]
    out.append("This check never merges; a maintainer merges after reading it.")
    return "\n".join(out) + "\n"


def main(argv):
    args, flags, i = [], {}, 1
    while i < len(argv):
        a = argv[i]
        if a in ("--base", "--summary"):
            flags[a] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            flags[a] = True
        else:
            args.append(a)
        i += 1
    path = Path(args[0] if args else Path(__file__).resolve().parent.parent / "catalog.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    base = json.loads(Path(flags["--base"]).read_text(encoding="utf-8")) if flags.get("--base") else None
    offline = bool(flags.get("--offline"))
    schema_errs = [] if offline else check_catalog.check(doc)
    fetcher = Fetcher(path.parent, offline=offline)
    if flags.get("--all"):
        old = {a.get("id"): a for a in (base or {}).get("apps", [])}
        pairs = [(a, old.get(a.get("id"))) for a in doc.get("apps", [])]
    else:
        pairs = changed_apps(doc, base)
    reports = [verify_app(a, fetcher, b) for a, b in pairs]
    for e in schema_errs:
        print(f"FAIL catalog: {e}")
    for r in reports:
        for s, n, d in r.checks:
            print(f"{s} {r.app_id}: {n}{': ' + d if d else ''}")
        for x in r.review:
            print(f"REVIEW {r.app_id}: {x}")
    md = summary_markdown(reports, schema_errs)
    if flags.get("--summary"):
        with open(flags["--summary"], "a", encoding="utf-8") as f:
            f.write(md)
    if schema_errs or any(r.failed for r in reports):
        return 1
    return 2 if any(r.review for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
