# battalionOS-apps
BattalionOS apps catalog: the apps the Marketplace lists and updates (apps.json)

## apps.json

The Armory reads this file. Each entry of `apps`: `id`, `name`, `kind` (`app` or `shell`), `version` or `feed`
(a release feed `latest.json`; `{channel}` is replaced by the user's channel), `publicKey` (the update signature key),
`restart` (`none`, `daemon` or `relaunch`). The daemon setting `armory.catalogUrl` points at this file.
