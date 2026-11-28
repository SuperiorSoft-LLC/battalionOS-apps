import copy, json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_catalog as cc

ROOT = Path(__file__).resolve().parent.parent
GOOD = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))


def with_app(**over):
    d = copy.deepcopy(GOOD)
    d["apps"][0].update(over)
    return d


class CheckCatalog(unittest.TestCase):
    def test_shipped_catalog_passes(self):
        self.assertEqual(cc.check(GOOD, ROOT), [])

    def test_valid_entry_passes(self):
        self.assertEqual(cc.check(with_app(id="my-app", name="My app"), ROOT), [])

    def test_duplicate_id_fails(self):
        d = copy.deepcopy(GOOD)
        d["apps"].append(copy.deepcopy(d["apps"][0]))
        self.assertTrue(any("appears twice" in e for e in cc.check(d, ROOT)))

    def test_http_url_fails(self):
        d = with_app(channels={"stable": "http://example.com/feed.json"})
        self.assertTrue(any("not https" in e for e in cc.check(d, ROOT)))

    def test_missing_key_fails(self):
        d = copy.deepcopy(GOOD)
        del d["apps"][0]["publicKey"]
        self.assertTrue(any("no public key" in e for e in cc.check(d, ROOT)))

    def test_missing_channel_bad_id_bad_schema_fail(self):
        self.assertTrue(any("no channel" in e for e in cc.check(with_app(channels={}), ROOT)))
        self.assertTrue(any("not allowed" in e for e in cc.check(with_app(id="Bad_Id"), ROOT)))
        d = copy.deepcopy(GOOD)
        d["schema"] = 1
        self.assertTrue(cc.check(d, ROOT))

    def test_icon_rules(self):
        for bad in ("icons/infantry-ai.png", "http://x/y.png", "file:///a.png"):
            self.assertTrue(any("icon must be" in e for e in cc.check(with_app(icon=bad), ROOT)), bad)
        self.assertEqual(cc.check(with_app(icon="https://example.com/a.png"), ROOT), [])

    def test_infantry_ai_has_three_https_channels(self):
        app = next(a for a in GOOD["apps"] if a["id"] == "infantry-ai")
        self.assertEqual(set(app["channels"]), {"stable", "prerelease", "nightly"})
        for url in app["channels"].values():
            self.assertTrue(url.startswith("https://"), url)

    def test_bad_permission_fails(self):
        self.assertTrue(any("unknown permission" in e for e in cc.check(with_app(permissions=["root"]), ROOT)))


class PermissionsPinned(unittest.TestCase):
    # Mirror of battalion-app-api manifest.rs:169. Change both together.
    OS = {"process.spawn", "network", "files.user", "window", "login.window",
          "notifications", "scan.code", "files.read", "files.write"}

    def test_permissions_match_the_os_list(self):
        self.assertEqual(cc.PERMISSIONS, self.OS)

    def test_every_os_permission_is_accepted(self):
        for perm in sorted(self.OS):
            self.assertEqual(cc.check(with_app(permissions=[perm]), ROOT), [], perm)


if __name__ == "__main__":
    unittest.main()
