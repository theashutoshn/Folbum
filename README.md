# Zima Album Sync

Zima Album Sync is an unofficial companion app for ZimaOS Photos. It creates and updates Photos albums from folders that Photos has already indexed. Albums contain references to your media; the app does not copy, move, or delete files.

## Try it locally

1. Copy `.env.example` to `.env` and replace `APP_PASSWORD` with a unique password.
2. Run `docker compose up -d --build`.
3. Open `http://127.0.0.1:8765` and sign in as `admin` with that password.
4. Demo mode uses sample media and cannot touch your Photos library.

To use a real ZimaOS installation, set `ZIMA_MODE=live` and `ENABLE_LIVE_WRITES=true` in `.env`, then rebuild/restart. Open the app, connect using your own ZimaOS URL and account, choose a Photos source, review the preview, and run sync. Use a trusted LAN or an HTTPS reverse proxy for the browser connection: HTTP Basic authentication and the initial ZimaOS login otherwise travel in cleartext.

The app stores access and refresh tokens in its private Docker data volume. It refreshes the token pair automatically and does not put credentials into the browser response. Keep the Docker volume private. A revoked refresh token requires connecting again.

## Sync behavior

- Every folder with directly indexed media maps to one album. Empty parent folders do not create albums. Media directly inside the selected source maps to an album named after the source folder.
- Albums use the last folder name. If two media folders share that name, their relative paths are used as distinct titles.
- The app reads all indexed gallery pages, lists target album members, and adds only missing asset IDs. Repeated runs normally add nothing.
- A single existing album with the matching title is reused. The preview shows which albums will be created or updated. The app never deletes albums or removes members.
- Upgrading from the earlier folder-rule build keeps its saved mappings untouched. Automatic sync adopts an existing album only when its title matches the new folder title; albums made with old custom titles are left in place.
- If Photos has not indexed a file, the app cannot add it to an album. Refresh the source in ZimaOS Photos, then reload the preview. The current app does not trigger source refresh automatically.
- Manual removal of a member from a managed album is reversed on the next sync. A deleted managed album produces a stale-mapping error for review.
- The scheduler runs inside the app process at the chosen interval. Manual sync is available at any time.

## App Store package

The ZimaOS App Store source manifest is [Apps/ZimaAlbumSync/docker-compose.yml](Apps/ZimaAlbumSync/docker-compose.yml). It uses a versioned image, a persistent Docker volume, and an install-time `APP_PASSWORD` value. Replace the password placeholder during installation. The app refuses to start with the placeholder.

The image must be built and pushed as `ghcr.io/theashutoshn/zima-album-sync:v0.1.0` before this manifest can be installed from a store. After that, submit the manifest and icon to the [official ZimaOS AppStore repository](https://github.com/IceWhaleTech/CasaOS-AppStore) using its current contribution process. This repository does not publish an image or submit an App Store entry automatically.

## Private reference folder

`photo-album-sync/` contains the original NAS scripts, notes, local configuration, state, and credentials. It is ignored by Git and excluded from the container image. Never add `auth_tokens.json`, `.zima-sync.env`, or a live `sync_state.json` to a release. The app in `app/` is the distributable implementation and has no personal source ID, storage path, or NAS address.

## Development

Run `python -m unittest discover -s tests -v` to test the album planning and observed Photos API response shapes. The Photos endpoints are unofficial and can change with ZimaOS versions; test against a supported NAS before publishing a release.
