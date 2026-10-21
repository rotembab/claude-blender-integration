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


_exit_status = 0


def pytest_sessionfinish(session, exitstatus):
    global _exit_status
    _exit_status = int(exitstatus)


def pytest_unconfigure(config):
    # The bpy 4.2 wheel can segfault in its own interpreter-exit cleanup after every test has
    # passed (seen on Linux and macOS CI). Real Blender never exits this way, so leave right
    # after pytest has reported, with pytest's own status. On Windows os._exit still runs DLL
    # teardown (and crashes there too), so terminate the process outright instead.
    import os
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), _exit_status)
    os._exit(_exit_status)
