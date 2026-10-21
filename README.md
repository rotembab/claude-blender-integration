# Claude Blender Integration

Open source bridge that gives Claude full, safe access to a live Blender session. The goal is complex work: sculpting, retopology, rigging, animation and game-ready export, not just stacking primitives.

It has three parts:

| Part | Where | What it does |
| --- | --- | --- |
| Blender addon | `addon/claude_blender` | Local socket server inside Blender. Runs every command on Blender's main thread. |
| MCP server | `server/` | Exposes the addon as MCP tools, grouped into toolsets. |
| Agent layer | `agent/` (coming in M3) | Claude skill with playbooks that plan multi-stage builds and check each stage. |

## Status

| Toolset | Tools |
| --- | --- |
| core | `get_scene_state`, `run_python`, `checkpoint`, `list_checkpoints`, `rollback` |
| look | `capture_views` (fixed-angle renders: solid, wireframe, x-ray), `get_object_details`, `mesh_report` |
| modeling | `create_primitive`, `transform`, `apply_transforms`, `add_modifier`, `set_modifier`, `apply_modifiers`, `boolean`, `duplicate`, `delete`, `join`, `set_parent`, `mesh_edit` (extrude, inset, bevel, subdivide... on faces picked by direction, bounds or material) |
| topology | `voxel_remesh`, `quad_remesh` (QuadriFlow), `decimate` (to a triangle budget), `cleanup`, `shade` |
| sculpt | `sculpt_prepare`, `sculpt_stroke` (draw, clay, blob, inflate, smooth, flatten, pinch, crease, grab, with symmetry), `symmetrize`, `smooth_mesh`, `surface_noise` |
| uv_bake | `uv_unwrap`, `uv_pack`, `uv_report` (islands, overlap, coverage, stretch), `bake_maps` (normal, AO, diffuse... from a high-poly mesh) |
| materials | `create_material`, `assign_material` (whole mesh or selected faces), `set_material_texture` |
| rig | `rig_template` (game humanoid fitted to a mesh), `edit_bones`, `rigify_metarig`, `rigify_generate`, `bind_mesh`, `rig_report`, `limit_weights`, `pose_bones`, `reset_pose`, `pose_test` (stress-pose renders), `auto_rig_unirig` + `auto_rig_status` (experimental) |
| animate | `keyframe`, `procedural_cycle` (walk, run, idle), `list_actions`, `set_action`, `push_to_nla`, `set_frame_range`, `set_frame` |
| export | `export_model` (FBX with Unity/Unreal/Godot presets, glTF, OBJ), `reimport_check` |

The sculpt brushes work on vertex positions with numpy instead of Blender's sculpt operators. Those operators need a 3D viewport under the mouse, so they can't be driven reliably from a script. The numpy brushes behave the same headless and in the UI.

### UniRig (experimental)

`auto_rig_unirig` runs a local [UniRig](https://github.com/VAST-AI-Research/UniRig) checkout through its `launch/inference` scripts (skeleton, then skin, then merge) in a background thread, so Blender stays responsive. `auto_rig_status` imports the result when it's done. You need UniRig installed with its own Python environment and an NVIDIA GPU with 8 GB or more. On Windows you also need Git Bash, because UniRig's scripts are bash. This bridge hasn't been run against a real UniRig install yet. On a Mac, or as a fallback, use `rig_template` or Rigify.

Next up: the agent layer (M3). It's a Claude skill with playbooks that chain these tools and check each stage. See the [architecture doc](https://claude.ai/artifact/JrknQR19bdru2ycPHy5GEe).

Requires Blender 4.2 LTS or newer. Tested headless on 4.2 and 5.0.

## Install

### 1. Blender addon (Windows and macOS)

1. Download `claude_blender-<version>.zip` from the latest CI run's artifacts, or build it with `python scripts/build_addon.py`.
2. In Blender: **Edit > Preferences > Get Extensions**, open the **v** menu at the top right, choose **Install from Disk...**, and pick the zip.
3. In the 3D viewport press **N**, open the **Claude** tab and click **Start Claude Bridge**. To start it every time, tick **Start bridge when Blender opens** in the addon's preferences.

The bridge listens on `127.0.0.1:9877` only. That's a different port from the older `blender-mcp` addon (9876), so both can be installed at once.

### 2. MCP server

You need [uv](https://docs.astral.sh/uv/getting-started/installation/).

- **Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **macOS:** `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Claude Desktop.** Edit the config file:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/rotembab/claude-blender-integration#subdirectory=server",
        "claude-blender-mcp"
      ]
    }
  }
}
```

**Claude Code:**

```
claude mcp add blender -- uvx --from "git+https://github.com/rotembab/claude-blender-integration#subdirectory=server" claude-blender-mcp
```

Optional environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CLAUDE_BLENDER_PORT` | `9877` | Must match the port in the addon's preferences |
| `CLAUDE_BLENDER_HOST` | `127.0.0.1` | |
| `CLAUDE_BLENDER_TOOLSETS` | `all` | Comma list such as `core,look`, to keep Claude's tool list short |

## How it works

```
Claude ──MCP──> claude-blender-mcp ──JSON lines over 127.0.0.1──> addon socket thread
                                                                     │ queue
                                                                     ▼
                                                     bpy timer on Blender's main thread
                                                     runs the command, returns the result
```

- **Main-thread queue.** bpy isn't thread safe. The socket thread only queues requests, and a timer runs them, so Blender's UI stays responsive.
- **Checkpoints.** `checkpoint` saves a copy of the file to a temp folder without touching your `.blend`, and `rollback` reopens it. After a rollback Blender has the checkpoint copy open, so use **File > Save As** to keep that state in your own file.
- **Undo.** In the UI, each `run_python` call pushes one undo step named `Claude: run_python`, so you can press Ctrl+Z on anything Claude did.
- **No silent re-runs.** If the connection drops while a command runs, the server reports it and doesn't resend, because the command may already have changed the scene.

## Development

```
# MCP server tests (no Blender needed)
pip install -e "server[dev]" && pytest server

# Addon tests, headless, using the bpy wheel (Python 3.11)
pip install bpy pytest -e server && pytest tests/blender
```

On Linux the render test needs Mesa EGL (`libegl1 libegl-mesa0`). Without a GPU or EGL it's skipped.

`addon/claude_blender/protocol.py` and `server/src/claude_blender_mcp/protocol.py` must stay identical, and a test enforces this.

## License

MIT
