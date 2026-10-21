import math
import os

import bpy
import pytest


def ok(resp):
    assert resp["ok"], resp.get("error")
    return resp["result"]


def err(resp):
    assert not resp["ok"], resp
    return resp["error"]


# --- modeling -------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["cube", "uv_sphere", "ico_sphere", "cylinder", "cone", "plane", "grid", "circle", "torus"])
def test_create_primitive(call, kind):
    out = ok(call("create_primitive", kind=kind, name=f"P_{kind}", location=[1, 2, 3], rotation=[0, 0, 90], size=2))
    obj = bpy.data.objects[out["name"]]
    assert out["verts"] > 0
    assert tuple(round(v, 4) for v in obj.location) == (1, 2, 3)
    assert math.isclose(obj.rotation_euler.z, math.pi / 2, abs_tol=1e-6)


def test_torus_is_closed(call):
    name = ok(call("create_primitive", kind="torus", name="T", size=2, radius2=0.25, segments=24, rings=12))["name"]
    rep = ok(call("mesh_report", name=name))
    assert rep["boundary_edges"] == 0 and rep["non_manifold_edges"] == 0
    assert rep["faces"] == 24 * 12


def test_unknown_primitive(call):
    assert "Unknown primitive" in err(call("create_primitive", kind="teapot"))["message"]


def test_transform_relative_and_apply(call):
    ok(call("transform", name="Cube", scale=[2, 1, 1], rotation=[0, 0, 45]))
    ok(call("transform", name="Cube", location=[1, 0, 0], relative=True))
    out = ok(call("apply_transforms", name="Cube"))
    cube = bpy.data.objects["Cube"]
    assert tuple(cube.scale) == (1, 1, 1) and tuple(cube.rotation_euler) == (0, 0, 0)
    assert tuple(round(v, 3) for v in cube.location) == (1, 0, 0)
    assert max(out["dimensions"]) > 2.5  # rotated 2x-wide box baked into the mesh


def test_modifiers_add_set_apply(call):
    ok(call("add_modifier", name="Cube", type="SUBSURF", settings={"levels": 1}))
    ok(call("add_modifier", name="Cube", type="BEVEL", settings={"width": 0.1}))
    ok(call("set_modifier", name="Cube", modifier="Subsurf", settings={"levels": 2}))
    assert "stack order" in err(call("apply_modifiers", name="Cube", modifiers=["Bevel"]))["message"]
    out = ok(call("apply_modifiers", name="Cube", modifiers=["Subsurf"]))
    assert out["applied"] == ["Subsurf"] and out["faces"] == 96
    assert [m.name for m in bpy.data.objects["Cube"].modifiers] == ["Bevel"]


def test_bad_modifier_setting_is_rolled_back(call):
    e = err(call("add_modifier", name="Cube", type="SUBSURF", settings={"nope": 1}))
    assert "no setting" in e["message"]
    assert len(bpy.data.objects["Cube"].modifiers) == 0


def test_modifier_object_setting_by_name(call):
    ok(call("create_primitive", kind="cube", name="Mirror_Target"))
    ok(call("add_modifier", name="Cube", type="MIRROR", settings={"mirror_object": "Mirror_Target"}))
    assert bpy.data.objects["Cube"].modifiers["Mirror"].mirror_object.name == "Mirror_Target"


def test_boolean_difference(call):
    ok(call("create_primitive", kind="cylinder", name="Hole", size=1, depth=4, segments=16))
    out = ok(call("boolean", target="Cube", cutter="Hole"))
    assert out["faces"] > 6
    assert bpy.data.objects["Hole"].hide_get()
    assert not bpy.data.objects["Cube"].modifiers
    assert ok(call("mesh_report", name="Cube"))["non_manifold_edges"] == 0


def test_duplicate_delete_join_parent(call):
    ok(call("duplicate", name="Cube", new_name="Cube2", location=[3, 0, 0]))
    assert bpy.data.objects["Cube2"].data is not bpy.data.objects["Cube"].data
    out = ok(call("join", names=["Cube", "Cube2"]))
    assert out["verts"] == 16 and "Cube2" not in bpy.data.objects
    ok(call("set_parent", child="Light", parent="Cube"))
    assert bpy.data.objects["Light"].parent.name == "Cube"
    ok(call("delete", names=["Light"]))
    assert "Light" not in bpy.data.objects


def test_mesh_edit_extrude_top(call):
    out = ok(call("mesh_edit", name="Cube", op="extrude", select={"normal": [0, 0, 1]}, params={"distance": 1}))
    assert out["faces_selected"] == 1 and out["faces"] == 10
    assert math.isclose(bpy.data.objects["Cube"].dimensions.z, 3, abs_tol=1e-4)
    assert ok(call("mesh_report", name="Cube"))["non_manifold_edges"] == 0


@pytest.mark.parametrize("op,params", [
    ("inset", {"thickness": 0.2}),
    ("inset", {"thickness": 0.1, "individual": True}),
    ("bevel", {"width": 0.1, "segments": 2}),
    ("subdivide", {"cuts": 2}),
    ("scale", {"factor": [0.5, 0.5, 1]}),
    ("translate", {"offset": [0, 0, 0.5]}),
    ("triangulate", {}),
    ("flip_normals", {}),
    ("delete", {}),
])
def test_mesh_edit_ops(call, op, params):
    out = ok(call("mesh_edit", name="Cube", op=op, select={"normal": [0, 0, 1]}, params=params))
    assert out["faces_selected"] == 1


def test_mesh_edit_bounds_selector_and_empty(call):
    out = ok(call("mesh_edit", name="Cube", op="subdivide", select={"bounds": {"min": [0.5, -2, -2], "max": [2, 2, 2]}}))
    assert out["faces_selected"] == 1  # only the +X face center is inside
    assert "no faces" in err(call("mesh_edit", name="Cube", op="delete", select={"bounds": {"min": [5, 5, 5], "max": [6, 6, 6]}}))["message"]


# --- topology -----------------------------------------------------------------


def test_voxel_remesh_target_faces(call):
    ok(call("create_primitive", kind="uv_sphere", name="S", size=2))
    out = ok(call("voxel_remesh", name="S", target_faces=4000))
    assert 2000 < out["after"]["faces"] < 8000


def test_quad_remesh(call):
    ok(call("create_primitive", kind="uv_sphere", name="S", size=2, segments=64, rings=32))
    out = ok(call("quad_remesh", name="S", target_faces=400))
    rep = ok(call("mesh_report", name="S"))
    assert 200 < out["after"]["faces"] < 800
    assert rep["quads"] / rep["faces"] > 0.9


def test_decimate_to_budget(call):
    ok(call("create_primitive", kind="uv_sphere", name="S", segments=64, rings=32))
    out = ok(call("decimate", name="S", target_tris=1000))
    assert out["after"]["tris"] <= 1100


def test_cleanup_merges_and_deletes_loose(call):
    ok(call("run_python", code=(
        "import bmesh\nme = bpy.data.objects['Cube'].data\nbm = bmesh.new(); bm.from_mesh(me)\n"
        "bm.verts.new((5, 5, 5))\nfor v in list(bm.verts)[:8]: bm.verts.new(v.co)\n"
        "bm.to_mesh(me); bm.free()"
    )))
    out = ok(call("cleanup", name="Cube"))
    assert out["after"]["verts"] == 8
    assert out["merged_verts"] + out["deleted_loose"] == 9


def test_shade_auto_smooth(call):
    ok(call("shade", name="Cube", smooth=True, sharp_angle=30))
    me = bpy.data.objects["Cube"].data
    assert all(p.use_smooth for p in me.polygons)


# --- sculpt -------------------------------------------------------------------


def _sphere(call, faces=20000):
    ok(call("create_primitive", kind="ico_sphere", name="Head", size=2, subdivisions=3))
    ok(call("sculpt_prepare", name="Head", target_faces=faces))
    return bpy.data.objects["Head"]


def test_sculpt_prepare_is_dense_and_closed(call):
    obj = _sphere(call)
    rep = ok(call("mesh_report", name="Head"))
    assert rep["faces"] > 10000 and rep["boundary_edges"] == 0
    assert all(p.use_smooth for p in obj.data.polygons[:10])


def test_draw_raises_and_invert_lowers(call):
    obj = _sphere(call)
    top = [0, 0, 1]
    ok(call("sculpt_stroke", name="Head", brush="draw", points=[top], radius=0.3, strength=1.0, symmetry=""))
    z_up = max(v.co.z for v in obj.data.vertices)
    assert z_up > 1.02
    ok(call("sculpt_stroke", name="Head", brush="draw", points=[top] * 6, radius=0.3, strength=1.0, symmetry="", invert=True))
    assert max(v.co.z for v in obj.data.vertices) < z_up


def test_symmetry_mirrors_the_stroke(call):
    obj = _sphere(call)
    out = ok(call("sculpt_stroke", name="Head", brush="draw", points=[[0.7, -0.7, 0.2], [0.7, -0.6, 0.4]],
                  radius=0.2, strength=1.0, symmetry="X"))
    assert out["dabs"] > 2
    xs = [v.co.x for v in obj.data.vertices if v.co.length > 1.01]
    assert min(xs) < -0.4 and max(xs) > 0.4


@pytest.mark.parametrize("brush", ["clay", "blob", "inflate", "smooth", "flatten", "pinch", "crease"])
def test_brushes_move_vertices(call, brush):
    obj = _sphere(call, faces=8000)
    before = [v.co.copy() for v in obj.data.vertices]
    out = ok(call("sculpt_stroke", name="Head", brush=brush, points=[[0, -1, 0], [0.3, -0.95, 0.2]], radius=0.35, strength=0.8))
    moved = sum(1 for v, b in zip(obj.data.vertices, before) if (v.co - b).length > 1e-6)
    assert out["verts_moved"] > 0 and moved > 0


def test_grab_moves_by_delta(call):
    obj = _sphere(call, faces=8000)
    ok(call("sculpt_stroke", name="Head", brush="grab", points=[[0, -1, 0]], radius=0.4, delta=[0, -0.5, 0],
            falloff="constant", symmetry=""))
    assert min(v.co.y for v in obj.data.vertices) < -1.45


def test_sculpt_respects_object_transform(call):
    obj = _sphere(call, faces=8000)
    obj.location = (10, 0, 0)
    out = ok(call("sculpt_stroke", name="Head", brush="draw", points=[[10, 0, 1]], radius=0.3, symmetry=""))
    assert out["verts_moved"] > 0
    out = ok(call("sculpt_stroke", name="Head", brush="draw", points=[[0, 0, 1]], radius=0.3, symmetry=""))
    assert out["verts_moved"] == 0


def test_sculpt_rejects_modifiers_and_bad_brush(call):
    ok(call("add_modifier", name="Cube", type="SUBSURF"))
    assert "modifiers" in err(call("sculpt_stroke", name="Cube", brush="draw", points=[[0, 0, 1]], radius=1))["message"]
    assert "Unknown brush" in err(call("sculpt_stroke", name="Cube", brush="paint", points=[[0, 0, 1]], radius=1))["message"]
    ok(call("apply_modifiers", name="Cube"))
    assert "grab needs delta" in err(call("sculpt_stroke", name="Cube", brush="grab", points=[[0, 0, 1]], radius=1))["message"]


def test_symmetrize(call):
    obj = _sphere(call, faces=8000)
    ok(call("sculpt_stroke", name="Head", brush="draw", points=[[1, 0, 0]], radius=0.4, strength=1, symmetry=""))
    ok(call("symmetrize", name="Head", direction="+X"))
    xs = [v.co.x for v in obj.data.vertices]
    assert math.isclose(max(xs), -min(xs), rel_tol=0.02)


def test_smooth_mesh_and_surface_noise(call):
    _sphere(call, faces=8000)
    ok(call("smooth_mesh", name="Head", iterations=2))
    ok(call("surface_noise", name="Head", texture="VORONOI", scale=0.1, strength=0.02))
    assert not bpy.data.objects["Head"].modifiers
    assert "Unknown texture" in err(call("surface_noise", name="Head", texture="PLAID"))["message"]


# --- uv and bake ----------------------------------------------------------------


@pytest.mark.parametrize("method", ["smart", "angle_based", "cube"])
def test_uv_unwrap_methods(call, method):
    ok(call("create_primitive", kind="uv_sphere", name="S", segments=24, rings=12))
    out = ok(call("uv_unwrap", name="S", method=method, seams_from_angle=60 if method == "angle_based" else None))
    assert out["islands"] >= 1
    if method == "smart":
        assert out["overlap"] < 0.01 and out["faces_out_of_bounds"] == 0


def test_uv_report_detects_overlap(call):
    # Default cube UVs are a cross layout; stack all faces on the same square to force overlap.
    ok(call("run_python", code=(
        "me = bpy.data.objects['Cube'].data\nuv = me.uv_layers.active.data\n"
        "for p in me.polygons:\n"
        "    for i, li in enumerate(p.loop_indices):\n"
        "        uv[li].uv = [(0,0),(1,0),(1,1),(0,1)][i]"
    )))
    rep = ok(call("uv_report", name="Cube"))
    assert rep["overlap"] > 0.9 and rep["islands"] == 6


def test_uv_pack_two_objects(call):
    ok(call("create_primitive", kind="cube", name="B"))
    for n in ("Cube", "B"):
        ok(call("uv_unwrap", name=n, method="smart"))
    out = ok(call("uv_pack", names=["Cube", "B"], margin=0.02))
    assert all(r["faces_out_of_bounds"] == 0 for r in out.values())


def test_bake_normal_and_ao_from_sculpt(call, tmp_path):
    engine = bpy.context.scene.render.engine
    # High: a sphere with sculpted detail. Low: a plain sphere unwrapped.
    ok(call("create_primitive", kind="ico_sphere", name="High", subdivisions=5, size=2))
    ok(call("sculpt_stroke", name="High", brush="draw", points=[[0, -1, 0]], radius=0.4, strength=1))
    ok(call("create_primitive", kind="uv_sphere", name="Low", segments=24, rings=12, size=2, smooth=True))
    ok(call("uv_unwrap", name="Low", method="smart"))
    out = ok(call("bake_maps", low="Low", high="High", maps=["NORMAL", "AO"], size=64, samples=1,
                  output_dir=str(tmp_path), cage_extrusion=0.1))
    paths = [m["path"] for m in out["maps"]]
    assert all(os.path.getsize(p) > 0 for p in paths)
    mat = bpy.data.objects["Low"].material_slots[0].material
    assert any(n.type == "NORMAL_MAP" for n in mat.node_tree.nodes)
    assert bpy.context.scene.render.engine == engine


def test_bake_needs_uvs_and_high_for_normal(call):
    ok(call("create_primitive", kind="cube", name="NoUV"))
    assert "no UVs" in err(call("bake_maps", low="NoUV", maps=["AO"]))["message"]
    assert "needs high" in err(call("bake_maps", low="Cube", maps=["NORMAL"]))["message"]
