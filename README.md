# battalionOS-apps
BattalionOS apps catalog: the apps the Marketplace lists and updates (apps.json)

## apps.json

The Armory reads this file. Each entry of `apps`: `id`, `name`, `kind` (`app` or `shell`), `version` or `feed`
(a release feed `latest.json`; `{channel}` is replaced by the user's channel), `publicKey` (the update signature key),
`restart` (`none`, `daemon` or `relaunch`). The daemon setting `armory.catalogUrl` points at this file.

## catalog.json (Armory catalog v2)

`catalog.json` is the catalog the BattalionOS Armory lists: `{ "schema": 2, "apps": [...] }`. `apps.json` above is the
older file the 0.7 releases read; it stays as it is.

Each app: `id` (2-63 chars, `a-z 0-9 -`, unique), `name`, `publicKey` (minisign key, pinned at first install),
`contract` (`{min, max}`, the app contract versions it speaks), `channels` (channel name -> https feed url; the channel names are `stable`, `prerelease` and `nightly`), and
optional `publisher`, `summary`, `license`, `homepage` (https), `icon` (a `data:image/` url or an https url; the OS accepts nothing else) and `permissions`
(`process.spawn`, `network`, `files.user`, `window`, `login.window`).

## Add your app

1. Package and sign it (`bos-package` in infantry-ai writes a `catalog-entry.json` with the key to pin).
2. Make a small PNG (about 128x128) and inline it as a `data:image/png;base64,...` url, or host it at an https url.
3. Add the entry to `apps` in `catalog.json`, with https channel urls only.
4. Run `python3 scripts/test_check_catalog.py` and `python3 scripts/check_catalog.py`; CI runs both on every push.
5. Open a pull request. The code of the app stays in your own repository: the catalog holds only the entry.
