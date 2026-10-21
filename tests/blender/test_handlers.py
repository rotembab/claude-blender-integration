import threading

import bpy
import pytest


def ok(resp):
    assert resp["ok"], resp.get("error")
    return resp["result"]


def test_ping_and_commands(call):
    assert ok(call("ping"))["pong"] is True
    commands = ok(call("list_commands"))
    assert {"core", "look"} <= set(commands)
    assert "capture_views" in commands["look"]


def test_unknown_command(call):
    resp = call("nope")
    assert not resp["ok"] and resp["error"]["type"] == "UnknownCommand"


def test_bad_params_are_reported(call):
    resp = call("mesh_report", nam="Cube")
    assert not resp["ok"] and resp["error"]["type"] == "TypeError"


def test_scene_state_default_scene(call):
    state = ok(call("scene_state"))
    names = {o["name"]: o for o in state["objects"]}
    assert {"Cube", "Camera", "Light"} <= set(names)
    assert names["Cube"]["mesh"] == {"verts": 8, "faces": 6, "tris": 12}


def test_run_python_result_and_stdout(call):
    out = ok(call("run_python", code="bpy.ops.mesh.primitive_uv_sphere_add()\nprint('hi')\nresult = bpy.context.object.name"))
    assert out["result"] == "Sphere"
    assert "hi" in out["stdout"]
    assert "Sphere" in bpy.data.objects


def test_run_python_error_has_traceback(call):
    resp = call("run_python", code="x = 1\nraise ValueError('boom')")
    assert not resp["ok"]
    assert "ValueError: boom" in resp["error"]["message"]
    assert "<claude>" in resp["error"]["message"]


def test_checkpoint_and_rollback(call):
    first = ok(call("checkpoint", label="before sphere"))
    ok(call("run_python", code="bpy.ops.mesh.primitive_uv_sphere_add()"))
    second = ok(call("checkpoint", label="with sphere"))
    ok(call("run_python", code="bpy.data.objects.remove(bpy.data.objects['Cube'])"))
    assert "Cube" not in bpy.data.objects

    restored = ok(call("rollback", checkpoint_id=first["id"]))
    assert restored["discarded"] == [second["id"]]
    assert "Cube" in bpy.data.objects and "Sphere" not in bpy.data.objects
    assert [c["id"] for c in ok(call("list_checkpoints"))][-1] == first["id"]


def test_rollback_without_checkpoints(call):
    from claude_blender.handlers import core

    core._checkpoints.clear()
    resp = call("rollback")
    assert not resp["ok"] and "No checkpoints" in resp["error"]["message"]


def test_mesh_report_cube_and_open_mesh(call):
    rep = ok(call("mesh_report", name="Cube"))
    assert (rep["verts"], rep["quads"], rep["tris"], rep["ngons"]) == (8, 6, 12, 0)
    assert rep["non_manifold_edges"] == 0 and rep["boundary_edges"] == 0
    ok(call("run_python", code=(
        "import bmesh\nme = bpy.data.objects['Cube'].data\nbm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()\n"
        "bmesh.ops.delete(bm, geom=[bm.faces[0]], context='FACES_ONLY')\nbm.to_mesh(me); bm.free()"
    )))
    rep = ok(call("mesh_report", name="Cube"))
    assert rep["faces"] == 5 and rep["boundary_edges"] == 4


def test_mesh_report_evaluated_sees_modifiers(call):
    bpy.data.objects["Cube"].modifiers.new("sub", "SUBSURF").levels = 1
    assert ok(call("mesh_report", name="Cube", evaluated=False))["faces"] == 6
    assert ok(call("mesh_report", name="Cube", evaluated=True))["faces"] == 24


def test_object_details(call):
    bpy.data.objects["Cube"].modifiers.new("bev", "BEVEL")
    det = ok(call("object_details", name="Cube"))
    assert det["modifiers"][0]["type"] == "BEVEL"
    assert "width" in det["modifiers"][0]["settings"]
    assert det["scale_applied"] is True


def test_missing_object_is_command_error(call):
    resp = call("object_details", name="Nope")
    assert resp["error"]["type"] == "CommandError"


CAPTURE_SCRIPT = r"""
import base64, sys
sys.path.insert(0, sys.argv[1])
import bpy
from claude_blender.handlers import dispatch

scene = bpy.context.scene
before = (scene.render.engine, scene.camera.name, scene.render.resolution_x, len(bpy.data.objects))
resp = dispatch({"id": 1, "cmd": "capture_views",
                 "params": {"views": ["front", "top", "iso"], "resolution": 128, "shading": "wireframe"}})
assert resp["ok"], resp
out = resp["result"]
assert [i["view"] for i in out["images"]] == ["front", "top", "iso"]
assert base64.b64decode(out["images"][0]["png_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
after = (scene.render.engine, scene.camera.name, scene.render.resolution_x, len(bpy.data.objects))
assert after == before, (before, after)
assert not any(m.name == "_claude_wire" for m in bpy.data.objects["Cube"].modifiers)
print("CAPTURE_OK")
"""


def test_capture_views_restores_scene(tmp_path):
    # Rendering needs a GPU context (or Mesa EGL on Linux). Without one Blender aborts the whole
    # process, so run it in a child process and skip unless CI says rendering must work.
    import os
    import pathlib
    import subprocess
    import sys

    script = tmp_path / "capture.py"
    script.write_text(CAPTURE_SCRIPT)
    addon_dir = pathlib.Path(__file__).resolve().parents[2] / "addon"
    proc = subprocess.run([sys.executable, str(script), str(addon_dir)], capture_output=True, text=True, timeout=300)
    if "CAPTURE_OK" in proc.stdout:
        return
    # POSIX reports a signal as a negative code; Windows reports NTSTATUS codes like 0xC0000005.
    crashed = proc.returncode < 0 or proc.returncode >= 0xC0000000 or "Fatal Python error" in proc.stderr
    if crashed and not os.environ.get("CLAUDE_REQUIRE_RENDER"):
        pytest.skip("no GPU/EGL context for Workbench rendering here")
    pytest.fail(f"capture_views failed (rc={proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-3000:]}")


def test_socket_bridge_end_to_end():
    """MCP-side client -> socket -> queue -> main-thread dispatch -> response."""
    from claude_blender.server import BridgeServer
    from claude_blender_mcp.connection import BlenderConnection, BlenderError

    srv = BridgeServer(port=0)
    srv.start(use_timer=False)  # no event loop under the bpy module; drain by hand
    results = {}

    def client():
        conn = BlenderConnection(port=srv.port)
        results["ping"] = conn.call("ping")
        results["obj"] = conn.call("run_python", {"code": "result = len(bpy.data.objects)"})
        try:
            conn.call("object_details", {"name": "Nope"})
        except BlenderError as exc:
            results["err"] = str(exc)
        conn.close()

    t = threading.Thread(target=client)
    t.start()
    while t.is_alive():
        srv.process_pending()
        t.join(0.01)
    srv.stop()
    assert results["ping"]["pong"] is True
    assert results["obj"]["result"] == 3
    assert "No object named" in results["err"]


def test_addon_registers_and_unregisters():
    import claude_blender

    claude_blender.register()
    try:
        assert hasattr(bpy.types, "CLAUDE_PT_panel")
        assert bpy.ops.claude.start_bridge.poll() is not None
    finally:
        claude_blender.unregister()
    assert not hasattr(bpy.types, "CLAUDE_PT_panel")
