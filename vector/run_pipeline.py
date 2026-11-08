#!/usr/bin/env python3
"""
run_pipeline.py - Phase 4, steps 1-3 in one command (works on Windows, macOS and Linux).

    python run_pipeline.py              # chunk -> embed -> load ChromaDB
    python run_pipeline.py --no-download   # never try to download the PDFs

If manuals/ has no PDFs, it first tries to download and extract the course's UnstructuredData.zip.
Afterwards: run the notebook (vector_benchmark.ipynb) or  python src/benchmark.py
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from paths import MANUALS  # noqa: E402

DATA_URL = "https://622.gomillion.org/data/UnstructuredData.zip"


def has_docs() -> bool:
    return any(p.suffix.lower() in {".pdf", ".txt"} for p in MANUALS.glob("*"))


def download_manuals():
    print(f"manuals/ is empty - downloading {DATA_URL}")
    MANUALS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "data.zip"
        urllib.request.urlretrieve(DATA_URL, zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(Path(tmp) / "x")
        n = 0
        for p in (Path(tmp) / "x").rglob("*"):
            if p.is_file() and p.suffix.lower() in {".pdf", ".txt"} and "__MACOSX" not in p.parts:
                shutil.copy2(p, MANUALS / p.name)
                n += 1
    print(f"  extracted {n} files into {MANUALS}")


def run(script: str, *args: str):
    cmd = [sys.executable, str(SRC / script), *args]
    print("\n$ " + " ".join(Path(c).name if i == 1 else c for i, c in enumerate(cmd)), flush=True)
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--batch-size", type=int, default=32, help="embedding batch size")
    args = ap.parse_args()

    if not has_docs():
        if args.no_download:
            sys.exit(f"No PDFs in {MANUALS}. Copy the 25 documents there and rerun.")
        try:
            download_manuals()
        except Exception as exc:
            sys.exit(f"Download failed ({exc}). Copy the PDFs into {MANUALS} manually and rerun.")

    run("chunker.py")
    run("embed.py", "--batch-size", str(args.batch_size))
    run("vectordb.py", "build")
    print("\nPipeline complete. Next: open vector_benchmark.ipynb (or run: python src/benchmark.py)")


if __name__ == "__main__":
    main()
