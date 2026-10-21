import bpy
from mathutils import Vector


def ok(resp):
    assert resp["ok"], resp.get("error")
    return resp["result"]


def err(resp):
    assert not resp["ok"], resp
    return resp["error"]


def _evaluated(name):
    obj = bpy.data.objects[name]
    dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(dg).to_mesh()
    pts = [obj.matrix_world @ v.co for v in me.vertices]
    faces = [len(p.vertices) for p in me.polygons]
    return pts, faces


def _body(call):
    """A capsule-ish torso: UV sphere 0.3 m wide, 1 m tall, centred at z 1."""
    ok(call("create_primitive", kind="uv_sphere", name="Body", location=[0, 0, 1], scale=[0.15, 0.12, 0.5],
            segments=32, rings=16))
    bpy.data.objects["Cube"].hide_set(True)


def test_armor_plate_front(call):
    _body(call)
    out = ok(call("armor_plate", name="Chest.L", body="Body", view="front", inset=0.01, thickness=0.01,
                  bottom=[[0, 1.0], [0.08, 1.0]], right=[[0.08, 1.0], [0.08, 1.2]],
                  top=[[0, 1.2], [0.08, 1.2]], left=[[0, 1.0], [0, 1.2]], material="Orange"))
    raw = bpy.data.objects["Chest.L"].data
    assert all(len(p.vertices) == 4 for p in raw.polygons), "plate grid must be all quads"
    assert [m.type for m in bpy.data.objects["Chest.L"].modifiers] == ["MIRROR", "SOLIDIFY", "BEVEL",
                                                                       "WEIGHTED_NORMAL"]
    pts, _ = _evaluated("Chest.L")
    xs = [p.x for p in pts]
    assert min(xs) < -0.07 and max(xs) > 0.07, "mirrored to both sides"
    assert all(0.95 < p.z < 1.25 for p in pts)
    # The outer face sits on the body's front pushed out by the inset (front of the sphere: y ~ -0.12).
    assert min(p.y for p in pts) < -0.12 and min(p.y for p in pts) > -0.16
    assert out["grid"][0] >= 3 and bpy.data.objects["Chest.L"].data.materials[0].name == "Orange"


def test_armor_plate_on_a_limb(call):
    ok(call("create_primitive", kind="cylinder", name="Leg", location=[0.1, 0, 0.5], scale=[0.06, 0.06, 0.4],
            segments=24))
    axis = [[0.1, 0, 0.9], [0.1, 0, 0.1]]
    for view in ("front", "back"):
        ok(call("armor_plate", name=f"Shin_{view}", body="Leg", view=view, inset=0.008, mirror=False,
                limb_axis=axis, bottom=[[0.04, 0.3], [0.16, 0.3]], right=[[0.16, 0.3], [0.16, 0.6]],
                top=[[0.04, 0.6], [0.16, 0.6]], left=[[0.04, 0.3], [0.04, 0.6]]))
    for view, sign in (("front", -1), ("back", 1)):
        pts, _ = _evaluated(f"Shin_{view}")
        radial = [((p.x - 0.1) ** 2 + p.y ** 2) ** 0.5 for p in pts]
        assert max(radial) < 0.075, "plate hugs the limb (no ray landed on something else)"
        assert sum(p.y * sign for p in pts) > 0, f"{view} plate is on the {view}"
        # It wraps round to the sides: the plate reaches the leg's left and right silhouettes.
        assert min(p.x for p in pts) < 0.05 and max(p.x for p in pts) > 0.15


def test_armor_plate_errors(call):
    _body(call)
    assert "view must be" in err(call("armor_plate", name="P", body="Body", view="diagonal", bottom=[[0, 0], [1, 0]],
                                      right=[[1, 0], [1, 1]], top=[[0, 1], [1, 1]], left=[[0, 0], [0, 1]]))["message"]
    assert "at least 2" in err(call("armor_plate", name="P", body="Body", view="front", bottom=[[0, 0]],
                                    right=[[1, 0], [1, 1]], top=[[0, 1], [1, 1]], left=[[0, 0], [0, 1]]))["message"]
    assert "No object" in err(call("armor_plate", name="P", body="Nope", view="front", bottom=[[0, 0], [1, 0]],
                                   right=[[1, 0], [1, 1]], top=[[0, 1], [1, 1]], left=[[0, 0], [0, 1]]))["message"]


def test_shell_cap_is_a_clean_dome(call):
    ok(call("shell_cap", name="Pad.L", centre=[0.2, 0, 1.4], radii=[0.08, 0.07, 0.06], up=[0.5, 0, 0.86],
            across=[0.86, 0, -0.5], coverage=90, resolution=10, mirror=True))
    obj = bpy.data.objects["Pad.L"]
    assert len(obj.data.polygons) == 100 and all(len(p.vertices) == 4 for p in obj.data.polygons)
    pts, _ = _evaluated("Pad.L")
    apex = Vector((0.2, 0, 1.4)) + Vector((0.5, 0, 0.86)).normalized() * 0.06
    assert min((p - apex).length for p in pts) < 0.01
    assert min(p.x for p in pts) < -0.1, "mirrored"
    # Normals point away from the centre (outer face out).
    f = obj.data.polygons[55]
    assert f.normal.dot(f.center - Vector((0.2, 0, 1.4))) > 0


def test_rounded_segment(call):
    ok(call("rounded_segment", name="Finger", start=[0, 0, 1], end=[0, 0, 0.96], width=0.012, depth=0.012,
            mirror=False))
    obj = bpy.data.objects["Finger"]
    assert all(len(p.vertices) == 4 for p in obj.data.polygons)
    pts, faces = _evaluated("Finger")
    assert all(n == 4 for n in faces)
    assert 0.955 < min(p.z for p in pts) and max(p.z for p in pts) < 1.005
    assert "same point" in err(call("rounded_segment", name="X", start=[0, 0, 0], end=[0, 0, 0], width=1,
                                    depth=1))["message"]
