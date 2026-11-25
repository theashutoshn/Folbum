# Folbum feature lessons

## Selective album synchronization

Suppose your Photos source is called Gallery. You want an album for `Travel/Japan` and want to leave `Travel/Korea` out. Open **Sync**, choose Gallery, clear **Sync all folders, including new folders**, and check Japan. The preview shows what a sync would do with that choice.

### Why the picker and the preview show different folders

Folbum answers two questions. Which folders could you select? Which of those folders should this run sync? The picker needs every folder containing indexed media so you can choose Korea later. The preview and sync use only the selected folders. Both call the same planning function, which keeps their selection rules consistent.

### Follow one checkbox click through the code

1. **Discover the folders.** In `plan`, Folbum reads the Photos index, calculates each media item's folder relative to Gallery, and groups asset IDs by folder. It records the available folders and their counts before applying the selection. The relative path `Travel/Japan` distinguishes this folder from another folder named Japan elsewhere in Gallery. [app/engine.py](app/engine.py)
2. **Display the tree.** The server's `snapshot` returns the available paths, counts, configuration, and planned album rows. In the browser, `renderFolderTree` splits paths at each slash and builds a tree. Travel can therefore appear as an expandable parent even if it contains media only in subfolders. Its count includes its descendants. [app/server.py](app/server.py) · [static/app.js](static/app.js)
3. **Remember the choice.** Checking Japan updates a set of selected paths. The browser calls `saveSettings` with `selected_folders: ["Travel/Japan"]`. The server validates the list in `_update_config` and saves it to `config.json`. An empty list means “sync zero folders.” An absent selection means “sync all folders,” including folders that Photos indexes later. [static/app.js](static/app.js) · [app/server.py](app/server.py)
4. **Apply the plan.** When you run sync, `sync` reads the saved configuration and calls `plan` again. It finds or creates Japan's album, compares its current members with the planned asset IDs, then adds the missing IDs. Running sync twice with the same photos therefore adds each photo only once. The scheduler calls the same `sync` function. [app/engine.py](app/engine.py) · [app/server.py](app/server.py)

### Try it

With one indexed photo in each test folder, select only Japan, refresh the browser, and check that Japan is still selected. Sync once and look for its album in ZimaOS Photos. Then deselect Japan, select Korea, and add a second photo to Japan. Once Photos indexes it, sync again. Korea should get an album, and Japan's existing album should still contain just its first photo. Deselecting a folder stops future additions and preserves the album you already created.


## Renaming a synced album

Open **Sync**, find a synced folder in the album preview, and choose **Rename**. For example, rename the album for `Travel/Japan` to `Spring in Kyoto`. The preview shows the new album title above the original folder path.

### How the folder remembers its album

An album has a display name and a stable Photos ID. Imagine the first sync saved ID `42` for `Travel/Japan`. Future syncs can find album `42` even after its title changes. Folbum keeps that association in `sync_state.json`, scoped to the source and connection through `mapping_key`. [app/server.py](app/server.py)

1. The preview function `snapshot` marks a row as mapped when the saved folder association matches the album ID. The browser's `row` function shows Rename for every selected folder. Clicking it sends the source, folder, ID, and requested title to `/api/albums/rename`. For a selected folder without a saved mapping, Rename stores the chosen title in `planned_names.json`. Both preview and sync read it through `album_plan`. The first sync creates the album with that name and records its ID. [static/app.js](static/app.js) · [app/server.py](app/server.py)
2. The server's `rename_album` checks the current source, the saved ID, and the live album list under the sync lock. It rejects blank names and a name already used by another album. `PhotosClient.rename_album` sends the update for ID `42` and reads the list again to confirm the new title. [app/server.py](app/server.py) · [app/engine.py](app/engine.py)
3. On the next sync, `plan` resolves the saved ID and reads its current title from Photos. Albums already claimed by a folder are excluded from name matching for new folders. That matters if you later add a source folder called `Spring in Kyoto`: its photos should never be added to Japan's album merely because their names match. [app/engine.py](app/engine.py)

### Verify the mapping

Use a test folder with one indexed photo. Sync it, rename its album, and reload the preview. Check that the new title appears beside the same folder path. Add a second photo to the folder, wait for indexing, and sync again. In Photos, both photos should appear in the renamed album. The sync should add one photo and create zero albums if this is the only folder being synced.
