# Professional Blender practice

> When: always. These are the house rules for every build. Read this alongside the playbook for the job. They're how a senior 3D artist works in Blender, and how studios expect files to come back.

## Scene and file hygiene

- **Real-world scale.** Use metric units with a unit scale of 1.0, so 1 unit = 1 m. A person is about 1.8 m tall; a door is 2.1 m. Build at true size from the first primitive.
- **Apply transforms before modifiers that depend on scale, and before export:**
  - `apply_transforms` for rotation and scale; Bevel, Solidify and booleans act on unapplied scale.
  - Object origins: put a character's at the feet (0, 0, 0). Put a prop's where it rests or pivots.
- **Names, every time.**
  - Objects say what they are and which side: `Thigh_Plate.L`, `Boot_Sole.R`. Blender's `.L` / `.R` suffixes make mirroring and weight painting automatic.
  - No `Cube.003` survives to the end.
  - Engine assets use the engine's prefixes: `SK_` skeletal mesh, `SM_` static mesh, `M_` material, `T_<Name>_BaseColor` / `_Normal` / `_ORM` textures, `A_` or `<Rig>_<clip>` for animations.
- **Collections by role**, for example `Body`, `Armor`, `Joints`, `Details`, `Rig`, `Reference`. Reference images and helpers go in their own collection, hidden from render.
- **Save often, with checkpoints.** Take a `checkpoint` before every destructive step: applying modifiers, joining, remeshing, booleans.

## Modeling

- **Blockout first.** Primitives at the right size, checked against the reference from front, side and 3/4. No detail until the proportions read right.
- **Model one side.** Use a Mirror modifier (with clipping on the centre) for anything symmetric, and add asymmetry only at the end.
- **Stay non-destructive as long as you can.** Use modifier stacks rather than applied geometry: Mirror, then Solidify (shell thickness), then Bevel (angle-limited, 2-3 segments), then Weighted Normal. Apply them only for export or baking.
- **Hard surface:**
  - Separate pieces where the real object has separate pieces: plates, caps, bolts. Each piece needs real thickness (Solidify) and softened edges (Bevel), because perfectly sharp edges look CG and catch no highlight.
  - Panel lines: model them as gaps between pieces or insets. Fine engraving goes in the normal map.
  - Shading: auto smooth (Smooth by Angle, about 30-40°) plus Weighted Normal for flat, clean faces with crisp edges.
  - Use booleans for cut-ins, then clean up the result: `cleanup` (merge by distance, delete loose geometry).
- **Topology:**
  - Use quads on anything that deforms, with edge loops following the deformation: around elbows, knees, shoulders and the mouth. Add three loops at each bending joint.
  - Triangles and n-gons are fine on flat, rigid hard-surface faces, but never on faces that bend.
  - No non-manifold edges, no zero-area faces, no flipped normals. Check with `mesh_report`.
- **Density.** Spend polygons on the silhouette and on curvature people see, and keep flat areas sparse. Keep the density consistent between neighbouring parts.

## Sculpting (organic)

- Use dynamic topology or voxel remesh for the big forms, then multires for the fine detail.
- Work big to small: primary forms, then secondary (muscle groups, folds), then tertiary (pores, scratches).
- Keep the sculpt as `<Name>_high`. A game asset never ships the sculpt; retopologise it and bake (`retopo_and_bake`).

## UVs and texel density

- **Seams.** Put them where they hide: inside limbs, under arms, along hard edges, at the back. Hard-surface pieces get one island per plate face, split at sharp edges.
- **Keep texel density consistent** across the asset, with a little more on the face and hands for characters. Check with `uv_report`.
- **No overlaps** on anything that will be baked. Pack with margins of 4-8 px at the target resolution.

## Materials and textures (PBR)

- **Metal/roughness workflow.**
  - Base colour has no lighting baked in: no AO, no shadows, no highlights.
  - Metallic is 0 or 1. Use in-between values only on transitions such as wear.
  - Roughness carries most of the realism; vary it.
- **One material per surface type**, such as painted plate, rubber, bare metal or glass. Use texture variation within each one, rather than dozens of materials.
- **Textures tell the story:**
  - subtle colour variation;
  - edge wear on exposed edges (lighter and rougher, or bare metal);
  - grime and AO in crevices;
  - fine detail and engraving in the normal map.
  - Bake procedural detail to images for engines.
- **Maps for engines:**
  - BaseColor (sRGB);
  - Normal (Non-Color, OpenGL in Blender. Unreal expects DirectX, so flip G on import, or set the texture's Flip Green Channel);
  - ORM packed as R = AO, G = Roughness, B = Metallic (Non-Color).
  - Size: powers of two. 2048 for a hero character, 1024 for props.

## Rigging and animation

- **Bone names** use `.L` / `.R`. Deform bones are separate from control bones. For engines, export deform bones only, with a single root at the origin.
- **Weights:**
  - Rigid pieces (armor plates, robot parts) get 100% weight on one bone.
  - Soft parts get smooth falloff across the joint.
  - At most 4 influences per vertex for engines, and normalised. Check with `rig_report`.
- **Test before animating.** Stress-test with `pose_test`: arms up, deep knee bend and twist. Fix any collapsing or intersecting parts.
- **Clips:** one action per clip, pushed to the NLA, named `<Rig>_<clip>`, and looping cleanly (the first frame equals the last).

## Lighting and presentation

- Judge the model in a neutral studio: grey backdrop, a key light, fill and rim, and the Standard or AgX view transform. Never judge colour in solid view alone.
- Always check a 3/4 view, plus front, side and back, next to the reference.

## Export

- Follow `export_to_engine`: apply transforms, check scale and forward axis for the target engine, and embed or ship the textures.
- Re-import the exported file with `reimport_check` and confirm the triangle count, bones, clips and materials.
