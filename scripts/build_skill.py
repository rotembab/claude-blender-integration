"""Zip the blender-builder skill into dist/ for uploading to Claude Desktop or claude.ai."""

import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "agent" / "skills" / "blender-builder"


def main():
    out = ROOT / "dist" / "blender-builder-skill.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SRC.rglob("*")):
            if path.is_file():
                # The skill folder at the zip root, the layout skill uploads expect.
                zf.write(path, (pathlib.Path(SRC.name) / path.relative_to(SRC)).as_posix())
    print(out)


if __name__ == "__main__":
    main()
