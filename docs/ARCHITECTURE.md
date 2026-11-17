# Scaffold architecture and next milestones

## Current data flow

- Browser → HTTP Basic authenticated Python stdlib server → preview/config/sync endpoints.
- Demo mode → seven synthetic API-like indexed assets. No NAS access.
- Live mode → observed ZimaOS Photos `/v2/photos/gallery/assets`, `/v2/photos/albums`, `/v2/photos/albums/{id}`; add-only album writes when ENABLE_LIVE_WRITES=true.
- Persistent JSON → `config.json`, `sync_state.json`, `credentials.json` (live-only), `history.json`, `demo_albums.json` (demo-only).
- Docker packaging → single lightweight container, no database/Node/npm dependencies. Static UI ships with image.

## Rule behavior

- Each selected folder creates a single flat Photos album.
- `recursive=false` includes only files directly inside the folder.
- `recursive=true` includes all descendants; overlapping parent/child album memberships are intentional.
- Naming: full relative folder path (`Trips / Korea`) or last path element (`Korea`). Per-folder override can supersede either.
- Duplicate configured titles fail closed. Missing indexed directories display `not-indexed` rather than creating empty albums.
- Existing Photos albums are not adopted by name unless explicitly implemented in a future release; current version protects user-owned albums against unintentional changes.

## Production TODO

1. Inspect **actual API JSON shapes** on the user's ZimaOS version to verify pagination fields and refresh response. Current runbook documents paths, not complete response schema.
2. Add a secure Photos initial-login flow that doesn't expose credentials over an untrusted HTTP path.
3. Add source indexing state and optionally call a **verified** source-refresh endpoint; do not infer a private endpoint.
4. Add explicit UI for adopting an existing album by immutable album ID, rather than guessing by title.
5. Migrate prior systemd sync_state mappings safely, with warnings on gallery-root differences.
6. Support mount-free folder browse from Photos index, and optional read-only filesystem mount for empty folder discovery.
7. Add robust sync logging, job locking across processes, retry/backoff, structured error codes, and scheduler persistence.
8. Add HTTPS proxy documentation, CSRF protection, session/auth design, privilege minimization, and integration tests on supported ZimaOS releases.
9. Publish a version-tagged container image, proper icon, valid x-casaos metadata and tested App Store submission.
