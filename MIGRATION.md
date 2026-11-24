# Folbum — Installation and Storage Migration

## Before installation (existing users only)

New users can skip this section and proceed directly to either solution below. Existing users retaining the same named volume (Solution 1) or the same absolute bind mount do not need to migrate their data. Backing up before an upgrade is still recommended.

Existing users switching from the named volume `folbum_app-data` to `/DATA/AppData/folbum` (Solution 2) must back up and migrate their data **before** reinstalling Folbum.

### Backup and migration

1. SSH into your NAS. Use `docker volume ls` and `docker inspect <container_name>` to confirm the existing volume mounted at `/app/data`. Replace the example volume name below if different. Stop the existing Folbum containers with `docker stop <container_name>` before copying. Do not delete the original volume.

2. Back up the named volume (run with Docker access, using `sudo` where needed):

   ```bash
   OLD_VOLUME=folbum_app-data
   BACKUP_DIR=/DATA/AppData/folbum-backup
   sudo mkdir -p "$BACKUP_DIR"
   sudo chmod 700 "$BACKUP_DIR"
   docker volume inspect "$OLD_VOLUME" >/dev/null && \
   sudo sh -c 'umask 077; docker run --rm --network none \
     --mount "type=volume,source=$1,target=/source,readonly" \
     alpine:3.20 tar -cpf - -C /source . > "$2/folbum-$(date +%Y%m%d-%H%M%S).tar"' sh "$OLD_VOLUME" "$BACKUP_DIR"
   ```

   Check that the backup exists and is readable using `sudo tar -tf /path/to/backup.tar` (replace with the actual archive path). Keep it private because it may contain authentication data. Stop if backup fails.

3. **Only for users switching to Solution 2:** Copy the old volume into the new host directory. The destination must be empty and all Folbum containers must be stopped.

   ```bash
   NEW_DIR=/DATA/AppData/folbum
   sudo mkdir -p "$NEW_DIR"
   docker volume inspect "$OLD_VOLUME" >/dev/null && \
   docker run --rm --network none \
     --mount "type=volume,source=$OLD_VOLUME,target=/source,readonly" \
     --mount "type=bind,source=$NEW_DIR,target=/destination" \
     alpine:3.20 sh -ec 'test -z "$(ls -A /destination)"; \
       tar -cpf /tmp/folbum.tar -C /source .; \
       tar -xpf /tmp/folbum.tar -C /destination; \
       diff -qr /source /destination'
   ```

   Proceed only if the command succeeds. Check ownership with `sudo ls -ldn "$NEW_DIR"` and compare with `docker run --rm --entrypoint id ghcr.io/theashutoshn/folbum:v0.2.1 zima`. After installation, verify your existing settings and album mappings. Keep the original volume and backup until the new installation is verified. Never use `docker compose down -v` during migration.

---


#### <u>Solution:</u>

1. **Install the original Compose using Docker CLI (Named Volume)**
    
    > Note: The below method requires SSH access and familiarity with Docker Compose, rather than the ZimaOS GUI.
    > 
    
    This bypasses the ZimaOS custom-app import interface and uses standard Docker Compose directly.
    
    SSH into your ZimaOS server and create a project directory (choose a location which you usually don’t access). Below is example:
    
    ```bash
    mkdir -p /DATA/AppData/folbum-install
    cd /DATA/AppData/folbum-install
    ```
    
    Then save your original unmodified (**where the mount type is volume**) Compose configuration as `compose.yaml`  Copy below compose content
    
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
          - type: volume
            source: app-data
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
          - type: volume
            source: app-data
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
    
    Validate it: `docker compose config -q`
    
    Start the application: `docker compose up -d`
    
    Check the services: `docker compose ps -a`
    
    **This method preserves the named-volume configuration and the permission initialization service.**
    
    **Disadvantage: You won’t be able to see Folbum Icon on the ZimaOS dashboard. You need to access it using `http://<YOUR_NAS_IP>:8765`**
    
2. **Use explicit bind mounts for GUI-compatible variant (Absolute bind mount)**
    
    Instead of using a named volume, configure both services to use an explicit absolute NAS directory.
    
    Replace the mount type to bind in both services and add source destination
    
    ```bash
    volumes:	
    	type: bind
    	source: /DATA/AppData/folbum
    	target: /app/data
    	bind:
    	create_host_path: false
    ```
    
    Keep the `/etc/localtime` mount unchanged in the main service.
    
    Before installing, create the directory:
    
    ```bash
    sudo mkdir -p /DATA/AppData/folbum
    ```
    
    Copy the below compose file content and paste in the application YAML. (**Install a customized app → Import → Docker Compose**.)
    
    ```yaml
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
          test:
            - CMD
            - python
            - -c
            - import urllib.request;
              urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=5)
          interval: 30s
          timeout: 6s
          retries: 3
      folbum-data-init:
        image: ghcr.io/theashutoshn/folbum:v0.2.1
        user: 0:0
        restart: no
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
          - >
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
      app-data: null
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
        en_US: Create and update an album for every indexed media folder. Albums use the
          last folder name. Preview changes before syncing; existing files stay in
          place.
      author: Ashutosh
      developer: Ashutosh
      category: Media
      architectures:
        - amd64
        - arm64
      version: 0.2.1
      repo: https://github.com/theashutoshn/Folbum
    ```
    
    <aside>
    ❗
    
    **Note: Changing from a named volume to a bind mount is safe when the destination is configured correctly and the original data is migrated. The danger is changing where the data lives without transferring it.**  **Never switch a working Folbum installation from one persistent storage location to another without first backing up and migrating its data**.
    
    </aside>