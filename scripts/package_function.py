"""Build a Flex Consumption source ZIP with host.json at the archive root."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
PACKAGE = ROOT / "build" / "guard-storage.zip"


def main() -> None:
    files = [
        SOURCE / "function_app.py",
        SOURCE / "host.json",
        SOURCE / "requirements.txt",
        *sorted((SOURCE / "storage_guard").glob("*.py")),
    ]
    PACKAGE.parent.mkdir(exist_ok=True)
    with ZipFile(PACKAGE, "w", compression=ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, file.relative_to(SOURCE))
    print(PACKAGE)


if __name__ == "__main__":
    main()
