import os

import bpy
import pytest


def ok(resp):
    assert resp["ok"], resp.get("error")
    return resp["result"]


def err(resp):
    assert not resp["ok"], resp
    return resp["error"]


def _character(call):
    """A rough blocky humanoid mesh (1.8 m, T-pose, facing -Y) bound to rig_template."""
    parts = [
        ("cube", [0, 0, 1.25], [0.36, 0.22, 0.55]),   # torso
        ("cube", [0, 0, 1.68], [0.2, 0.2, 0.25]),     # head
        ("cube", [0.45, 0, 1.47], [0.6, 0.1, 0.1]),   # left arm
        ("cube", [-0.45, 0, 1.47], [0.6, 0.1, 0.1]),  # right arm
        ("cube", [0.11, 0, 0.5], [0.13, 0.13, 0.95]),  # left leg
        ("cube", [-0.11, 0, 0.5], [0.13, 0.13, 0.95]),
    ]
    names = []
    for i, (kind, loc, dims) in enumerate(parts):
        n = ok(call("create_primitive", kind=kind, name=f"part{i}", location=loc, scale=[d / 2 for d in dims]))["name"]
        ok(call("apply_transforms", name=n, location=True))
        names.append(n)
    ok(call("join", names=names))
    ok(call("delete", names=["Cube"]))
    ok(call("voxel_remesh", name="part0", voxel_size=0.03))
    bpy.data.objects["part0"].name = "Body"
    ok(call("rig_template", name="Rig", fit_to="Body"))
    return "Body", "Rig"


# --- materials ------------------------------------------------------------------


def test_create_and_assign_material(call):
    ok(call("create_material", name="Red", base_color=[1, 0, 0], roughness=0.3, assign_to=["Cube"]))
    mat = bpy.data.objects["Cube"].material_slots[0].material
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    assert tuple(bsdf.inputs["Base Color"].default_value)[:3] == (1, 0, 0)
    assert abs(bsdf.inputs["Roughness"].default_value - 0.3) < 1e-6


def test_assign_material_to_faces(call):
    ok(call("create_material", name="Blue", base_color=[0, 0, 1]))
    out = ok(call("assign_material", name="Cube", material="Blue", select={"normal": [0, 0, 1]}))
    assert out["faces"] == 1
    me = bpy.data.objects["Cube"].data
    blue = [s.material.name if s.material else None for s in bpy.data.objects["Cube"].material_slots].index("Blue")
    assert sum(1 for p in me.polygons if p.material_index == blue) == 1


def test_set_material_texture(call, tmp_path):
    img = bpy.data.images.new("t", 8, 8)
    path = str(tmp_path / "t.png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    ok(call("create_material", name="Tex"))
    ok(call("set_material_texture", material="Tex", input="normal", image_path=path))
    nodes = bpy.data.materials["Tex"].node_tree.nodes
    assert any(n.type == "NORMAL_MAP" for n in nodes)
    assert "No image" in err(call("set_material_texture", material="Tex", input="roughness", image_path=str(tmp_path / "x.png")))["message"]


# --- rig ------------------------------------------------------------------------


def test_rig_template_fits_mesh(call):
    ok(call("create_primitive", kind="cube", name="Tall", location=[2, 0, 1], scale=[0.3, 0.2, 1]))
    out = ok(call("rig_template", name="Rig", fit_to="Tall"))
    rig = bpy.data.objects["Rig"]
    assert out["bones"] == 22 and abs(out["height"] - 2.0) < 1e-3
    head = rig.data.bones["head"]
    assert abs((rig.matrix_world @ head.tail_local).z - 2.0) < 1e-3
    assert abs(rig.location.x - 2.0) < 1e-6
    assert not rig.data.bones["root"].use_deform


def test_edit_bones_add_update_remove(call):
    ok(call("rig_template", name="Rig"))
    ok(call("edit_bones", armature="Rig", bones=[
        {"name": "tail", "head": [0, 0.05, 0.95], "tail": [0, 0.4, 0.8], "parent": "hips"},
        {"name": "head", "deform": False},
    ], remove=["toe.L", "toe.R"]))
    bones = bpy.data.objects["Rig"].data.bones
    assert "tail" in bones and bones["tail"].parent.name == "hips"
    assert not bones["head"].use_deform and "toe.L" not in bones
    assert "zero length" in err(call("edit_bones", armature="Rig", bones=[{"name": "z", "head": [0, 0, 0], "tail": [0, 0, 0]}]))["message"]


def test_bind_auto_and_report_and_limit(call):
    body, rig = _character(call)
    rep = ok(call("bind_mesh", mesh=body, armature=rig))
    assert rep["bound"] and rep["unweighted_verts"] < rep["verts"] * 0.02
    ok(call("limit_weights", mesh=body, limit=2))
    rep = ok(call("rig_report", mesh=body, armature=rig, max_influences=2))
    assert rep["verts_over_influence_limit"] == 0 and rep["verts_not_normalized"] == 0


def test_pose_moves_mesh_and_reset(call):
    body, rig = _character(call)
    ok(call("bind_mesh", mesh=body, armature=rig))
    obj = bpy.data.objects[body]

    def lowest_left_hand_z():
        dg = bpy.context.evaluated_depsgraph_get()
        me = obj.evaluated_get(dg).to_mesh()
        z = min((obj.matrix_world @ v.co).z for v in me.vertices if (obj.matrix_world @ v.co).x > 0.6)
        obj.evaluated_get(dg).to_mesh_clear()
        return z

    rest = lowest_left_hand_z()
    ok(call("pose_bones", armature=rig, poses={"upper_arm.L": {"rotation": [-70, 0, 0]}}))
    bpy.context.view_layer.update()
    # The arm swings down, so verts that were out at the hand are now far below shoulder height.
    obj_dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(obj_dg).to_mesh()
    assert min((obj.matrix_world @ v.co).z for v in me.vertices) < rest  # something moved down
    obj.evaluated_get(obj_dg).to_mesh_clear()
    ok(call("reset_pose", armature=rig))
    assert tuple(bpy.data.objects[rig].pose.bones["upper_arm.L"].rotation_euler) == (0, 0, 0)


POSE_TEST_SCRIPT = r"""
import bpy
from claude_blender.handlers import dispatch
from test_rig_animate_export import _character

def call(cmd, **params):
    return dispatch({"id": 1, "cmd": cmd, "params": params})

body, rig = _character(call)
assert call("bind_mesh", mesh=body, armature=rig)["ok"]
resp = call("pose_test", mesh=body, armature=rig, views=["front"], resolution=64)
assert resp["ok"], resp
assert [p["pose"] for p in resp["result"]["poses"]] == ["arms_down_knee_up", "twist_and_reach"]
assert all(tuple(pb.rotation_euler) == (0, 0, 0) for pb in bpy.data.objects[rig].pose.bones)
print("RENDER_OK", flush=True)
"""


def test_pose_test_renders_and_resets(render_child):
    render_child(POSE_TEST_SCRIPT)


def test_rigify_metarig_and_generate(call):
    ok(call("create_primitive", kind="cube", name="Tall", location=[0, 0, 0.9], scale=[0.3, 0.2, 0.9]))
    meta = ok(call("rigify_metarig", fit_to="Tall"))
    assert meta["bones"] > 50
    gen = ok(call("rigify_generate", metarig=meta["name"]))
    assert gen["deform_bones"] > 30


def test_unirig_validates_setup(call, tmp_path):
    assert "UniRig checkout" in err(call("auto_rig_unirig", mesh="Cube", unirig_dir=str(tmp_path)))["message"]
    assert "No job" in err(call("auto_rig_status", job_id="nope"))["message"]


# --- animate --------------------------------------------------------------------


def test_keyframe_object_and_bones(call):
    ok(call("rig_template", name="Rig"))
    out = ok(call("keyframe", name="Rig", action="Wave", keys=[
        {"frame": 1, "location": [0, 0, 0], "bones": {"upper_arm.R": {"rotation": [0, 0, 0]}}},
        {"frame": 20, "location": [0, 1, 0], "bones": {"upper_arm.R": {"rotation": [60, 0, 0]}}},
    ], interpolation="LINEAR"))
    assert out["action"] == "Wave" and out["frame_range"] == [1.0, 20.0]
    bpy.context.scene.frame_set(10)
    assert 0.4 < bpy.data.objects["Rig"].location.y < 0.6
    assert "No pose bone" in err(call("keyframe", name="Rig", keys=[{"frame": 1, "bones": {"nope": {"rotation": [0, 0, 0]}}}]))["message"]


def test_procedural_walk_loops(call):
    ok(call("rig_template", name="Rig"))
    out = ok(call("procedural_cycle", armature="Rig", kind="walk", frames=32))
    assert "thigh.L" in out["bones"]
    rig = bpy.data.objects["Rig"]
    bpy.context.scene.frame_set(1)
    start = rig.pose.bones["thigh.L"].rotation_euler.x
    bpy.context.scene.frame_set(9)  # quarter cycle: left leg forward
    quarter = rig.pose.bones["thigh.L"].rotation_euler.x
    bpy.context.scene.frame_set(33)  # one full cycle later
    assert abs(rig.pose.bones["thigh.L"].rotation_euler.x - start) < 1e-4
    assert quarter < start - 0.2


@pytest.mark.parametrize("kind", ["run", "idle"])
def test_other_cycles(call, kind):
    ok(call("rig_template", name="Rig"))
    ok(call("procedural_cycle", armature="Rig", kind=kind))
    assert ok(call("list_actions", name="Rig"))[0]["name"] == f"Rig_{kind}"


def test_cycle_bone_map_required_for_foreign_rig(call):
    ok(call("edit_bones", armature=ok(call("rig_template", name="Rig"))["name"], bones=[]))
    ok(call("run_python", code="a = bpy.data.armatures.new('X'); o = bpy.data.objects.new('X', a); bpy.context.scene.collection.objects.link(o)"))
    ok(call("edit_bones", armature="X", bones=[{"name": "Bip_Pelvis", "head": [0, 0, 1], "tail": [0, 0, 1.1]}]))
    assert "bone_map" in err(call("procedural_cycle", armature="X"))["message"]
    out = ok(call("procedural_cycle", armature="X", bone_map={"hips": "Bip_Pelvis"}))
    assert out["bones"] == ["Bip_Pelvis"]


def test_nla_push_and_frame_tools(call):
    ok(call("rig_template", name="Rig"))
    ok(call("procedural_cycle", armature="Rig", kind="walk"))
    ok(call("push_to_nla", name="Rig"))
    ok(call("procedural_cycle", armature="Rig", kind="idle"))
    ok(call("push_to_nla", name="Rig"))
    names = {a["name"] for a in ok(call("list_actions", name="Rig"))}
    assert names == {"Rig_walk", "Rig_idle"}
    assert ok(call("set_frame_range", start=1, end=60, fps=30))["fps"] == 30
    assert ok(call("set_frame", frame=12))["frame"] == 12


# --- export ---------------------------------------------------------------------


@pytest.mark.parametrize("fmt,preset", [("fbx", "unity"), ("fbx", "unreal"), ("glb", "generic"), ("obj", "generic")])
def test_export_and_reimport_rigged_animated(call, tmp_path, fmt, preset):
    body, rig = _character(call)
    ok(call("bind_mesh", mesh=body, armature=rig))
    ok(call("procedural_cycle", armature=rig, kind="walk"))
    ok(call("push_to_nla", name=rig))
    path = str(tmp_path / f"char.{fmt}")
    out = ok(call("export_model", path=path, objects=[body], preset=preset))
    assert set(out["objects"]) == {body, rig}  # armature pulled in automatically
    n_objects = len(bpy.data.objects)
    rep = ok(call("reimport_check", path=path))
    assert len(bpy.data.objects) == n_objects  # the check cleaned up after itself
    assert rep["tris"] > 100
    if fmt != "obj":
        assert rep["bones"] >= 21  # deform bones only (root is not deforming)
        assert rep["skinned_meshes"]
        assert rep["actions"], rep


def test_export_bad_format(call, tmp_path):
    assert "format must be" in err(call("export_model", path=str(tmp_path / "x.blend")))["message"]
