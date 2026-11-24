# Folbum v0.2.1

Folbum creates albums from folders that ZimaOS Photos has indexed. Each album refers to the original photos and videos, which stay in their existing folders.

## Install on ZimaOS

**Installing v0.2.0?** Import the [corrected v0.2.0 Compose file](https://raw.githubusercontent.com/theashutoshn/Folbum/71282251966c6637a2e50f5ee5ec9de713d595f0/Apps/Folbum/docker-compose.yml) directly into ZimaOS. It uses the published v0.2.0 image and includes the data-folder permissions fix and dashboard icon URL. The original v0.2.0 source ZIP predates these installer fixes.

For v0.2.1, use the following steps once its release image is published.

1. Pull the release image on your NAS. If you already pulled this tag, continue to step 2.

   ```sh
   docker pull ghcr.io/theashutoshn/folbum:v0.2.1
   ```

2. In ZimaOS, choose **Install a customized app → Import → Docker Compose**. Copy the [Folbum install manifest](Apps/Folbum/docker-compose.yml) below, paste it into the Docker Compose tab, and click **Submit**.
   > [!NOTE]
    > Due to ZimaOs importer intervention, the mount type changes to bind from volume but since the bind type requires source to be any specific file or folder path on the host machine, the source now stays /app/data which docker interprets as a host filesystem. For the installation we will use mount type bind and source as absolute path.

   ```yaml
   name: folbum
   services:
     folbum:
       image: ghcr.io/theashutoshn/folbum:v0.2.1
       depends_on:
         folbum-data-init:
           condition: service_completed_successfully
       restart: unless-stopped
       ports:
         - target: 8765
           published: "8765"
           protocol: tcp
       environment:
         DATA_DIR: /app/data
       volumes:
         - type: bind
           source: /DATA/AppData/folbum/
           target: /app/data
         - type: bind
           source: /etc/localtime
           target: /etc/localtime
           read_only: true
           bind:
             create_host_path: false
       security_opt:
         - no-new-privileges:true
       cap_drop:
         - ALL
       read_only: true
       tmpfs:
         - /tmp:size=16m
       healthcheck:
         test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=5)"]
         interval: 30s
         timeout: 6s
         retries: 3
     folbum-data-init:
       image: ghcr.io/theashutoshn/folbum:v0.2.1
       user: "0:0"
       restart: "no"
       network_mode: none
       read_only: true
       security_opt:
         - no-new-privileges:true
       cap_drop:
         - ALL
       cap_add:
         - CHOWN
       volumes:
         - type: bind
           source: /DATA/AppData/folbum/
           target: /app/data
       command:
         - python
         - -c
         - |
           import os
           import pwd
           from pathlib import Path

           data = Path("/app/data")
           user = pwd.getpwnam("zima")
           owner = data.stat().st_uid
           if owner == 0:
               if any(data.iterdir()):
                   raise SystemExit("Existing root-owned Folbum data: verify ownership of the /app/data mount.")
               os.chown(data, user.pw_uid, user.pw_gid)
   volumes:
     app-data:
   x-casaos:
     id: com.theashutoshn.folbum
     main: folbum
     index: /
     port_map: "8765"
     scheme: http
     icon: https://raw.githubusercontent.com/theashutoshn/Folbum/v0.2.0/Apps/Folbum/icon.png
     title:
       en_US: Folbum
     tagline:
       en_US: Automatically turn indexed Photos folders into albums.
     description:
       en_US: Create and update an album for every indexed media folder. Albums use the last folder name. Preview changes before syncing; existing files stay in place.
     author: Ashutosh
     developer: Ashutosh
     category: Media
     architectures:
       - amd64
       - arm64
     version: "0.2.1"
     repo: https://github.com/theashutoshn/Folbum
   ```

3. Keep the `app-data` volume mounted at `/app/data`. The default host port is `8765`. If another app uses it, choose a free host port and keep the container port at `8765`. Click **Install**.
4. Open `http://NAS_IP:8765` on your trusted LAN, replacing `NAS_IP` with your NAS address and using the host port you selected. Create your Folbum username and a password of at least 12 characters, then sign in. The first person to open a fresh installation can create its account.

The installer runs `folbum-data-init` once to give Folbum access to a fresh, root-owned data folder. An exited initializer with status 0 is normal. The Folbum web service runs as the `zima` user. Both services must use the same data mount if you customize the storage path.

## Connect Photos and run your first sync

1. In **Connection**, click **+** and enter the address of your ZimaOS NAS and your ZimaOS login. Use a NAS address reachable from the container. Choose **Keep NAS connected** to retain the connection across restarts.
2. In **Sync**, choose a Photos source. Review the preview to see which albums Folbum will create or update, then run sync.
3. Open ZimaOS Photos to view the albums. To keep them up to date, choose an automatic sync interval in Folbum. The first scheduled sync starts after that interval.

Each folder containing indexed media gets an album named after the folder. When two folders share a name, Folbum uses their relative paths to distinguish them. Repeated syncs add missing items and preserve existing album members.

## Screenshots

**Connection** — Check whether Folbum can reach your ZimaOS NAS.

![Connection page showing a healthy NAS connection](Screenshot%202026-11-21%20172957.png)

**Sync** — Choose a Photos source, preview its albums, and run or schedule a sync.

![Sync page showing the selected gallery, manual sync controls, and up-to-date albums](Screenshot%202026-11-21%20172922.png)

**Dashboard** — See how many media items Photos has indexed and how many are in albums.

![Dashboard showing 2,848 indexed media items across 16 albums](Screenshot%202026-11-21%20172850.png)

## Data and updates

Folbum stores your account, settings, sync history, and saved connection tokens in the Docker volume mounted at `/app/data`. Keep the volume and its backups private. When updating Folbum, reuse this volume so your account and settings carry over.

Ordinary sync reads the Photos index and requires no gallery mount. For the optional **Dashboard** disk comparison, mount the matching NAS gallery folder read-only at `/media-source`, set `DISK_GALLERY_ROOT` to `/media-source`, and set `DISK_SOURCE_PATH` to the exact source path shown in **Sync**. See the [disk comparison configuration](compose.disk.yaml).

## Troubleshooting

- **Image pull fails.** Check that the image name and version match the release manifest. If the registry denies access, confirm the image is available to your NAS account.
- **Folbum cannot connect to Photos.** Check the address in **Connection**. Use the NAS network address. Inside Folbum, `localhost` points back to the container.
- **A photo is missing from the preview.** Refresh the source in ZimaOS Photos, wait for indexing to finish, then reload the Folbum preview.
- **Setup appears again after an update.** Check the volume mounted at `/app/data` and reconnect the volume from your previous Folbum installation before creating an account.

## License and support

Folbum is an unofficial companion to ZimaOS Photos. Folbum uses the [MIT License](LICENSE). The bundled Montserrat font uses the [SIL Open Font License 1.1](static/fonts/OFL-Montserrat.txt).

For installation questions and bug reports, use [Folbum Issues](https://github.com/theashutoshn/Folbum/issues) if you have repository access. Include your Folbum and ZimaOS versions, the step that failed, and the error message. Remove passwords, tokens and private NAS details before sharing logs or screenshots.
