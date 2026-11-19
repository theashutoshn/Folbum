"""Compare a mounted Photos source with media already indexed by ZimaOS Photos."""

import os
from pathlib import Path, PurePosixPath


MEDIA_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff',
    '.heic', '.heif', '.mp4', '.mov', '.m4v', '.avi', '.mkv', '.3gp',
})


def filesystem_files(root):
    """Return eligible media paths relative to a read-only mounted source."""
    root = Path(root)
    if not root.is_dir():
        raise OSError('Mounted source directory is unavailable')

    def raise_walk_error(error):
        raise error

    paths = set()
    for directory, _, filenames in os.walk(root, followlinks=False, onerror=raise_walk_error):
        for filename in filenames:
            if filename.startswith('._') or filename in ('.DS_Store', 'Thumbs.db'):
                continue
            if Path(filename).suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            file_path = Path(directory) / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            paths.add(file_path.relative_to(root).as_posix())
    return paths


def indexed_files(assets, source):
    """Return indexed media paths relative to the selected Photos source."""
    source = source.rstrip('/')
    paths = set()
    for asset in assets:
        if asset.get('entry_type') == 'group' or asset.get('media_type') not in (None, 'img', 'video'):
            continue
        path = asset.get('path')
        if not isinstance(path, str):
            continue
        path = path.replace('\\', '/')
        if path.startswith('/'):
            if not path.startswith(source + '/'):
                continue
            relative = path[len(source) + 1:]
        else:
            relative = path
        parts = PurePosixPath(relative).parts
        if not parts or any(part in ('', '.', '..') for part in relative.split('/')):
            continue
        if PurePosixPath(relative).suffix.lower() in MEDIA_EXTENSIONS:
            paths.add(relative)
    return paths


def compare_paths(disk, indexed, sample_limit=8):
    missing = disk - indexed
    return {
        'status': 'ready',
        'disk_count': len(disk),
        'indexed_count': len(indexed),
        'missing_count': len(missing),
        'missing_sample': sorted(missing)[:sample_limit],
        'index_only_count': len(indexed - disk),
    }
