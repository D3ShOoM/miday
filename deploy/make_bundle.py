"""Zip the app for uploading to PythonAnywhere (or any other host).

    .venv/bin/python deploy/make_bundle.py   ->   dist/miday.zip

Local state (.env, the database, collected static files) is left out, so
unzipping a newer bundle over an installed copy keeps its data and settings.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["manage.py", "requirements.txt", "run.sh", ".env.example", "README.md", "LICENSE", "config", "picker", "static", "deploy"]
SKIP_NAMES = {"__pycache__", "local_settings.py", ".DS_Store"}
OUT = ROOT / "dist" / "miday.zip"


def files():
    for item in INCLUDE:
        path = ROOT / item
        for file in [path] if path.is_file() else sorted(path.rglob("*")):
            rel = file.relative_to(ROOT)
            if file.is_file() and not SKIP_NAMES.intersection(rel.parts) and file.suffix != ".pyc":
                yield file, rel


def main():
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as bundle:
        count = 0
        for file, rel in files():
            bundle.write(file, rel)  # keeps the executable bit on run.sh
            count += 1
    print(f"{OUT}  ({count} files, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
