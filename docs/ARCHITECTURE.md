# Application architecture

The browser calls a Python HTTP server protected by a first-run Folbum account and session cookie. The server uses the ZimaOS Photos API to list sources, indexed gallery assets, albums, and album members. The user connects a ZimaOS NAS through the Connection page.

The app stores its account password hash, sessions, connection metadata, saved access/refresh tokens, source and schedule settings, album mappings, and run history in a private Docker volume. The mapping key includes the NAS address, Photos source path, and media folder, so equal folder names in different sources cannot share an album mapping. Automatic mappings use a separate key namespace from earlier rule-based versions.

Every folder containing directly indexed media maps to one album. A parent folder with no direct media has no album. Albums use the final folder name; duplicate final names use the relative folder path so titles stay distinct. A single existing album with the matching title is reused. The app adds missing membership references and never removes them.

The background scheduler calls the same sync operation as the manual button. An in-process lock prevents concurrent sync requests within one app instance. An optional read-only gallery mount lets the Dashboard compare disk files with the Photos index; syncing still uses only media indexed by Photos.

## Release limitations

- Photos APIs are unofficial and tested only against the response shapes documented by the original scripts. A real NAS integration test is needed before publishing.
- Source refresh is not automated. A Photos source scan can time out or temporarily return inconsistent membership data; users refresh from Photos and then review the preview.
- The first person to open an unconfigured installation can create its account. Complete setup before exposing the app to untrusted networks. Deploy on a trusted LAN or behind an HTTPS reverse proxy; enable secure cookies when HTTPS is used exclusively.
- Saved NAS tokens are stored in the Docker volume. The current "do not remember" connection also writes temporary tokens there until restart; move that temporary file to the container's tmpfs before a public release.
- A deleted managed album is recreated or a uniquely matching album is reused on the next sync. Intentional member removal is reversed by the next sync.
- Multi-process locking, automatic retry after uncertain writes, and user notifications are future work.
