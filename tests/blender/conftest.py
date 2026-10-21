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


@pytest.fixture
def render_child(tmp_path):
    """Run a script that renders in a child process and pass if it prints RENDER_OK.

    Rendering needs a GPU context (or Mesa EGL on Linux). Without one Blender aborts the whole
    process, so a crash skips the test unless CI says rendering must work (CLAUDE_REQUIRE_RENDER).
    The script gets the addon folder and this tests folder as sys.argv[1:3]."""
    import os
    import subprocess

    def _run(code):
        script = tmp_path / "render_child.py"
        script.write_text("import sys\nsys.path[:0] = sys.argv[1:3]\n" + code)
        here = pathlib.Path(__file__).resolve().parent
        proc = subprocess.run([sys.executable, str(script), str(REPO / "addon"), str(here)],
                              capture_output=True, text=True, timeout=600)
        if "RENDER_OK" in proc.stdout:
            return
        # POSIX reports a signal as a negative code; Windows reports NTSTATUS codes like 0xC0000005.
        crashed = proc.returncode < 0 or proc.returncode >= 0xC0000000 or "Fatal Python error" in proc.stderr
        if crashed and not os.environ.get("CLAUDE_REQUIRE_RENDER"):
            pytest.skip("no GPU/EGL context for Workbench rendering here")
        pytest.fail(f"render child failed (rc={proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-3000:]}")

    return _run


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
