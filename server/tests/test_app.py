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
            "capture_views", "get_object_details", "mesh_report"} <= names


def test_toolset_filter(monkeypatch):
    names = _tool_names(monkeypatch, "core")
    assert "run_python" in names
    assert "capture_views" not in names
