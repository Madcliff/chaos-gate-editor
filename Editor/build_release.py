"""Build both standalone ZIPs from a Linux runtime tarball and Windows wheels."""
# SPDX-License-Identifier: GPL-2.0-only
import argparse
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
PURE_PACKAGES = ("attr", "attrs", "archspec", "fsspec", "pyfmodex", "tpk_ar")


def distributable(path):
    return "__pycache__" not in path.parts and "libfmod" not in path.parts and path.suffix != ".pyc"


def stage_windows(editor, wheels, runtime_zip):
    with ZipFile(runtime_zip) as runtime:
        runtime.extractall(editor / "runtime")
    vendor = editor / "vendor"
    vendor.mkdir()
    for wheel in sorted(wheels.glob("*.whl")):
        with ZipFile(wheel) as package:
            for name in package.namelist():
                if distributable(Path(name)):
                    package.extract(name, vendor)
    for name in PURE_PACKAGES:
        shutil.copytree(ROOT / "vendor" / name, vendor / name, ignore=shutil.ignore_patterns("__pycache__"))
        for metadata in (ROOT / "vendor").glob(f"{name}-*.dist-info"):
            shutil.copytree(metadata, vendor / metadata.name)


def stage_linux(editor, runtime_tar):
    with tarfile.open(runtime_tar) as runtime:
        runtime.extractall(editor.parent, filter="data")
    bundled = editor / "runtime"
    (editor.parent / "python").rename(bundled)
    # The launcher uses the upstream standalone executable. Keep one copy
    # because ZIP extraction would otherwise turn its aliases into full files.
    for alias in ("python", "python3", "python3-config", "python3.14-config"):
        (bundled / "bin" / alias).unlink(missing_ok=True)
    for library in (bundled / "lib").glob("libpython*.so*"):
        library.unlink()
    shutil.rmtree(bundled / "include", ignore_errors=True)
    shutil.copytree(ROOT / "vendor", editor / "vendor",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "libfmod"))


def build(name, launcher, destination, stage):
    archive = destination / name
    with tempfile.TemporaryDirectory() as directory:
        staging = Path(directory)
        editor = staging / "Editor"
        editor.mkdir()
        for file in ("editor.py", "tree_layout.py", "index.html", "README.md", "LICENSE", launcher):
            shutil.copy2(ROOT / file, editor)
        shutil.copytree(ROOT / "docs", editor / "docs")
        stage(editor)
        with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=6) as output:
            for file in sorted(editor.rglob("*")):
                if file.is_file():
                    output.write(file, file.relative_to(staging))
    with ZipFile(archive) as output:
        bad = output.testzip()
        if bad:
            raise ValueError(f"Corrupt archive member {bad}")
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    print(archive, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-runtime", type=Path, required=True)
    parser.add_argument("--windows-wheels", type=Path, required=True)
    parser.add_argument("--linux-runtime", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT.parent / "dist")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    build("windows-x64-standalone.zip", "Start-Editor.cmd", args.out,
          lambda editor: stage_windows(editor, args.windows_wheels, args.windows_runtime))
    build("linux-x86_64-standalone.zip", "start-editor.sh", args.out,
          lambda editor: stage_linux(editor, args.linux_runtime))
