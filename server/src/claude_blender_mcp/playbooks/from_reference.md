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

## Quality bar

The user judges likeness by eye, from every angle, not by numbers. Work to these rules:

- **Model it like a 3D artist.** Build by hand: blockout, then forms, then detail. Every distinct piece in the picture gets its own part: plates, joint discs, collars, boots, fingers. Don't use `image_to_3d` unless the user asks for AI generation.
- **Detail all the time.** If you can see it in the picture, model it: panel seams, bevels and edge highlights, gaps between plates, fasteners, finger joints, and the sole and tread of boots. When in doubt, add the detail.
- **Real textures.** Use PBR materials per region: base colour, roughness and normal, with panel lines, subtle colour variation and edge wear baked in. Never ship flat placeholder colours or colour projected from the picture.
- **Judge the wireframe first.** A model is only good if its mesh is good. Before materials or textures, look at it with `reference_overlay(wireframe=true)` and check that every piece is clean quads with even spacing, loops that follow the forms and the joints, and no pinches, stretched faces or stray triangles. Show the user the wireframe before texturing.
- **Compare with the reference after every step.** Run `reference_overlay` in every view the reference has (front, side, back), on the whole figure and zoomed into regions (`region=[left, right, bottom, top]` in metres). Read positions off the reference rather than guessing, and fix what doesn't line up before moving on. For angles the reference doesn't show, such as 3/4, put a perspective render next to the picture and judge it by eye.
- **Never warp a finished mesh to chase the outline.** Fit proportions on the low-poly base mesh or the cage. Pushing vertices around after modifiers wrecks the topology and the plate shapes.
- **Outline match is not likeness.** `silhouette_iou` only checks the outline. A blob can score 0.96 and look nothing like the picture. Always also compare `capture_views` at `iso` (3/4) and side angles with the picture, and fix what the eye notices.

## 2. Blockout and base mesh

Build the proportions from primitives: `create_primitive`, `transform`, `mesh_edit`, `add_modifier`.

- **For characters, the blockout becomes a clean base mesh.** Box-model one connected, all-quad body:
  - a torso tube that continues into the neck;
  - arm tubes bridged into small quad holes on the torso's sides (`mesh_edit` bridge loops);
  - leg tubes bridged into the torso's bottom, split at the crotch;
  - quad caps on the ends.
- Model only the left half, with a Mirror modifier (clipping on) and Subdivision Surface on top. About 300 cage faces is plenty for a body.
- Place the cage from the reference, then offset it until the subdivided surface lands on the measured outline. Subdivision shrinks a cage.
- For an armored character, the base body is the under-suit, a few millimetres inside the armor's outer surface.

- Take sizes from the profile `set_reference` returns, and from `reference_to_world(view, points=[...])` on landmarks: shoulder, elbow, wrist, hip, knee, ankle, chin.
- Start with one part per body segment. Mirror with a Mirror modifier and model only one side.
- Check: `compare_to_reference` in every view, outline match ≥ 0.90. Then `capture_views(views=["front", "right", "iso"])` next to the picture. Fix proportions before adding any detail.

(`silhouette_mesh` gives a quick outline hull to model over or measure against. It is a guide, not the model.)

## 3. Forms and detail

Turn each blockout part into the real piece, part by part, comparing each with the picture as you go.

- **Hard surface (armor, robots, props):**
  - Shape the plates with `mesh_edit` (extrude, inset, bevel), boolean cuts, and Bevel and Solidify modifiers. Follow `hard_surface_prop`.
  - Keep plates as separate pieces with real gaps between them, and leave the dark under-suit visible where the picture shows it.
  - Lay plates onto the base body with `armor_plate`:
    - build the under-suit (the base mesh) about 12-15 mm inside the reference outline, so plates stand proud of it the way they do in the picture;
    - zoom `reference_overlay` on the part and read the panel's outline in metres, in the view that faces it (a grid helps: `run_python` can draw one over the picture);
    - pass the outline as four sides; `armor_plate` fills it with an even quad grid, lays it onto the body and adds Solidify, Bevel and Weighted Normal;
    - give plates real thickness (10-16 mm on a human-sized suit) and a 1-2 mm gap, so panel lines read as gaps;
    - on arms and legs pass `limb_axis` (the limb's centreline), and trace the front and back halves in the front and back views; they wrap round the limb;
    - a front/back pair must meet on one side seam: add `seam_range` (front `[-90, 90]`, back `[-270, -90]`) and `seam_sides: ["left", "right"]`. Outlines traced in one view stop short of the side, which leaves a strip of under-suit or an overlapping slab there;
    - add `fair` (10-30) on limb plates. If a plate still shows a crease, check the base body under it for the same crease and fix it there (smooth the base cage), not on the plate;
    - for parts no single view draws (a strap over the instep, a counter round the heel), use view `"limb"` with an axis along the foot or a vertical axis at the heel, and give the outline straight in (theta, t);
    - use `fold` for facets (the crease under a pectoral plate) and `dome` for bulges.
  - Domed pieces (shoulder pads, kneecaps, joint discs, helmets): `shell_cap`, fitted to the outline in two views.
  - Hands: `build_hand`, one connected all-quad mesh (palm box with the fingers and thumb extruded from it), never separate finger pieces.
  - Wrist cuffs, struts and boot blocks: `rounded_segment`.
  - Every joint disc mounts on something (a joint block or the suit): nothing floats or clips into a neighbouring piece. Check joints in the side and back views.
  - Model panel lines as insets or cuts, not paint.
- **Organic forms (muscles, cloth, faces):** sculpt on a dense copy, following `detailed_sculpt`.
- **Hands:** one connected mesh with knuckle loops (`build_hand`), matching the picture's pose in front and side views.
- Check at every part:
  - `reference_overlay` in front, side and back, zoomed in on the part, with the wireframe on.
  - `capture_views` close up, plus `iso`, next to the picture.
  - Name every feature visible in the picture that the part still lacks, and keep going until there are none worth adding.
  - The outline match should stay ≥ 0.95.

## 4. Materials and textures

- Make one PBR material per surface type the picture shows. For example: orange painted armor (roughness about 0.45), dark rubber or under-suit (about 0.7), glossy head (about 0.25), and metal fasteners.
  - Use `create_material`, then `assign_material(..., select=...)` per part or face set.
- Add texture detail:
  - panel lines and plate gaps in the normal map, by baking from the modeled detail (`bake_maps`);
  - subtle colour variation;
  - edge wear on plate edges (lighter, rougher);
  - grime in the creases (an AO bake multiplied in).
- Check: render `capture_views(shading="material")` in `iso` and compare its colours with the picture. Hue and value should read the same at a glance.

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

1. **Side by side from every angle.** Front, side, back and 3/4 renders next to the picture. Say honestly whether it reads as the same character at a glance. Outline numbers come second and never stand in for this.
   Also report triangles, bones, clips and texture size.
2. **Largest differences**, with heights and sizes (for example "upper arms 2.5 cm too wide at z = 1.1 m").
3. **What's missing.** Name each feature you can see in the picture but not in the model: panel lines, fingers, separate pieces, accessories, true materials. Look at the side-by-side images for this.
4. **What would improve it most, in order.** Concrete next steps with the tools that would do them, and what each would fix.

Save the review next to the exported files when there's a place for it, and keep the comparison images so the user can see the evidence.
