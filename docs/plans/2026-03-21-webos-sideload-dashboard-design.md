# webOS Sidecar design

## Goal

Build a local-first sideload dashboard that makes LG webOS TV developer installs feel simple instead of CLI-heavy, while still using the official LG tooling under the hood. The dashboard should cover the real workflow end-to-end: save the TV, fetch the developer SSH key through `Key Server`, load an `.ipk`, install it, and verify it appears on the TV. The experience should also guide users away from common mistakes like trying a `.wgt` on LG.

## Architecture

The implementation uses FastAPI plus a static frontend. Python is only the wrapper layer; the actual LG communication stays delegated to the official `@webos-tools/cli` commands. This keeps the tool honest and minimizes protocol drift. The frontend is a bold glitch/RGB single-page dashboard with drag-and-drop upload, GitHub release resolution, install activity output, and local history. Artifacts are stored in a local `runtime/` folder instead of a database.

## Failure handling

Every major CLI step returns raw command output plus a higher-level diagnosis when the error matches a known failure pattern. The first version focuses on the mistakes that happen most often: wrong package format, missing `.ipk` release asset, network reachability issues, passphrase/key mismatch, expired Developer Mode, and packaging the wrong folder. Verification is intentionally strict: a successful install is only marked verified when the installed app list contains the expected app id.
