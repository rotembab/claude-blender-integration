import base64
import http.server
import json
import math
import threading
import time

import bpy
import numpy as np


def ok(resp):
    assert resp["ok"], resp.get("error")
    return resp["result"]


def err(resp):
    assert not resp["ok"], resp
    return resp["error"]


def _figure(path, w=200, h=400, colour=(0.9, 0.2, 0.1), body_w=60, offset=0):
    """A grey picture with a simple figure: a body block and a round head, feet 20 px above the bottom."""
    px = np.full((h, w, 4), [0.5, 0.5, 0.5, 1.0], np.float32)  # rows top-down
    cx = w // 2 + offset
    px[120:380, cx - body_w // 2:cx + body_w // 2, :3] = colour
    yy, xx = np.mgrid[0:h, 0:w]
    px[(yy - 80) ** 2 + (xx - cx) ** 2 <= 40 ** 2, :3] = colour
    img = bpy.data.images.new("fig", w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(px[::-1]).ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return str(path)


def _sheet(path):
    """Front (wide, red) and side (narrow, blue) views side by side in one picture."""
    front = _read(_figure(path.parent / "a.png"))
    side = _read(_figure(path.parent / "b.png", colour=(0.1, 0.2, 0.9), body_w=30))
    sheet = np.concatenate([front, side], axis=1)
    img = bpy.data.images.new("sheet", sheet.shape[1], sheet.shape[0], alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(sheet[::-1]).ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return str(path)


def _read(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1]


def test_set_reference_scales_and_profiles(call, tmp_path):
    path = _figure(tmp_path / "front.png")
    out = ok(call("set_reference", image_path=path, view="front", height=1.8))
    # Figure is 340 px tall (head top at row 40, feet at row 380) and 80 px wide at the head.
    mpp = 1.8 / 340
    assert abs(out["subject_size_m"][0] - 80 * mpp) < 3 * mpp
    assert out["cut_off_at_edge"] == []
    body = [p for p in out["profile"] if 0.3 < p["z"] < 1.2]
    assert all(len(p["spans"]) == 1 and abs((p["spans"][0][1] - p["spans"][0][0]) - 60 * mpp) < 3 * mpp for p in body)
    assert "Ref_front" in bpy.data.objects and bpy.data.objects["Ref_front"].empty_display_type == "IMAGE"
    feet, top = ok(call("reference_to_world", view="front", points=[[0.5, 380 / 400], [0.5, 40 / 400]]))["points"]
    assert abs(feet[2]) < 2 * mpp and abs(top[2] - 1.8) < 2 * mpp
    assert ok(call("list_references"))[0]["view"] == "front"
    assert "No image" in err(call("set_reference", image_path=str(tmp_path / "x.png")))["message"]


def test_crop_sheet_and_silhouette_mesh_and_paint(call, tmp_path):
    sheet = _sheet(tmp_path / "sheet.png")
    ok(call("set_reference", image_path=sheet, view="front", height=1.8, crop=[0, 0, 0.5, 1]))
    side = ok(call("set_reference", image_path=sheet, view="side", height=1.8, crop=[0.5, 0, 1, 1]))
    mpp = 1.8 / 340
    assert side["view"] == "right" and abs(side["subject_size_m"][0] - 80 * mpp) < 3 * mpp
    out = ok(call("silhouette_mesh", name="Hull", resolution=80))
    w, d, h = out["dimensions"]
    assert abs(h - 1.8) < 0.08 and abs(w - 80 * mpp) < 0.08  # widest at the round head
    body = np.array([v.co[:] for v in bpy.data.objects["Hull"].data.vertices if 0.5 < v.co.z < 1.0])
    body_w, body_d = np.ptp(body[:, 0]), np.ptp(body[:, 1])
    assert abs(body_w - 60 * mpp) < 0.06 and abs(body_d - 30 * mpp) < 0.06  # front and side outlines
    paint = ok(call("paint_from_reference", name="Hull"))
    assert paint["vertices_seen"] > paint["vertices"] * 0.5  # no back or left picture: those get filled in
    me = bpy.data.objects["Hull"].data
    col = np.empty(len(me.vertices) * 4, np.float32)
    me.color_attributes["Reference"].data.foreach_get("color_srgb", col)
    col = col.reshape(-1, 4)
    co = np.array([v.co[:] for v in me.vertices])
    nor = np.array([v.normal[:] for v in me.vertices])
    front = (nor[:, 1] < -0.9) & (co[:, 2] > 0.4) & (co[:, 2] < 1.2)
    side_facing = (nor[:, 0] > 0.9) & (co[:, 2] > 0.4) & (co[:, 2] < 1.2)
    assert front.any() and side_facing.any()
    assert col[front, 0].mean() > 0.7 and col[front, 2].mean() < 0.3  # red front picture
    assert col[side_facing, 2].mean() > 0.7  # blue side picture
    assert bpy.data.objects["Hull"].active_material.name == "Hull_reference"


def test_reference_errors(call, tmp_path):
    assert "set_reference first" in err(call("compare_to_reference", view="front"))["message"]
    assert "view must be" in err(call("set_reference", image_path=_figure(tmp_path / "f.png"), view="top"))["message"]
    assert "crop" in err(call("set_reference", image_path=_figure(tmp_path / "f.png"), crop=[0.5, 0, 0.2, 1]))["message"]


COMPARE_SCRIPT = r"""
import bpy, base64
import numpy as np
from claude_blender.handlers import dispatch
from test_reference import _figure
import pathlib, tempfile

def call(cmd, **params):
    r = dispatch({"id": 1, "cmd": cmd, "params": params})
    assert r["ok"], r
    return r["result"]

bpy.ops.wm.read_factory_settings(use_empty=True)
tmp = pathlib.Path(tempfile.mkdtemp())
call("set_reference", image_path=_figure(tmp / "f.png"), view="front", height=1.8)
call("silhouette_mesh", name="Hull", resolution=80)
out = call("compare_to_reference", view="front", resolution=256)
assert out["silhouette_iou"] > 0.85, out
assert base64.b64decode(out["png_base64"])[:4] == b"\x89PNG"
# A mesh twice too wide shows up as model outside the picture.
bpy.data.objects["Hull"].scale = (2, 1, 1)
wide = call("compare_to_reference", view="front", resolution=256)
assert wide["model_outside_picture"] > 0.5 and wide["largest_width_differences"][0]["difference"] > 0.1, wide
assert not any(o.name.startswith("_claude") for o in bpy.data.objects)

# Bones show up in renders as proxy shapes, which are removed afterwards.
call("rig_template", name="Rig", arm_angle=45)
shots = call("capture_views", views=["front"], objects=["Rig"], resolution=128, shading="xray")
assert shots["images"]
assert not any(o.name.startswith("_claude") for o in bpy.data.objects)
assert not any(m.name.startswith("_claude") for m in bpy.data.meshes)
print("RENDER_OK", flush=True)
"""


def test_compare_to_reference_and_bone_proxies(render_child):
    render_child(COMPARE_SCRIPT)


class _FakeHunyuan(http.server.BaseHTTPRequestHandler):
    glb = b""
    received = {}

    def log_message(self, *args):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "healthy"})
        elif self.path.startswith("/status/"):
            self._json(200, {"status": "completed", "model_base64": base64.b64encode(self.glb).decode()})
        else:
            self._json(404, {})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).received = data
        self._json(200, {"uid": "abc"})


def test_image_to_3d_bridge_with_fake_server(call, tmp_path):
    # The "generated" model: a 2 m tall box exported as GLB.
    ok(call("create_primitive", kind="cube", name="Box", scale=[0.25, 0.25, 1]))
    glb = tmp_path / "box.glb"
    ok(call("export_model", path=str(glb), objects=["Box"]))
    ok(call("delete", names=["Box", "Cube"]))
    _FakeHunyuan.glb = glb.read_bytes()
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeHunyuan)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        _FakeHunyuan.received = {}
        job = ok(call("image_to_3d", image_path=_figure(tmp_path / "f.png"), server=url, crop=[0, 0, 1, 1]))
        for _ in range(200):  # the job sends and polls in the background (every 3 s)
            st = ok(call("image_to_3d_status", job_id=job["job_id"], name="Base", height=1.8))
            if st["state"] != "running":
                break
            time.sleep(0.1)
        assert st["state"] == "done", st
        sent = _FakeHunyuan.received
        assert sent["texture"] is False and sent["type"] == "glb" and "num_inference_steps" not in sent
        assert base64.b64decode(sent["image"])[:4] == b"\x89PNG"
        assert st["imported"]["name"] == "Base"
        obj = bpy.data.objects["Base"]
        assert abs(obj.dimensions.z - 1.8) < 1e-3 and min(v.co.z for v in obj.data.vertices) > -1e-4
        assert len([o for o in bpy.data.objects if o.type == "MESH"]) == 1
    finally:
        server.shutdown()
    assert "No Hunyuan3D server" in err(call("image_to_3d", image_path=_figure(tmp_path / "g.png"),
                                             server="http://127.0.0.1:9"))["message"]
    assert "No job" in err(call("image_to_3d_status", job_id="nope"))["message"]


def test_rig_template_a_pose_keeps_pose_meaning(call):
    rig = ok(call("rig_template", name="Rig", arm_angle=50))
    assert rig["arm_angle"] == 50
    obj = bpy.data.objects["Rig"]
    ua = obj.data.bones["upper_arm.L"]
    d = (ua.tail_local - ua.head_local).normalized()
    assert abs(math.degrees(math.asin(-d.z)) - 50) < 0.5  # points 50° down
    pb = obj.pose.bones["upper_arm.L"]
    pb.rotation_mode = "XYZ"
    zs = []
    for r in (-20, 20):
        pb.rotation_euler = (math.radians(r), 0, 0)
        bpy.context.view_layer.update()
        zs.append((obj.matrix_world @ obj.pose.bones["hand.L"].tail).z)
    assert zs[1] > zs[0]  # +X still raises the arm
    # The walk lowers the arms from the T-pose by 70°; on a 50° A-pose rig that's 20° more.
    ok(call("procedural_cycle", armature="Rig", kind="walk"))
    bpy.context.scene.frame_set(1)
    assert abs(math.degrees(obj.pose.bones["upper_arm.L"].rotation_euler.x) + 20) < 1
