#!/usr/bin/env python3
"""Schema check for catalog.json; mirrors battalion-app-api catalog.rs (Catalog::parse + CatalogApp::check).
Usage: check_catalog.py [catalog.json]   exit 0 = ok, 1 = problems (one line each)."""
import json, re, sys
from pathlib import Path

PERMISSIONS = {"process.spawn", "network", "files.user", "window", "login.window"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
STR_FIELDS = ("name", "publisher", "summary", "license", "icon", "homepage")


def check(doc, root=None):
    """Return a list of problems; [] means the catalog is valid. `root` is unused, kept for callers."""
    if not isinstance(doc, dict):
        return ["catalog is not an object"]
    if doc.get("schema") != 2:
        return [f"catalog schema {doc.get('schema')!r} is not supported (need 2)"]
    apps = doc.get("apps", [])
    if not isinstance(apps, list):
        return ["'apps' is not a list"]
    errs, seen = [], set()
    for i, a in enumerate(apps):
        if not isinstance(a, dict):
            errs.append(f"apps[{i}] is not an object")
            continue
        aid = a.get("id")
        tag = f"app '{aid}'" if isinstance(aid, str) else f"apps[{i}]"
        if not isinstance(aid, str) or not ID.match(aid):
            errs.append(f"{tag}: id is missing or not allowed (2-63 chars, a-z 0-9 -)")
        elif aid in seen:
            errs.append(f"{tag}: app id '{aid}' appears twice")
        else:
            seen.add(aid)
        if not isinstance(a.get("name"), str) or not a["name"].strip():
            errs.append(f"{tag}: name is missing")
        key = a.get("publicKey")
        if not isinstance(key, str) or not key.strip():
            errs.append(f"{tag}: has no public key")
        c = a.get("contract")
        if not (isinstance(c, dict) and all(type(c.get(k)) is int for k in ("min", "max")) and 0 < c["min"] <= c["max"]):
            errs.append(f"{tag}: contract needs integers 0 < min <= max")
        for p in a.get("permissions", []) or []:
            if p not in PERMISSIONS:
                errs.append(f"{tag}: unknown permission '{p}'")
        ch = a.get("channels")
        if not isinstance(ch, dict) or not ch:
            errs.append(f"{tag}: has no channel")
        else:
            for name, url in ch.items():
                if not isinstance(url, str) or not url.startswith("https://"):
                    errs.append(f"{tag}: channel '{name}' url {url!r} is not https")
        hp = a.get("homepage")
        if hp is not None and not (isinstance(hp, str) and hp.startswith("https://")):
            errs.append(f"{tag}: homepage is not https")
        for f in STR_FIELDS:
            if f in a and a[f] is not None and not isinstance(a[f], str):
                errs.append(f"{tag}: {f} is not a string")
        icon = a.get("icon")
        if icon is not None and not (isinstance(icon, str) and (icon.startswith("data:image/") or icon.startswith("https://"))):
            errs.append(f"{tag}: icon must be a data:image/ url or an https url (the OS shows nothing else)")
    return errs


def main(argv):
    path = Path(argv[1] if len(argv) > 1 else Path(__file__).resolve().parent.parent / "catalog.json")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"FAIL {path}: {e}")
        return 1
    errs = check(doc, path.parent)
    for e in errs:
        print(f"FAIL {e}")
    if not errs:
        print(f"ok: {len(doc.get('apps', []))} app(s) in {path.name}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
