"""MCP schema advertises the headless build inputs; EHP report formatting handles headless JSON."""

import json
import re
from pathlib import Path

from src.mcp_server import PoE2BuildOptimizerMCP as M

SRC = (Path(__file__).resolve().parents[1] / "src" / "mcp_server.py").read_text(encoding="utf-8")


def _tool_block(name):
    i = SRC.index(f'name="{name}"')
    return SRC[i : i + 9000].split("types.Tool(")[0]


def test_dps_and_ehp_schemas_expose_build_inputs():
    for tool in ("calculate_character_dps", "calculate_ehp"):
        block = _tool_block(tool)
        for prop in ("pob_file_path", "character_data", "char_model", "config", "fields", "level"):
            assert f'"{prop}"' in block, (tool, prop)


def test_calculate_ehp_dispatch_registered():
    assert re.search(r'name == "calculate_ehp"', SRC)


def test_ehp_report_formats_headless_json_as_markdown():
    out = M._ehp_text_for_report(
        json.dumps({"stats": {"Life": 1187, "FireMaximumHitTaken": 791, "TotalEHP": 872.1}})
    )
    assert "{" not in out and "**Total EHP:** 872" in out and "**Life:** 1,187" in out


def test_ehp_report_strips_python_header():
    out = M._ehp_text_for_report("[approximate: x]\n# Effective Health Pool Analysis\n\nbody")
    assert out.strip() == "body"
