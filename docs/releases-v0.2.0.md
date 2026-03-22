# webOS Sidecar v0.2.0 📺⚡

## Highlights 🚀

- ✅ fixed LG Key Server passphrase handling by normalizing TV codes to uppercase
- ✅ fixed modern Node compatibility for `@webos-tools/cli` installs
- ✅ Moonfin install path verified on a real LG webOS TV
- ✅ Litefin release support added to the dashboard presets and resolver guidance
- ✅ publish-ready repo docs, changelog, and mermaid project diagrams

## User-facing changes ✨

- TV cards now show whether the saved SSH key and passphrase exist
- Step 2 clears stale local keys before linking again
- Step 2 now explains passphrase mismatch errors directly
- Step 4 blocks impossible installs before running the CLI when auth state is incomplete
- dashboard source presets now include:
  - Moonfin org
  - Moonfin Smart-TV releases
  - Litefin repo
  - Litefin releases

## Technical fixes 🛠️

- `scripts/node-compat.cjs` restores `util.isDate` for the LG CLI’s bundled `ssh2` path on Node 25
- CLI wrapper injects the compatibility shim automatically
- passphrases are normalized server-side and client-side
- Litefin release guidance now explains `es6-webos`, `legacy-webos`, and `ultra-legacy-webos`

## Verified ✅

- `ares-device --system-info --device living-room-tv`
- dashboard `POST /api/install`
- installed app listing returns `org.moonfin.webos`

## Suggested GitHub release blurb 🪩

`webOS Sidecar v0.2.0` turns the rough LG webOS sideload flow into a cleaner local dashboard: Moonfin verified, Litefin wired in, uppercase Key Server fixes, Node 25 compatibility, and better troubleshooting all the way through. 📺⚡
