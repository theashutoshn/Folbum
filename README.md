# Folbum — Public Beta v0.2.0

Folbum is an unofficial companion app for ZimaOS Photos. It creates and updates Photos albums from folders that Photos has already indexed. Albums contain references to your media; the app does not copy, move, or delete files.

## Try it locally

1. Run `docker compose up -d --build` on the NAS.
2. Open `http://NAS_IP:8765` on your trusted LAN. In the Create account popup, choose your own username and password. Then sign in.
3. Add your NAS in **Connection**, select a Photos source in **Sync**, review the preview, then sync.

Open the app, connect using your own ZimaOS URL and account, choose a Photos source, and review the preview before syncing. The container serves HTTP and does not include an HTTPS reverse proxy. Use a trusted LAN for direct access. For HTTPS access, put a reverse proxy in front of Folbum, terminate TLS there, and have the proxy replace `X-Forwarded-Proto` with `https` on requests to Folbum. Folbum then adds `Secure` to session cookies automatically. The proxy should be the only public entry point; restrict direct port 8765 access to trusted clients. An HTTPS browser connection does not also encrypt the separate app-to-NAS connection; use an HTTPS NAS URL if your NAS supports it.

Folbum stores a salted, one-way password hash in its private Docker data volume. Passwords must be at least 12 characters. The first person who opens an unconfigured app can create its account, so finish setup before exposing it to untrusted networks. The app login has a **Stay signed in** checkbox. It keeps a server-side session for 30 days when checked, or 12 hours when unchecked, using a HttpOnly, SameSite=Strict cookie. Change your password in the **Settings** tab; this signs out all browsers. This login is separate from the ZimaOS Photos connection below.

The Connection page has a **+** button that opens a form for the NAS IP address or URL, NAS username, and password. You may also provide a display name; otherwise the app uses the address hostname. After authentication, the page shows the NAS name, address, and connection health. Green means the authenticated Photos sources API succeeded; red means that check failed. The power icon disconnects while keeping saved tokens, and the link icon reconnects by validating those tokens. The trash icon removes the connection details and tokens from this app and clears the selected source and automatic schedule; it does not delete media or albums from the NAS. **Keep NAS connected** is checked by default and stores access and refresh tokens in the private Docker data volume so browser refreshes and container restarts retain the connection. When unchecked, the connection lasts only until the app process stops. The app refreshes tokens automatically and does not put credentials into the browser response. Keep the Docker volume private. A revoked refresh token requires adding the NAS again with credentials.

The Dashboard refreshes its preview and sync history every minute while it is visible. It also refreshes when you return to a browser tab that has been idle for a minute. The refresh button remains available for an immediate update.

Use a NAS address reachable from inside Docker, not `localhost` on the laptop. `ZIMA_URL` is no longer used; enter the address through the Connection page. The app keeps one active ZimaOS connection, shared by everyone who signs in to this app. Adding another NAS replaces that active connection.

## View logs

From the extracted app folder, run `docker compose logs --tail=100 album-sync` to see recent entries, or `docker compose logs -f album-sync` to follow new entries (Ctrl+C stops following). The Compose files mount the Linux NAS host's `/etc/localtime` read-only, so app log timestamps use the NAS time zone and include its offset. The Dashboard's Last sync time uses the browser's local time zone automatically. Docker's optional `--timestamps` flag adds a separate UTC timestamp ending in `Z`. The app logs automatic schedule changes and scheduled sync starts, completions, skips, and failures. After selecting an interval, the first automatic run waits for the full interval; later runs wait for the interval after the prior attempt finishes. Manual sync completions are logged separately.

## Sync behavior

- Every folder with directly indexed media maps to one album. Empty parent folders do not create albums. Media directly inside the selected source maps to an album named after the source folder.
- Albums use the last folder name. If two media folders share that name, their relative paths are used as distinct titles.
- The app reads all indexed gallery pages, lists target album members, and adds only missing asset IDs. Repeated runs normally add nothing.
- A single existing album with the matching title is reused. The preview shows which albums will be created or updated. The app never deletes albums or removes members.
- Upgrading from the earlier folder-rule build keeps its saved mappings untouched. Automatic sync adopts an existing album only when its title matches the new folder title; albums made with old custom titles are left in place.
- If Photos has not indexed a file, the app cannot add it to an album. Refresh the source in ZimaOS Photos, then reload the preview. The current app does not trigger source refresh automatically.
- Each sync removes obsolete album IDs from the selected source's mappings. If a folder still has indexed media, sync reuses a uniquely matching album or creates a replacement and saves its ID. Sync also restores missing members.
- The scheduler runs inside the app process at the chosen interval. Manual sync is available at any time.

## Disk comparison

The Dashboard can compare media files on disk with the selected source's Photos index. It shows how many files Photos has not indexed yet and one example path. This comparison is read-only. Sync still adds only media that Photos has indexed, and the app does not trigger a Photos source scan.

To compare a Photos source with files on disk:

1. Find the selected source path in **Sync** and replace `DISK_SOURCE_PATH` in `compose.disk.yaml` with that exact path (for example, `/media/HDD-Storage/Gallery`).
2. Replace the bind mount `source` path in `compose.disk.yaml` with the matching directory on the NAS. The directory must exist and be readable by the app's `zima` user.
3. Start with `docker compose -f compose.yaml -f compose.disk.yaml up -d --build`.

The extra Compose file mounts that directory read-only at `/media-source`. If the mount is not configured, cannot be read, or belongs to a different selected source, Dashboard shows an unavailable indicator instead of reporting zero missing files. After refreshing a source in ZimaOS Photos, reload the preview to update the comparison.

## App Store package

The ZimaOS App Store source manifest is [Apps/ZimaAlbumSync/docker-compose.yml](Apps/ZimaAlbumSync/docker-compose.yml). It uses a versioned image and a persistent Docker volume. Account creation takes place in the first-run popup.

The image must be built and pushed as `ghcr.io/theashutoshn/zima-album-sync:v0.2.0` before this manifest can be installed from a store. After that, submit the manifest and icon to the [official ZimaOS AppStore repository](https://github.com/IceWhaleTech/CasaOS-AppStore) using its current contribution process. This repository does not publish an image or submit an App Store entry automatically.

## Private reference folder

`photo-album-sync/` contains the original NAS scripts, notes, local configuration, state, and credentials. It is ignored by Git and excluded from the container image. Never add `auth_tokens.json`, `.zima-sync.env`, or a live `sync_state.json` to a release. The app in `app/` is the distributable implementation and has no personal source ID, storage path, or NAS address.

## Development

Run `python -m unittest discover -s tests -v` to test the album planning and observed Photos API response shapes. The Photos endpoints are unofficial and can change with ZimaOS versions; test against a supported NAS before publishing a release.
