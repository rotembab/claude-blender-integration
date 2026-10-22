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


def _theta(obj, cx=0.1, cy=0.0):
    """Angle round a vertical limb at (cx, cy): 0 = front (-Y), +90 = +X."""
    import math
    out = []
    for v in obj.data.vertices:
        p = obj.matrix_world @ v.co
        out.append(math.degrees(math.atan2(p.x - cx, -(p.y - cy))) % 360)
    return out


def test_armor_plate_pair_shares_side_seams(call):
    ok(call("create_primitive", kind="cylinder", name="Leg", location=[0.1, 0, 0.5], scale=[0.06, 0.06, 0.4],
            segments=24))
    axis = [[0.1, 0, 0.9], [0.1, 0, 0.1]]
    # Outlines that stop short of the silhouette, as traced in each view.
    for view, rng in (("front", [-90, 90]), ("back", [-270, -90])):
        ok(call("armor_plate", name=f"Calf_{view}", body="Leg", view=view, inset=0.008, mirror=False, fair=10,
                limb_axis=axis, seam_range=rng, seam_sides=["left", "right"],
                bottom=[[0.07, 0.3], [0.13, 0.3]], right=[[0.13, 0.3], [0.13, 0.6]],
                top=[[0.07, 0.6], [0.13, 0.6]], left=[[0.07, 0.3], [0.07, 0.6]]))
    front = _theta(bpy.data.objects["Calf_front"])
    back = _theta(bpy.data.objects["Calf_back"])
    front = [t if t < 180 else t - 360 for t in front]
    assert min(front) < -85 and max(front) > 85, "front plate runs out to both side seams"
    assert min(back) > 90 - 2 and max(back) < 270 + 2, "back plate stays behind the seams"
    assert min(back) < 95 and max(back) > 265, "back plate reaches both side seams"
    assert all(len(p.vertices) == 4 for p in bpy.data.objects["Calf_back"].data.polygons)


def test_armor_plate_limb_view_wraps_a_heel(call):
    ok(call("create_primitive", kind="cylinder", name="Heel", location=[0.1, 0, 0.05], scale=[0.05, 0.05, 0.05],
            segments=24))
    axis = [[0.1, 0, 0.0], [0.1, 0, 0.1]]
    ths = [60 + 240 * k / 12 for k in range(13)]
    ok(call("armor_plate", name="Counter", body="Heel", view="limb", limb_axis=axis, inset=0.002, mirror=False,
            bottom=[[t, 0.2] for t in ths], right=[[300, 0.2], [300, 0.8]], top=[[t, 0.8] for t in ths],
            left=[[60, 0.2], [60, 0.8]], thickness=0.004, fair=5))
    th = _theta(bpy.data.objects["Counter"])
    assert min(th) > 55 and max(th) < 305 and any(170 < t < 190 for t in th), "wraps round the back only"
    zs = [(bpy.data.objects["Counter"].matrix_world @ v.co).z for v in bpy.data.objects["Counter"].data.vertices]
    assert 0.015 < min(zs) and max(zs) < 0.085


def test_armor_plate_errors(call):
    _body(call)
    assert "view must be" in err(call("armor_plate", name="P", body="Body", view="diagonal", bottom=[[0, 0], [1, 0]],
                                      right=[[1, 0], [1, 1]], top=[[0, 1], [1, 1]], left=[[0, 0], [0, 1]]))["message"]
    assert "at least 2" in err(call("armor_plate", name="P", body="Body", view="front", bottom=[[0, 0]],
                                    right=[[1, 0], [1, 1]], top=[[0, 1], [1, 1]], left=[[0, 0], [0, 1]]))["message"]
    assert "needs limb_axis" in err(call("armor_plate", name="P", body="Body", view="limb", bottom=[[0, 0], [1, 0]],
                                         right=[[1, 0], [1, 1]], top=[[0, 1], [1, 1]], left=[[0, 0], [0, 1]]))["message"]
    assert "seam_sides" in err(call("armor_plate", name="P", body="Body", view="front", limb_axis=[[0, 0, 0], [0, 0, 1]],
                                    seam_range=[-90, 90], seam_sides=["up"], bottom=[[0, 0], [1, 0]],
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


def test_build_hand_is_one_quad_mesh(call):
    out = ok(call("build_hand", name="Hand.L", wrist=[0.44, 0, 0.96], down=[0, 0, -1], across=[0, 1, 0],
                  palm_side=[-1, 0, 0], material="Orange", joint_material="Dark"))
    obj = bpy.data.objects["Hand.L"]
    me = obj.data
    assert all(len(p.vertices) == 4 for p in me.polygons)
    # One connected piece: walk the edges from vertex 0 and reach every vertex.
    adj = {v.index: set() for v in me.vertices}
    for e in me.edges:
        a, b = e.vertices
        adj[a].add(b)
        adj[b].add(a)
    seen, stack = {0}, [0]
    while stack:
        for n in adj[stack.pop()] - seen:
            seen.add(n)
            stack.append(n)
    assert len(seen) == len(me.vertices)
    assert [m.name for m in me.materials] == ["Orange", "Dark"]
    assert {p.material_index for p in me.polygons} == {0, 1}
    pts, _ = _evaluated("Hand.L")
    right = [p for p in pts if p.x > 0]
    # Fingers reach well past the palm (0.088 m) and the hand hangs below the wrist.
    assert 0.96 - min(p.z for p in right) > 0.14 and max(p.z for p in right) < 0.975
    assert out["faces"] == len(me.polygons)


def test_build_hand_errors(call):
    assert "parallel" in err(call("build_hand", name="H", wrist=[0, 0, 1], down=[0, 0, -1], across=[0, 0, 1],
                                  palm_side=[1, 0, 0]))["message"]
    assert "4 entries" in err(call("build_hand", name="H", wrist=[0, 0, 1], down=[0, 0, -1], across=[0, 1, 0],
                                   palm_side=[1, 0, 0], fingers=[[0.03, 0.02, 0.02]]))["message"]
