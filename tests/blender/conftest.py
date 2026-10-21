import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "addon"))
sys.path.insert(0, str(REPO / "server" / "src"))

bpy = pytest.importorskip("bpy", reason="needs the bpy module (pip install bpy) or Blender's Python")


@pytest.fixture(autouse=True)
def factory_scene():
    """Every test starts from Blender's default scene (cube, camera, light)."""
    bpy.ops.wm.read_factory_settings(use_empty=False)
    yield


@pytest.fixture
def call():
    from claude_blender.handlers import dispatch

    def _call(cmd, **params):
        return dispatch({"id": 1, "cmd": cmd, "params": params})

    return _call
