"""Zip addon/claude_blender into dist/ for Blender's "Install from Disk"."""

import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "addon" / "claude_blender"


def main():
    version = re.search(r'^version = "([^"]+)"', (SRC / "blender_manifest.toml").read_text(), re.M).group(1)
    out = ROOT / "dist" / f"claude_blender-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SRC.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                # Files at the zip root: the layout Blender 4.2+ extensions expect.
                zf.write(path, path.relative_to(SRC).as_posix())
    print(out)


if __name__ == "__main__":
    main()
