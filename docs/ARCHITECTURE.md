# Application architecture

The browser calls a password-protected Python HTTP server. The server uses the ZimaOS Photos API to list sources, indexed gallery assets, albums, and album members. Demo mode uses synthetic assets and never calls the NAS. Live mode requires a user-provided ZimaOS URL and login.

The app stores connection metadata, rotated access/refresh credentials, source and schedule settings, album mappings, and run history in a private Docker volume. The mapping key includes the Photos source path and media folder, so equal folder names in different sources cannot share an album mapping. Automatic mappings use a separate key namespace from earlier rule-based versions.

Every folder containing directly indexed media maps to one album. A parent folder with no direct media has no album. Albums use the final folder name; duplicate final names use the relative folder path so titles stay distinct. A single existing album with the matching title is reused. The app adds missing membership references and never removes them.

The background scheduler calls the same sync operation as the manual button. An in-process lock prevents concurrent sync requests within one app instance. The app does not mount the user's gallery, and it cannot see files that Photos has not indexed.

## Release limitations

- Photos APIs are unofficial and tested only against the response shapes documented by the original scripts. A live NAS integration test is needed before publishing.
- Source refresh is not automated. A Photos source scan can time out or temporarily return inconsistent membership data; users refresh from Photos and then review the preview.
- The web UI uses HTTP Basic authentication. Deploy on a trusted LAN or behind an HTTPS reverse proxy. The app checks same-origin browser writes, but it is not a complete public-internet authentication system.
- A deleted managed album produces a stale mapping error. Intentional member removal is reversed by the next sync.
- Multi-process locking, automatic retry after uncertain writes, and user notifications are future work.
