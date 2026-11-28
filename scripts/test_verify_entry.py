"""Tests for verify_entry.py (ARMORY-CHECK-1). Offline: every feed and package is a file in a temp folder, and
every key is made here and thrown away. Needs `cryptography`."""
import base64, copy, hashlib, io, json, os, shutil, sys, tempfile, unittest, zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, str(Path(__file__).parent))
import verify_entry as ve

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "files"


class Key:
    """A throwaway minisign key."""

    def __init__(self):
        self.sk = Ed25519PrivateKey.generate()
        self.id = os.urandom(8)
        pk = self.sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.public = base64.b64encode(b"Ed" + self.id + pk).decode()

    def sign(self, data, name="pkg"):
        sig = self.sk.sign(hashlib.blake2b(data, digest_size=64).digest())
        trusted = f"timestamp:0\tfile:{name}\thashed"
        g = self.sk.sign(sig + trusted.encode())
        return ("untrusted comment: signature from minisign secret key\n"
                f"{base64.b64encode(b'ED' + self.id + sig).decode()}\n"
                f"trusted comment: {trusted}\n{base64.b64encode(g).decode()}\n")


def package(manifest, extra=b"<html></html>"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("app.json", json.dumps(manifest))
        z.writestr("ui/index.html", extra)
    return buf.getvalue()


MANIFEST = {"manifest": 1, "id": "my-app", "name": "My app", "version": "1.2.0", "contract": {"min": 1, "max": 1},
            "permissions": ["network", "files.user"]}


def entry(key, **over):
    e = {"id": "my-app", "name": "My app", "publicKey": key.public, "contract": {"min": 1, "max": 1},
         "permissions": ["files.user", "network"], "channels": {"stable": "feed.json"}}
    e.update(over)
    return e


class Site:
    """A temp folder that plays the publisher's release page: feed.json and the package."""

    def __init__(self, key, manifest=MANIFEST, feed_version="1.2.0", sign_with=None):
        self.dir = Path(tempfile.mkdtemp())
        self.pkg = package(manifest)
        (self.dir / "app.bosapp").write_bytes(self.pkg)
        self.feed = {"version": feed_version, "contract": 1, "platforms": {"windows-x86_64": {
            "url": "app.bosapp", "size": len(self.pkg), "sha256": hashlib.sha256(self.pkg).hexdigest(),
            "signature": (sign_with or key).sign(self.pkg)}}}
        self.write_feed()

    def write_feed(self):
        (self.dir / "feed.json").write_text(json.dumps(self.feed))

    def verify(self, app, base_app=None):
        return ve.verify_app(app, ve.Fetcher(self.dir, offline=True), base_app)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def fails(r, name):
    return [d for s, n, d in r.checks if s == "FAIL" and name in n]


class VerifyEntry(unittest.TestCase):
    def setUp(self):
        self.key = Key()
        self.sites = []

    def tearDown(self):
        for s in self.sites:
            s.close()

    def site(self, **kw):
        s = Site(self.key, **kw)
        self.sites.append(s)
        return s

    def test_good_entry_passes(self):
        r = self.site().verify(entry(self.key))
        self.assertFalse(r.failed, r.checks)
        self.assertEqual(r.review, [])
        names = [n for _, n, _ in r.checks]
        for want in ("feed", "download", "size", "sha256", "signature", "manifest", "permissions shown"):
            self.assertTrue(any(want in n for n in names), want)
        shown = next(d for _, n, d in r.checks if n == "permissions shown")
        self.assertEqual(shown, "files.user, network")

    def test_tampered_package_fails_sha_and_signature(self):
        s = self.site()
        bad = bytearray(s.pkg)
        bad[-30] ^= 0xFF
        (s.dir / "app.bosapp").write_bytes(bytes(bad))
        r = s.verify(entry(self.key))
        self.assertTrue(fails(r, "sha256"))
        self.assertTrue(fails(r, "signature"))

    def test_size_mismatch_fails(self):
        s = self.site()
        s.feed["platforms"]["windows-x86_64"]["size"] += 1
        s.write_feed()
        self.assertTrue(fails(s.verify(entry(self.key)), "size"))

    def test_signature_by_another_key_fails(self):
        r = self.site(sign_with=Key()).verify(entry(self.key))
        self.assertIn("another key", fails(r, "signature")[0])

    def test_version_mismatch_fails(self):
        r = self.site(feed_version="1.3.0").verify(entry(self.key))
        self.assertIn("version", fails(r, "manifest")[0])

    def test_manifest_id_and_permissions_must_match_entry(self):
        r = self.site().verify(entry(self.key, permissions=["network"]))
        self.assertIn("permissions", fails(r, "manifest")[0])
        r = self.site(manifest=dict(MANIFEST, id="other-app")).verify(entry(self.key))
        self.assertIn("id", fails(r, "manifest")[0])

    def test_bad_permission_fails(self):
        m = dict(MANIFEST, permissions=["root"])
        r = self.site(manifest=m).verify(entry(self.key, permissions=["root"]))
        self.assertTrue(fails(r, "schema"))
        self.assertIn("unknown permission", fails(r, "manifest")[0])

    def test_feed_contract_outside_entry_fails(self):
        s = self.site()
        s.feed["contract"] = 2
        s.write_feed()
        self.assertTrue(fails(s.verify(entry(self.key)), "feed contract"))

    def test_key_change_needs_human_review(self):
        new = Key()
        s = Site(new)
        self.sites.append(s)
        r = s.verify(entry(new), base_app=entry(self.key))
        self.assertFalse(r.failed, r.checks)  # every check passes with the new key...
        self.assertEqual(len(r.review), 1)    # ...and it is still not OK on its own
        self.assertIn("publicKey", r.review[0])

    def test_same_key_bump_needs_no_review(self):
        r = self.site().verify(entry(self.key), base_app=entry(self.key, channels={"stable": "old.json"}))
        self.assertEqual(r.review, [])

    def test_https_required_online(self):
        r = ve.verify_app(entry(self.key), ve.Fetcher(".", offline=False))
        self.assertTrue(fails(r, "schema"))

    def test_main_exit_codes_and_summary(self):
        s = self.site()
        (s.dir / "catalog.json").write_text(json.dumps({"schema": 2, "apps": [entry(self.key)]}))
        (s.dir / "base.json").write_text(json.dumps({"schema": 2, "apps": []}))
        md = s.dir / "summary.md"
        cat, base = str(s.dir / "catalog.json"), str(s.dir / "base.json")
        self.assertEqual(ve.main(["x", cat, "--base", base, "--offline", "--summary", str(md)]), 0)
        self.assertIn("`my-app`: PASS", md.read_text())
        # unchanged against the base: nothing to verify
        self.assertEqual(ve.main(["x", cat, "--base", cat, "--offline"]), 0)
        # key change: exit 2 = needs review
        other = entry(Key())
        (s.dir / "base.json").write_text(json.dumps({"schema": 2, "apps": [other]}))
        self.assertEqual(ve.main(["x", cat, "--base", base, "--offline", "--summary", str(md)]), 2)
        self.assertIn("NEEDS REVIEW", md.read_text())


class FilesDryRun(unittest.TestCase):
    """The Files app as built in battalionos-files/out, signed with its throwaway key (fixtures/files)."""

    def run_fixture(self, mutate=None):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(FIXTURE, tmp, dirs_exist_ok=True)
        if mutate:
            mutate(tmp)
        app = json.loads((tmp / "catalog.json").read_text())["apps"][0]
        return ve.verify_app(app, ve.Fetcher(tmp, offline=True))

    def test_files_signature_size_sha_and_manifest_verify(self):
        r = self.run_fixture()
        for name in ("feed", "download", "size", "sha256", "signature"):
            self.assertTrue(any(s == "PASS" and name in n for s, n, _ in r.checks), name)
        # ARMORY-CHECK-2: files.read/files.write are OS permissions, so the dry run passes fully.
        self.assertEqual([n for s, n, _ in r.checks if s == "FAIL"], [])

    def test_files_tampered_copy_fails(self):
        def tamper(d):
            p = d / "files-0.1.0-windows-x86_64.bosapp"
            b = bytearray(p.read_bytes())
            b[len(b) // 2] ^= 0x01
            p.write_bytes(bytes(b))
        r = self.run_fixture(tamper)
        self.assertTrue(fails(r, "sha256"))
        self.assertTrue(fails(r, "signature"))

    def test_files_entry_is_not_in_the_live_catalog(self):
        live = json.loads((Path(__file__).resolve().parent.parent / "catalog.json").read_text(encoding="utf-8"))
        self.assertNotIn("files", [a["id"] for a in live["apps"]])


if __name__ == "__main__":
    unittest.main()
