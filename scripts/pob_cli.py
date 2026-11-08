#!/usr/bin/env python3
"""
Headless CLI for the PoE2 MCP tools -- use when the MCP server is not attached
to the session (e.g. a fresh cloud chat).  Same code path as the MCP tools.

  python scripts/pob_cli.py analyze build.txt        # PoB share code or XML file ('-' = stdin)
  python scripts/pob_cli.py tool <tool_name> '<json args>'
  python scripts/pob_cli.py tools                    # list tool names

`analyze` prints the parsed build as JSON (class, level, gems, items, tree
node IDs, stats) which is the input every other tool needs.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
logging.disable(logging.CRITICAL)  # keep stdout clean; stderr noise is not useful here


async def _server():
    from src.mcp_server import PoE2BuildOptimizerMCP

    s = PoE2BuildOptimizerMCP()
    await s.initialize()
    return s


def _out(result):
    for c in result:
        print(getattr(c, "text", c))


async def amain(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[1]
    s = await _server()
    if cmd == "tools":
        # Tool names are registered with the MCP SDK list_tools handler.
        import re

        src = (ROOT / "src" / "mcp_server.py").read_text(encoding="utf-8")
        print("\n".join(sorted(set(re.findall(r'name="([a-z_0-9]+)",\s*description', src)))))
        return 0
    if cmd == "analyze":
        raw = sys.stdin.read() if len(argv) < 3 or argv[2] == "-" else None
        if raw is None:
            path = Path(argv[2])
            if not path.is_file():
                print(f"file not found: {path}", file=sys.stderr)
                return 2
            _out(await s.handle_call_tool("import_pob", {"pob_file_path": str(path)}))
        else:
            raw = raw.strip()
            key = "pob_xml" if raw.lstrip().startswith("<") else "pob_code"
            _out(await s.handle_call_tool("import_pob", {key: raw}))
        return 0
    if cmd == "tool":
        if len(argv) < 3:
            print("usage: tool <name> '<json args>'", file=sys.stderr)
            return 2
        args = json.loads(argv[3]) if len(argv) > 3 else {}
        _out(await s.handle_call_tool(argv[2], args))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    rc = asyncio.run(amain(sys.argv))
    sys.stdout.flush()
    os._exit(rc)  # background cache/db tasks can otherwise keep the process alive
