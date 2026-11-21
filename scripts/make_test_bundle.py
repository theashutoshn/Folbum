"""Build a source folder for testing on a NAS without private local files."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "folbum-test-bundle"
FILES = [ROOT / name for name in (
    "Dockerfile", "compose.yaml", ".dockerignore",
    "README.md", "QUICKSTART.txt", "LICENSE", "Apps/Folbum/docker-compose.yml",
)]
FILES += sorted((ROOT / "app").glob("*.py"))
FILES += sorted(path for path in (ROOT / "static").rglob("*") if path.is_file())

for path in FILES:
    if not path.is_file():
        raise SystemExit(f"Missing bundle input: {path}")

if OUTPUT.is_symlink() or OUTPUT.resolve() != ROOT / "folbum-test-bundle":
    raise SystemExit("Unsafe bundle output path")
if OUTPUT.exists():
    if not OUTPUT.is_dir():
        raise SystemExit(f"Bundle output is not a directory: {OUTPUT}")
    shutil.rmtree(OUTPUT)

for path in FILES:
    destination = OUTPUT / path.relative_to(ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
print(f"Created {OUTPUT} with {len(FILES)} public files")
