import asyncio
import importlib


def _tool_names(monkeypatch, toolsets):
    monkeypatch.setenv("CLAUDE_BLENDER_TOOLSETS", toolsets)
    import claude_blender_mcp.app as app

    app = importlib.reload(app)
    return {t.name for t in asyncio.run(app.mcp.list_tools())}


def test_all_tools_registered(monkeypatch):
    names = _tool_names(monkeypatch, "all")
    assert {"get_scene_state", "run_python", "checkpoint", "rollback", "list_checkpoints",
            "capture_views", "get_object_details", "mesh_report",
            "create_primitive", "mesh_edit", "boolean", "sculpt_prepare", "sculpt_stroke",
            "quad_remesh", "decimate", "uv_unwrap", "bake_maps",
            "create_material", "rig_template", "bind_mesh", "pose_test", "procedural_cycle",
            "export_model", "reimport_check", "auto_rig_unirig"} <= names


def test_toolset_filter(monkeypatch):
    names = _tool_names(monkeypatch, "core")
    assert "run_python" in names
    assert "capture_views" not in names


def test_every_tool_maps_to_an_addon_command(monkeypatch):
    """Each MCP tool must call a command the addon registers, with parameters it accepts."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    addon_cmds = {}
    for path in (root / "addon/claude_blender/handlers").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "command":
                        args = {a.arg for a in node.args.args + node.args.kwonlyargs}
                        addon_cmds[dec.args[0].value] = args
    server_dir = root / "server/src/claude_blender_mcp"
    for path in server_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("call", "_call") and node.args:
                cmd = node.args[0].value
                assert cmd in addon_cmds, f"{path.name}: unknown addon command {cmd!r}"
                kw = {k.arg for k in node.keywords} - {"timeout"}
                assert kw <= addon_cmds[cmd], f"{cmd}: addon does not accept {kw - addon_cmds[cmd]}"
