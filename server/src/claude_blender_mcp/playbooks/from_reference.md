# Model from a reference picture

> When: the user gives a picture (a turnaround sheet, concept art, a photo of an object or character) and wants a 3D model that matches it, usually rigged and exported. Ends with a review of what's missing.

## 0. Read the picture first

Look at it before calling any tool, and write down:

- which views it shows (front, side, back) and roughly where each sits, for `crop`;
- the subject's real height (default 1.8 m for an adult human figure);
- the rest pose (T-pose or A-pose) and the arm angle;
- which parts are simple shapes (a sphere head, cylinder limbs, a box) that are better rebuilt as primitives;
- the materials and colours.

If the picture is a real, identifiable person, check that the user is that person or has their consent before making a likeness. Otherwise offer a character inspired by it instead.

## 1. Set up the references

- `set_reference(image_path, view="front", height=..., crop=[...])` for every view in the picture. In a side view where the character faces picture-left, use `view="right"`.
- Check what comes back:
  - `cut_off_at_edge` should be empty for full-body work.
  - `subject_size_m` should be plausible.
  - In the profile, the head row should come out at about head width.
- If the background stays attached, raise tolerance to 0.1-0.15. If thin parts go missing, lower it.

## 2. Base mesh

Pick the first one that's available:

1. **Image-to-3D on the user's GPU.** `image_to_3d(image_path, crop=front_crop)`, then poll `image_to_3d_status(job_id, name="Base", height=...)` every 20-30 s. It gives the most detail: plates, fingers, faces.
   - If it says no server is running, tell the user how to start one (Hunyuan3D-2 `python api_server.py --port 8081`) and continue with option 2 meanwhile.
2. **`silhouette_mesh(name="Base")`.** Its outline matches the pictures and the cross-sections are rounded. It has no surface detail.

Check: `compare_to_reference(view=...)` for every view. Outline match (silhouette_iou) should be at least 0.90 before refining. If an image_to_3d mesh faces the wrong way, `transform(name, rotation=[0, 0, 180])` and `apply_transforms(name)`.

## 3. Refine against the picture

Work through the views in a loop: compare, fix the biggest differences, compare again.

- `largest_width_differences` names the heights to fix. Red in the overlay means too big, blue means missing.
- Rebuild parts that are simple shapes as primitives. For example, cut the blob head away with `mesh_edit(..., op="delete", select={"bounds": ...})` and add a `create_primitive(kind="uv_sphere", ...)` sized from `reference_to_world(...)`.
- Fix proportions with `sculpt_stroke(brush="grab", ...)` and add forms with clay and inflate. Aim strokes with `surface_points(...)`.
- Hard-surface plates and seams: `sculpt_stroke(brush="crease", ...)` along the seams, or model separate plates with `hard_surface_prop` techniques.
- Check: outline match ≥ 0.95 in each view, and nothing in the overlay that the eye notices.

## 4. Colour

- Quick: `paint_from_reference(name)` on the dense mesh. It carries the picture's lighting.
- Clean (better for stylised and hard-surface work): flat materials per region with `create_material(...)` and `assign_material(..., select=...)`.

## 5. Game mesh, UVs, bake

Follow `retopo_and_bake`. Use `bake_maps(low, high, maps=["DIFFUSE", "NORMAL"])` when the dense mesh is painted.

## 6. Rig and animate

Follow `rig_and_animate`.

- Measure the arm angle from the picture: `reference_to_world(view="front", points=[shoulder, wrist])`, then angle = atan(drop / reach).
- `rig_template(fit_to=..., arm_angle=...)`.
- Check the joints with `capture_views(objects=[mesh, rig], shading="xray")` and move legs and arms to the limbs' centres with `edit_bones(...)`.

## 7. Preview export

Follow `export_to_engine`. Export a preview as soon as the rig works, so the user can drop it into the engine early. Use `export_model(path="<Name>_preview.fbx", preset="unreal")` (or unity), then run `reimport_check(...)`.

## 8. Review: what's missing and what to improve

End with a short review the user can act on. Write it from the evidence, not from memory:

1. **Numbers.** Outline match per view, plus model-outside and picture-not-covered from `compare_to_reference`. Triangles, bones, clips and texture size.
2. **Largest differences**, with heights and sizes (for example "upper arms 2.5 cm too wide at z = 1.1 m").
3. **What's missing.** Name each feature you can see in the picture but not in the model: panel lines, fingers, separate pieces, accessories, true materials. Look at the side-by-side images for this.
4. **What would improve it most, in order.** Concrete next steps with the tools that would do them, and what each would fix.

Save the review next to the exported files when there's a place for it, and keep the comparison images so the user can see the evidence.
