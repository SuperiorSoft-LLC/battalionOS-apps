# Publish your app

Your app's code, builds and releases stay in **your** repository. This repository holds only the catalog entry that
points at them. Publishing is a pull request that adds (or bumps) your entry in `catalog.json`; a check verifies it end
to end and a maintainer merges it. Nothing is merged automatically.

## 1. Make the app

Start from the page-app template, `fixtures/page-app` in [BattalionOS](https://github.com/SuperiorSoft-LLC/BattalionOS) (copy the folder into
your own repository). Its `app.json` is the manifest: `id` (2-63 chars, `a-z 0-9 -`), `name`, `version`, `contract`
(`{min, max}`) and `permissions`. Ask only for permissions the OS knows: `process.spawn`, `network`, `files.user`,
`window`, `login.window`.

## 2. Package and sign it

1. Make a signing key once: `minisign -G -p myapp.pub -s myapp.key`. Keep `myapp.key` secret and out of every
   repository. The **base64 line** of `myapp.pub` is your `publicKey`; the OS pins it at first install.
2. Build the `.bosapp` package (`bos-package` in infantry-ai). It writes the package, its `.minisig` signature, a
   `feed.json` and a `catalog-entry.json` with the key to pin.

The feed (`feed.json`) names one version and, per platform, the package url, its `size`, `sha256` and the full text
of its minisign `signature`:

```json
{ "version": "1.2.0", "contract": 1,
  "platforms": { "windows-x86_64": { "url": "https://github.com/you/my-app/releases/download/v1.2.0/my-app-1.2.0-windows-x86_64.bosapp",
    "size": 80497, "sha256": "…", "signature": "untrusted comment: …\n…\ntrusted comment: …\n…\n" } } }
```

## 3. Host the feed on your GitHub releases

Upload the package and `feed.json` to a release of your repository. A channel url that never changes works best: a
release tag per channel (`bos-stable`, `bos-prerelease`, `bos-nightly`) whose `feed.json` you replace on each update,
for example `https://github.com/you/my-app/releases/download/bos-stable/feed.json`. Every url must be https.

## 4. Open a pull request here

Add your entry to `apps` in `catalog.json`: `id`, `name`, `publicKey`, `contract`, `permissions`, `channels`
(channel name -> https feed url) and optionally `publisher`, `summary`, `license`, `homepage`, `icon` (see README).
Check it locally first:

```
pip install cryptography
python3 scripts/check_catalog.py
python3 scripts/verify_entry.py catalog.json --base <copy of catalog.json from main>
```

On the pull request, the `verify-entries` job checks each new or changed entry and writes the result to the job
summary:

- schema and id rules;
- each channel's feed is reachable over https and well formed, and its contract is inside the entry's;
- each package downloads, its size and sha256 match the feed, and its minisign signature verifies against the
  entry's `publicKey`;
- the package's `app.json` has the entry's id, contract and permissions, and the feed's version;
- the permissions the app asks for are listed in the summary, so a reviewer sees them;
- a `publicKey` change on an id already listed is flagged **NEEDS REVIEW**: a maintainer confirms it with the
  publisher before merging, even when every other check passes.

To ship an update you usually change nothing here: replace the `feed.json` on your release and users get it. Open a
PR only to change the entry itself (a new channel, permissions, a new key).

## Trying it offline

`verify_entry.py --offline` also accepts file paths (relative to the catalog file) for feeds and packages.
`scripts/fixtures/files` is a dry run with the Files app, signed with a throwaway key:

```
python3 scripts/verify_entry.py scripts/fixtures/files/catalog.json --offline --all
```
