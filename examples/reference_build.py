"""Build a rigged, animated character from a turnaround sheet in a running Blender, end to end.

This is the from_reference playbook as a fixed script, for checking a setup and for seeing the
tools work together. (Claude does the same through the MCP tools, making the choices itself.)

    pip install -e server
    # In Blender: start the Claude bridge (N panel > Claude)
    python examples/reference_build.py sheet.png --front 0 0 0.4 1 --side 0.4 0 0.62 1 --back 0.62 0 1 1 \
        --arm-angle 58 --out build/robot [--hunyuan http://127.0.0.1:8081]

Crops are [left top right bottom] in 0-1 of the picture. Writes <out>_preview.fbx (Unreal),
<out>.glb and comparison images, and prints the numbers the review is built from.
"""

import argparse
import base64
import os
import time

from claude_blender_mcp.connection import BlenderConnection


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--front", nargs=4, type=float, required=True)
    ap.add_argument("--side", nargs=4, type=float)
    ap.add_argument("--back", nargs=4, type=float)
    ap.add_argument("--height", type=float, default=1.8)
    ap.add_argument("--arm-angle", type=float, default=0.0)
    ap.add_argument("--faces", type=int, default=6000, help="quad budget for the game mesh")
    ap.add_argument("--hunyuan", help="Hunyuan3D API server URL for the base mesh (else silhouette_mesh)")
    ap.add_argument("--out", default="build/character")
    args = ap.parse_args()
    image = os.path.abspath(args.image)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    conn = BlenderConnection()

    def call(cmd, timeout=600, **params):
        t = time.time()
        result = conn.call(cmd, params, timeout=timeout)
        print(f"{cmd}: {time.time() - t:.1f}s")
        return result

    def compare(tag):
        for view in [v for v in ("front", "right", "back") if v in refs]:
            res = call("compare_to_reference", view=view)
            with open(f"{out}_{tag}_{view}.png", "wb") as fh:
                fh.write(base64.b64decode(res.pop("png_base64")))
            print(f"  {view}: outline match {res['silhouette_iou']}, largest differences "
                  f"{res['largest_width_differences'][:2]}")

    # 1. References.
    refs = {}
    for view, crop in (("front", args.front), ("right", args.side), ("back", args.back)):
        if crop:
            refs[view] = call("set_reference", image_path=image, view=view, height=args.height, crop=crop)
    call("checkpoint", label="references set")

    # 2. Base mesh.
    if args.hunyuan:
        job = call("image_to_3d", image_path=image, server=args.hunyuan, crop=args.front)["job_id"]
        while True:
            time.sleep(20)
            st = call("image_to_3d_status", job_id=job, name="Base", height=args.height)
            print("  ", st["state"], st.get("server_status"), st["elapsed_seconds"], "s")
            if st["state"] != "running":
                break
        if st["state"] != "done":
            raise SystemExit(f"image_to_3d failed: {st.get('error')}")
    else:
        call("silhouette_mesh", name="Base")
    compare("base")

    # 3. Colour, game mesh, UVs, bake.
    call("paint_from_reference", name="Base")
    low = call("duplicate", name="Base", new_name="Character")["name"]
    call("quad_remesh", name=low, target_faces=args.faces, use_symmetry=True, timeout=900)
    call("cleanup", name=low, fill_holes=True)
    call("shade", name=low)
    call("uv_unwrap", name=low, method="smart", angle_limit=55)
    call("uv_pack", names=[low], margin=0.004)
    call("create_material", name="Character", assign_to=[low])
    call("bake_maps", low=low, high="Base", maps=["DIFFUSE", "NORMAL"], size=1024, cage_extrusion=0.02, timeout=1800,
         output_dir=os.path.dirname(out))
    call("run_python", code="o = bpy.data.objects['Base']; o.hide_set(True); o.hide_render = True")
    compare("lowpoly")

    # 4. Rig, skin, test, animate.
    call("rig_template", name="Rig", fit_to=low, arm_angle=args.arm_angle)
    rep = call("bind_mesh", mesh=low, armature="Rig", timeout=900)
    call("limit_weights", mesh=low, limit=4)
    rep = call("rig_report", mesh=low, armature="Rig")
    print(f"  skin: {rep['unweighted_verts']} unweighted verts, {rep['verts_over_influence_limit']} over 4 influences")
    for pose in call("pose_test", mesh=low, armature="Rig")["poses"]:
        for img in pose["images"]:
            with open(f"{out}_pose_{pose['pose']}_{img['view']}.png", "wb") as fh:
                fh.write(base64.b64decode(img["png_base64"]))
    for kind in ("walk", "idle"):
        call("procedural_cycle", armature="Rig", kind=kind)
        call("push_to_nla", name="Rig")

    # 5. Export and verify.
    call("export_model", path=f"{out}_preview.fbx", objects=[low], preset="unreal", timeout=900)
    call("export_model", path=f"{out}.glb", objects=[low], timeout=900)
    check = call("reimport_check", path=f"{out}_preview.fbx", timeout=900)
    print(f"  FBX: {check['tris']} tris, {check['bones']} bones, clips {[a['name'] for a in check['actions']]}, "
          f"materials {check['materials']}")
    print(f"Done: {out}_preview.fbx, {out}.glb and comparison images next to them")


if __name__ == "__main__":
    main()
