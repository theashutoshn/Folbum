"""Build a source bundle for testing on a NAS without private local files."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "folbum-test-bundle.zip"
FILES = [ROOT / name for name in (
    "Dockerfile", "compose.yaml", ".dockerignore", ".env.example",
    "README.md", "QUICKSTART.txt",
)]
FILES += sorted((ROOT / "app").glob("*.py"))
FILES += sorted(path for path in (ROOT / "static").rglob("*") if path.is_file())

with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as bundle:
    for path in FILES:
        if not path.is_file():
            raise SystemExit(f"Missing bundle input: {path}")
        bundle.write(path, path.relative_to(ROOT).as_posix())
print(f"Created {OUTPUT} with {len(FILES)} public files")
