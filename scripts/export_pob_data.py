#!/usr/bin/env python3
"""Offline Lua -> JSON export of Path of Building 2 data tables (Phase 1 of the Lua-free calc plan).

Lua runs here, at *build time only*, through ``lupa``; the committed ``data/pob/*.json`` files are
what a Python/TS port consumes at calc time. Output is deterministic (sorted keys, no timestamps) so
``--check`` can fail CI/pre-commit when the committed JSON is stale relative to the pinned PoB2 commit.

Files written to ``data/pob/``:

* ``constants.json``      Data/Misc.lua tables + ``misc`` (the ``data.misc`` magic numbers from Modules/Data.lua)
* ``bosses.json``         Data/Bosses.lua, derived ``bossStats``, boss DPS/pen multipliers, Data/BossSkills.lua
* ``bases.json``          Data/Bases/*.lua (armour / weapon / flask / ... stat blocks verbatim)
* ``gems.json``           Data/Gems.lua keyed by ``gameId|variantId`` (``is_support`` flagged)
* ``enums.json``          Data/Global.lua ModFlag / KeywordFlag / SkillType
* ``modcache.json``       Data/ModCache.lua (mod text -> parsed mod list + unparsed remainder)
* ``config_options.json`` Modules/ConfigOptions.lua rows + a mod template per ``apply`` (see below)

Conventions
-----------
* Lua arrays (keys 1..n) become JSON arrays (so ``monsterArmourTable[L - 1]`` is level ``L``);
  other tables become objects with stringified keys. An empty Lua table is ``{}`` except for keys
  known to be lists (``EMPTY_LIST_KEYS``).
* +/-infinity (``math.huge``) is encoded as ``{"$inf": 1}`` / ``{"$inf": -1}``.
* Mods in ModCache / config templates are ``{name,type,value,flags,keywordFlags,source,tags:[...]}``.

Config option templates
-----------------------
Each row with an ``apply`` is executed against a *recording* ModList (``NewMod``/``ReplaceMod``/
``AddMod`` are captured, not applied). Numeric rows (count/countAllowZero/integer/float) are run with
several probe values; the recorded output is templated: a value equal to the input becomes ``"$val"``,
an affine function of it ``{"$affine": [k, c]}``. Two probes fix the line; the others verify it. Any
row whose output shape changes with the input, is not affine in it (e.g. ``min(val, 100)``,
``if val > 0``), throws, reads ``build``, parses mod text or leaks a Lua function gets
``"code": true`` plus ``"code_reasons"`` and a ``"sample"`` instead of a template. ``check`` rows run
once with ``true``; ``list`` rows run once per option (``"by_value"``). Rows without ``apply`` are
flagged ``"reads_input": true`` (calc code reads ``input[var]`` directly).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "pob"
SCHEMA_VERSION = 1
GENERATOR = "scripts/export_pob_data.py"

# Empty Lua tables under these keys are lists, not objects.
EMPTY_LIST_KEYS = frozenset({"implicitModTypes", "player", "enemy", "tags", "mods", "parsed_text"})

# Config row keys that are UI text / callbacks and not exported.
CONFIG_SKIP_KEYS = frozenset({"tooltip", "tooltipFunc", "apply"})
CONFIG_DEFAULT_KEYS = ("defaultState", "defaultIndex", "defaultPlaceholderState")
NUMERIC_ROW_TYPES = frozenset({"count", "countAllowZero", "integer", "float"})
# Probes: the first two fit the line, the rest verify it. 213 > 100 and -3 < 0 expose clamps.
NUMERIC_PROBES = (37, 213, 5, -3)

OUTPUT_FILES = (
    "constants.json",
    "bosses.json",
    "bases.json",
    "gems.json",
    "enums.json",
    "modcache.json",
    "config_options.json",
)


# --------------------------------------------------------------------------------------------
# Source discovery
# --------------------------------------------------------------------------------------------


def pob_pin() -> str:
    """Full commit sha pinned in src/pob/headless.py (read textually: no package import needed)."""
    text = (ROOT / "src" / "pob" / "headless.py").read_text(encoding="utf-8")
    m = re.search(r'^POB_COMMIT_PIN_FULL\s*=\s*"([0-9a-f]{40})"', text, re.M)
    if not m:
        raise RuntimeError("POB_COMMIT_PIN_FULL not found in src/pob/headless.py")
    return m.group(1)


def find_pob_src(explicit: Optional[str] = None) -> Path:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("POE2_POB_SRC"):
        candidates.append(Path(os.environ["POE2_POB_SRC"]))
    candidates.append(ROOT.parent / "PathOfBuilding-PoE2" / "src")
    home = Path(os.environ.get("POE2_POB_HOME", str(Path.home() / ".cache" / "poe2-mcp")))
    candidates.append(home / "PathOfBuilding-PoE2" / "src")
    for c in candidates:
        if (c / "Data" / "Misc.lua").is_file():
            return c
    raise FileNotFoundError(
        "PoB2 checkout not found (tried: %s). Run `bash scripts/setup_headless_pob.sh`."
        % ", ".join(str(c) for c in candidates)
    )


def checkout_commit(src: Path) -> Optional[str]:
    """HEAD sha of the checkout containing ``src`` (None if not a git checkout)."""
    head = src.parent / ".git" / "HEAD"
    if not head.is_file():
        return None
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(src.parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


# --------------------------------------------------------------------------------------------
# Lua runtime helpers
# --------------------------------------------------------------------------------------------


def new_runtime() -> Any:
    try:
        from lupa import lua54 as lupa_mod  # pinned runtime: 5.5 reserves `global`
    except ImportError:  # pragma: no cover - older lupa
        import lupa as lupa_mod
    return lupa_mod.LuaRuntime(unpack_returned_tuples=True)


class Converter:
    """Lua value -> plain Python. Records whether a function value was dropped."""

    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.saw_function = False

    def __call__(self, obj: Any, key_hint: str = "") -> Any:
        if obj is None or isinstance(obj, (bool, int, float, str)):
            if isinstance(obj, float):
                if math.isnan(obj):
                    raise ValueError("NaN in Lua data")
                if math.isinf(obj):  # JSON has no Infinity: {"$inf": +1|-1}
                    return {"$inf": 1 if obj > 0 else -1}
            return obj
        kind = self.rt.globals().type(obj)
        if kind == "table":
            items = list(obj.items())
            if not items:
                return [] if key_hint in EMPTY_LIST_KEYS else {}
            keys = [k for k, _ in items]
            if all(isinstance(k, int) and not isinstance(k, bool) for k in keys):
                n = len(keys)
                if set(keys) == set(range(1, n + 1)):
                    by_key = dict(items)
                    return [self(by_key[i], key_hint) for i in range(1, n + 1)]
            return {_key_str(k): self(v, _key_str(k)) for k, v in items}
        if kind == "function":
            self.saw_function = True
            return "<function>"
        raise TypeError("unsupported Lua type %r" % kind)


def _key_str(k: Any) -> str:
    if isinstance(k, float) and k.is_integer():
        return str(int(k))
    return str(k)


def read_lua(src: Path, rel: str) -> str:
    return (src / rel).read_text(encoding="utf-8")


def run_lua_file(rt: Any, src: Path, rel: str) -> Any:
    """Execute a data file (``return {...}``) in a fresh chunk and return its result."""
    chunk = rt.eval("function(code, name) return load(code, name) end")(
        read_lua(src, rel), "@" + rel
    )
    if chunk is None:
        raise RuntimeError("Lua syntax error in %s" % rel)
    return chunk()


# --------------------------------------------------------------------------------------------
# Exporters
# --------------------------------------------------------------------------------------------


def meta(source: str, pin: str) -> Dict[str, Any]:
    return {"generator": GENERATOR, "pob_commit": pin, "schema": SCHEMA_VERSION, "source": source}


def _extract_braced(text: str, start_pat: str) -> str:
    """Return ``start_pat`` through its matching closing brace (string/comment naive but sufficient)."""
    m = re.search(start_pat, text)
    if not m:
        raise RuntimeError("pattern not found: %s" % start_pat)
    i = text.index("{", m.end() - 1)
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start() : j + 1]
    raise RuntimeError("unbalanced braces after %s" % start_pat)


def load_misc(rt: Any, src: Path) -> Tuple[Any, Any]:
    """Run Data/Misc.lua, then the ``data.misc = {...}`` literal from Modules/Data.lua against it."""
    data = run_lua_file(rt, src, "Data/Misc.lua")
    literal = _extract_braced(read_lua(src, "Modules/Data.lua"), r"data\.misc\s*=\s*\{")
    loader = rt.eval("function(code, env) return load(code, '@Data.lua:data.misc', 't', env) end")
    chunk = loader(literal, rt.table_from({"data": data}))
    if chunk is None:
        raise RuntimeError("could not compile data.misc literal")
    chunk()
    return data, data["misc"]


def export_constants(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    data, misc = load_misc(rt, src)
    out: Dict[str, Any] = {"_meta": meta("Data/Misc.lua + Modules/Data.lua:data.misc", pin)}
    for k, v in data.items():
        if k == "misc":
            continue
        out[k] = conv(v, k)
    out["misc"] = conv(misc, "misc")
    return out


BOSS_MULT_KEYS = (
    "normalEnemyDPSMult",
    "stdBossDPSMult",
    "pinnacleBossDPSMult",
    "pinnacleBossPen",
    "uberBossDPSMult",
    "uberBossPen",
)


def compute_boss_stats(bosses: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """Mirror of Modules/Data.lua:871-876 (means of the armour/evasion multipliers, +100)."""
    count = uber = 0
    arm = eva = uarm = ueva = 0
    for b in bosses.values():
        if b.get("isUber"):
            uber += 1
            uarm += b["armourMult"]
            ueva += b["evasionMult"]
        count += 1
        arm += b["armourMult"]
        eva += b["evasionMult"]
    return {
        "PinnacleArmourMean": 100 + arm / count,
        "PinnacleEvasionMean": 100 + eva / count,
        "UberArmourMean": 100 + uarm / uber,
        "UberEvasionMean": 100 + ueva / uber,
    }


def lua_boss_stats(rt: Any, src: Path, bosses: Any) -> Dict[str, float]:
    """Run the *actual* bossStats block from Data.lua (cross-check for compute_boss_stats)."""
    text = read_lua(src, "Modules/Data.lua")
    m = re.search(
        r"\tlocal count, uberCount = 0, 0\n.*?data\.bossStats = \{.*?\n\t\}\n", text, re.S
    )
    if not m:
        raise RuntimeError("bossStats block not found in Modules/Data.lua")
    loader = rt.eval("function(code, env) return load(code, '@Data.lua:bossStats', 't', env) end")
    env = rt.table_from({"data": rt.table_from({"bosses": bosses}), "pairs": rt.globals().pairs})
    chunk = loader(m.group(0), env)
    if chunk is None:
        raise RuntimeError("could not compile bossStats block")
    chunk()
    stats = env["data"]["bossStats"]
    return {k: float(stats[k]) for k in stats.keys()}


def export_bosses(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    bosses_lua = run_lua_file(rt, src, "Data/Bosses.lua")
    bosses = conv(bosses_lua, "bosses")
    stats = compute_boss_stats(bosses)
    from_lua = lua_boss_stats(rt, src, bosses_lua)
    if stats != from_lua:
        raise RuntimeError("bossStats mismatch: python %r vs lua %r" % (stats, from_lua))
    _, misc = load_misc(rt, src)
    skills = conv(run_lua_file(rt, src, "Data/BossSkills.lua"), "bossSkillData")
    return {
        "_meta": meta("Data/Bosses.lua, Data/BossSkills.lua, Modules/Data.lua:871-876", pin),
        "bosses": bosses,
        "bossStats": stats,
        "bossMultipliers": {k: conv(misc[k]) for k in BOSS_MULT_KEYS},
        "bossSkills": skills["bossSkills"],
        "bossSkillsList": skills["bossSkillsList"],
    }


def export_bases(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    base_dir = src / "Data" / "Bases"
    bases: Dict[str, Any] = {}
    files: Dict[str, List[str]] = {}
    for path in sorted(base_dir.glob("*.lua")):
        store = rt.table()
        fn = run_lua_file(rt, src, "Data/Bases/%s" % path.name)
        fn(store)
        names: List[str] = []
        for name, entry in store.items():
            if name in bases:
                raise RuntimeError("duplicate base name %r (%s)" % (name, path.name))
            row = conv(entry, "base")
            row["source_file"] = path.stem
            bases[name] = row
            names.append(name)
        files[path.stem] = sorted(names)
    return {"_meta": meta("Data/Bases/*.lua", pin), "bases": bases, "files": files}


def export_gems(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    raw = run_lua_file(rt, src, "Data/Gems.lua")
    gems: Dict[str, Any] = {}
    for lua_key, entry in raw.items():
        g = conv(entry, "gem")
        key = "%s|%s" % (g["gameId"], g["variantId"])
        if key in gems:
            raise RuntimeError("duplicate gem key %r" % key)
        tags = g.get("tags") or {}
        g["lua_key"] = lua_key
        g["is_support"] = bool(g.get("gemType") == "Support" or tags.get("support"))
        gems[key] = g
    return {
        "_meta": meta("Data/Gems.lua", pin),
        "gems": gems,
        "supports": sorted(k for k, g in gems.items() if g["is_support"]),
    }


GLOBAL_PRELUDE = r"""
local env = {}
env.bit = {
  band = function(a, b) return a & b end,
  bor = function(a, b) return a | b end,
  bxor = function(a, b) return a ~ b end,
  bnot = function(a) return ~a end,
}
env.math = math
env.pairs = pairs
env.ipairs = ipairs
env.string = string
env.table = table
env.copyTable = function(t) local r = {} for k, v in pairs(t) do r[k] = v end return r end
return env
"""


def load_global_env(rt: Any, src: Path) -> Any:
    """Run Data/Global.lua into a fresh env table (ModFlag, KeywordFlag, SkillType, ...)."""
    env = rt.execute(GLOBAL_PRELUDE)
    loader = rt.eval("function(code, env) return load(code, '@Data/Global.lua', 't', env) end")
    chunk = loader(read_lua(src, "Data/Global.lua"), env)
    if chunk is None:
        raise RuntimeError("could not compile Data/Global.lua")
    chunk()
    return env


def export_enums(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    env = load_global_env(rt, src)
    out: Dict[str, Any] = {"_meta": meta("Data/Global.lua", pin)}
    for name in ("ModFlag", "KeywordFlag", "SkillType"):
        out[name] = conv(env[name], name)
    return out


def export_modcache(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    raw = run_lua_file(rt, src, "Data/ModCache.lua")
    entries: Dict[str, Any] = {}
    for text, pair in raw.items():
        mods = pair[1]
        rest = pair[2]
        entries[text] = {
            "mods": None if mods is None else [_norm_mod(conv(m, "mod")) for m in _seq(mods)],
            "rest": rest,
        }
    return {"_meta": meta("Data/ModCache.lua", pin), "entries": entries}


def _seq(tbl: Any) -> List[Any]:
    return [tbl[i] for i in range(1, len(list(tbl.keys())) + 1)]


def _norm_mod(mod: Any) -> Any:
    """Move a mod's array part (its tags, converted to {"1": ...}) under ``tags`` recursively."""
    if isinstance(mod, list):
        return [_norm_mod(x) for x in mod]
    if not isinstance(mod, dict):
        return mod
    out = {k: _norm_mod(v) for k, v in mod.items() if not k.isdigit()}
    tag_keys = sorted((k for k in mod if k.isdigit()), key=int)
    if tag_keys:
        out["tags"] = [_norm_mod(mod[k]) for k in tag_keys]
    elif "name" in mod and "type" in mod:
        out["tags"] = []
    return out


# --------------------------------------------------------------------------------------------
# Config options: recording ModList harness
# --------------------------------------------------------------------------------------------

CONFIG_HARNESS = r"""
local data, chunk_src, globals = ...
local saw_function = false
local build_reads = {}
local parsed_text = {}

local function create_mod(modName, modType, modVal, ...)
  -- same argument handling as Modules/ModTools.lua modLib.createMod
  local flags, keywordFlags, tagStart, source = 0, 0, 1, nil
  local n = select('#', ...)
  if n >= 1 and type(select(1, ...)) == "string" then source = select(1, ...); tagStart = 2 end
  if n >= 2 and type(select(2, ...)) == "number" then flags = select(2, ...); tagStart = 3 end
  if n >= 3 and type(select(3, ...)) == "number" then keywordFlags = select(3, ...); tagStart = 4 end
  return { name = modName, type = modType, value = modVal, flags = flags,
           keywordFlags = keywordFlags, source = source, select(tagStart, ...) }
end

local plain
local function plain_value(v)
  local t = type(v)
  if t == "function" then saw_function = true; return "<function>" end
  if t ~= "table" then return v end
  if v.name ~= nil and v.type ~= nil and v.flags ~= nil then return plain(v) end
  local r = {}
  for k, x in pairs(v) do r[k] = plain_value(x) end
  return r
end
plain = function(mod)
  local tags = {}
  for i = 1, #mod do tags[i] = plain_value(mod[i]) end
  return { name = mod.name, type = mod.type, value = plain_value(mod.value), flags = mod.flags,
           keywordFlags = mod.keywordFlags, source = mod.source, tags = tags }
end

local function recorder(sink)
  local m = {}
  function m:NewMod(...) sink[#sink + 1] = { op = "add", mod = plain(create_mod(...)) } end
  function m:ReplaceMod(...) sink[#sink + 1] = { op = "replace", mod = plain(create_mod(...)) } end
  function m:AddMod(mod) sink[#sink + 1] = { op = "add", mod = plain(mod) } end
  return setmetatable(m, { __index = function(_, k) error("unsupported ModList method " .. tostring(k)) end })
end

local function chain(path)
  return setmetatable({}, {
    __index = function(_, k)
      local p = path .. "." .. tostring(k)
      build_reads[#build_reads + 1] = p
      if p == "build.characterLevel" then return 100 end
      if p == "build.configTab.enemyLevel" then return nil end
      return chain(p)
    end,
    __call = function() return nil end,
  })
end

local env = setmetatable({
  data = data,
  m_min = math.min, m_max = math.max, m_floor = math.floor, s_format = string.format,
  t_insert = table.insert,
  round = function(val, dec)
    if dec then return math.floor(val * 10 ^ dec + 0.5) / 10 ^ dec end
    return math.floor(val + 0.5)
  end,
  StripEscapes = function(s) return (s:gsub("%^%d", ""):gsub("%^x%x%x%x%x%x%x", "")) end,
  modLib = {
    createMod = create_mod,
    setSource = function(mod, source) mod.source = source; return mod end,
    parseMod = function(line) parsed_text[#parsed_text + 1] = line; return nil, line end,
  },
}, { __index = function(_, k) local v = globals[k]; if v ~= nil then return v end return _G[k] end })

local fn = load(chunk_src, "@Modules/ConfigOptions.lua", "t", env)
local rows = fn()

local api = {}
api.rows = rows
function api.probe(row, val)
  saw_function = false
  build_reads = {}
  parsed_text = {}
  local player, enemy = {}, {}
  local ok, err = pcall(row.apply, val, recorder(player), recorder(enemy), chain("build"))
  return { ok = ok, err = (not ok) and tostring(err) or nil, player = player, enemy = enemy,
           build_reads = build_reads, parsed_text = parsed_text, saw_function = saw_function }
end
function api.row_info(row)
  -- scalar / list-ish row fields without callbacks (converted on the Python side)
  local r = {}
  for k, v in pairs(row) do
    if type(v) ~= "function" then r[k] = v end
  end
  r.has_apply = row.apply ~= nil
  return r
end
function api.strip(s)
  return (tostring(s):gsub("%^%d", ""):gsub("%^x%x%x%x%x%x%x", ""))
end
return api
"""


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _flatten(x: Any, path: Tuple[Any, ...] = ()) -> Dict[Tuple[Any, ...], Any]:
    if isinstance(x, dict):
        out: Dict[Tuple[Any, ...], Any] = {path + ("{}",): sorted(x.keys())}
        for k, v in x.items():
            out.update(_flatten(v, path + (k,)))
        return out
    if isinstance(x, list):
        out = {path + ("[]",): len(x)}
        for i, v in enumerate(x):
            out.update(_flatten(v, path + (i,)))
        return out
    return {path: x}


def _num(x: float) -> Any:
    return int(x) if float(x).is_integer() else x


def _set_path(root: Any, path: Tuple[Any, ...], value: Any) -> None:
    node = root
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value


def template_from_probes(probes: List[Tuple[float, Dict[str, Any]]]) -> Tuple[Optional[Any], str]:
    """Template the recorded mods across numeric probes.

    Returns (template, reason). template is None (with a reason) if the output is not an affine
    function of the input with a fixed shape.
    """
    flats = [(v, _flatten(out)) for v, out in probes]
    base_v, base = flats[0]
    for _, fl in flats[1:]:
        if fl.keys() != base.keys():
            return None, "output shape depends on val"
    template = json.loads(json.dumps(probes[0][1]))
    for path in sorted(base, key=repr):
        cells = [(v, fl[path]) for v, fl in flats]
        if not any(_is_num(c) for _, c in cells):
            if len({json.dumps(c) for _, c in cells}) != 1:
                return None, "non-numeric output depends on val"
            continue
        if not all(_is_num(c) for _, c in cells):
            return None, "output type depends on val"
        if len({c for _, c in cells}) == 1:
            continue  # constant
        (v1, y1), (v2, y2) = cells[0], cells[1]
        k = (y2 - y1) / (v2 - v1)
        c0 = y1 - k * v1
        for v, y in cells:
            if abs(y - (k * v + c0)) > 1e-9 * max(1.0, abs(y)):
                return None, "output is not affine in val"
        if abs(k - 1) < 1e-12 and abs(c0) < 1e-12:
            _set_path(template, path, "$val")
        else:
            _set_path(template, path, {"$affine": [_num(round(k, 12)), _num(round(c0, 12))]})
    return template, ""


def _probe_clean(rt: Any, conv: Converter, res: Any) -> Dict[str, Any]:
    conv.saw_function = False
    d = {
        "ok": bool(res["ok"]),
        "err": res["err"],
        "player": conv(res["player"], "player"),
        "enemy": conv(res["enemy"], "enemy"),
        "build_reads": sorted(set(conv(res["build_reads"], "parsed_text"))),
        "parsed_text": conv(res["parsed_text"], "parsed_text"),
        "saw_function": bool(res["saw_function"]),
    }
    return d


def _code_reasons(p: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    if not p["ok"]:
        reasons.append("apply error: %s" % p["err"])
    if p["saw_function"]:
        reasons.append("emits Lua function value")
    if p["build_reads"]:
        reasons.append("reads build state")
    if p["parsed_text"]:
        reasons.append("parses mod text")
    return reasons


def export_config(rt: Any, src: Path, pin: str, conv: Converter) -> Dict[str, Any]:
    data, _ = load_misc(rt, src)
    data["bosses"] = run_lua_file(rt, src, "Data/Bosses.lua")
    skills = run_lua_file(rt, src, "Data/BossSkills.lua")
    data["bossSkills"] = skills["bossSkills"]
    data["bossSkillsList"] = skills["bossSkillsList"]
    data["questRewards"] = run_lua_file(rt, src, "Data/QuestRewards.lua")
    data["enemyIsBossTooltip"] = ""
    data["bossStats"] = rt.table_from(compute_boss_stats(conv(data["bosses"], "bosses")))
    api = rt.eval("function(code, a, b, c) return load(code, '@harness')(a, b, c) end")(
        CONFIG_HARNESS, data, read_lua(src, "Modules/ConfigOptions.lua"), load_global_env(rt, src)
    )
    lua_rows = api["rows"]
    n_rows = len(list(lua_rows.keys()))

    rows: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    section = ""
    for i in range(1, n_rows + 1):
        lrow = lua_rows[i]
        info = conv(api.row_info(lrow), "row")
        if "section" in info and "var" not in info:
            section = api.strip(info["section"])
            sections.append({"name": section, "col": info.get("col"), "index": len(rows)})
            continue
        rtype = info.get("type")
        row: Dict[str, Any] = {
            "index": len(rows),
            "var": info.get("var"),
            "type": rtype,
            "label": api.strip(info["label"]) if "label" in info else None,
            "section": section,
            "col": info.get("col"),
        }
        defaults = {k: info[k] for k in CONFIG_DEFAULT_KEYS if k in info}
        if defaults:
            row["defaults"] = defaults
        if "list" in info:
            row["list"] = [
                {"val": it.get("val"), "label": api.strip(it["label"]) if "label" in it else None}
                for it in info["list"]
            ]
        vis = {k: v for k, v in info.items() if k.startswith("if") or k.startswith("hideIf")}
        if vis:
            row["visibility"] = vis
        other = {
            k: v
            for k, v in info.items()
            if k not in vis
            and k not in CONFIG_DEFAULT_KEYS
            and k not in CONFIG_SKIP_KEYS
            and k not in ("var", "type", "label", "list", "section", "col", "has_apply")
        }
        if other:
            row["other"] = other
        if not info.get("has_apply"):
            if row["var"] is not None:  # label-only rows have no input to read
                row["reads_input"] = True
            rows.append(row)
            continue
        row.update(_analyse_apply(rt, conv, api, lrow, rtype, info.get("list")))
        rows.append(row)

    by_var: Dict[str, List[int]] = {}
    for r in rows:
        if r["var"] is not None:
            by_var.setdefault(r["var"], []).append(r["index"])
    return {
        "_meta": meta("Modules/ConfigOptions.lua", pin),
        "probe_values": list(NUMERIC_PROBES),
        "rows": rows,
        "sections": sections,
        "by_var": {k: v for k, v in by_var.items()},
        "duplicate_vars": {k: v for k, v in by_var.items() if len(v) > 1},
    }


def _analyse_apply(
    rt: Any, conv: Converter, api: Any, lrow: Any, rtype: Any, list_vals: Any
) -> Dict[str, Any]:
    def run(val: Any) -> Dict[str, Any]:
        return _probe_clean(rt, conv, api.probe(lrow, val))

    def mods_of(p: Dict[str, Any]) -> Dict[str, Any]:
        return {"player": p["player"], "enemy": p["enemy"]}

    out: Dict[str, Any] = {"has_apply": True, "code": False}
    if rtype == "check":
        p = run(True)
        reasons = _code_reasons(p)
        out["mods"] = mods_of(p)
        if p["parsed_text"]:
            out["parsed_text"] = p["parsed_text"]
    elif rtype == "list" and list_vals:
        by_value: Dict[str, Any] = {}
        reasons = []
        for it in list_vals:
            p = run(it["val"])
            reasons += _code_reasons(p)
            entry = mods_of(p)
            if p["parsed_text"]:
                entry["parsed_text"] = p["parsed_text"]
            by_value[json.dumps(it["val"])] = entry
        out["by_value"] = by_value
    elif rtype in NUMERIC_ROW_TYPES:
        results = [(v, run(v)) for v in NUMERIC_PROBES]
        reasons = []
        for _, p in results:
            reasons += _code_reasons(p)
        tmpl: Optional[Any] = None
        if not reasons:
            tmpl, why = template_from_probes([(v, mods_of(p)) for v, p in results])
            if tmpl is None:
                reasons.append(why)
        if tmpl is not None:
            out["mods"] = tmpl
        else:
            out["sample"] = {"val": NUMERIC_PROBES[0], **mods_of(results[0][1])}
    else:
        p = run(NUMERIC_PROBES[0])
        reasons = _code_reasons(p) + ["unhandled row type %r" % (rtype,)]
        out["sample"] = {"val": NUMERIC_PROBES[0], **mods_of(p)}
    # de-duplicate while keeping order
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        out["code"] = True
        out["code_reasons"] = reasons
        if "mods" in out:
            out["sample"] = out.pop("mods")
    return out


# --------------------------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------------------------


def _compact(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def fmt(obj: Any, expand: int = 1, indent: int = 0) -> str:
    """Deterministic JSON; the top ``expand`` container levels get one entry per line (diff-friendly)."""
    if expand <= 0 or not isinstance(obj, (dict, list)) or not obj:
        return _compact(obj)
    pad = " " * (indent + 1)
    if isinstance(obj, dict):
        parts = [
            "%s%s: %s" % (pad, _compact(k), fmt(obj[k], expand - 1, indent + 1))
            for k in sorted(obj)
        ]
        return "{\n" + ",\n".join(parts) + "\n" + " " * indent + "}"
    parts = ["%s%s" % (pad, fmt(v, expand - 1, indent + 1)) for v in obj]
    return "[\n" + ",\n".join(parts) + "\n" + " " * indent + "]"


EXPAND = {
    "constants.json": 1,
    "bosses.json": 2,
    "bases.json": 2,
    "gems.json": 2,
    "enums.json": 2,
    "modcache.json": 2,
    "config_options.json": 2,
}


def build_all(src: Path) -> Dict[str, str]:
    pin = pob_pin()
    rt = new_runtime()
    conv = Converter(rt)
    exporters: Dict[str, Callable[[Any, Path, str, Converter], Dict[str, Any]]] = {
        "constants.json": export_constants,
        "bosses.json": export_bosses,
        "bases.json": export_bases,
        "gems.json": export_gems,
        "enums.json": export_enums,
        "modcache.json": export_modcache,
        "config_options.json": export_config,
    }
    out: Dict[str, str] = {}
    for name in OUTPUT_FILES:
        # fresh runtime per file: the data files mutate globals / share nothing
        rt = new_runtime()
        payload = exporters[name](rt, src, pin, Converter(rt))
        out[name] = fmt(payload, EXPAND[name]) + "\n"
    del conv
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--pob-src", help="PoB2 'src' dir (default: auto-detect)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output dir (default data/pob)")
    ap.add_argument("--check", action="store_true", help="fail if committed JSON is stale")
    ap.add_argument("--allow-commit-mismatch", action="store_true")
    args = ap.parse_args(argv)

    src = find_pob_src(args.pob_src)
    pin = pob_pin()
    head = checkout_commit(src)
    if head and head != pin and not args.allow_commit_mismatch:
        print(
            "PoB2 checkout is %s but the pin is %s; refusing (use --allow-commit-mismatch)"
            % (head[:7], pin[:7]),
            file=sys.stderr,
        )
        return 2

    outputs = build_all(src)
    out_dir = Path(args.out)
    if args.check:
        stale = []
        for name, text in outputs.items():
            path = out_dir / name
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        if stale:
            print("STALE: %s\nRegenerate: python scripts/export_pob_data.py" % ", ".join(stale))
            return 1
        print("OK: %d files up to date" % len(outputs))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
        print("wrote %s (%d KiB)" % (out_dir / name, len(text) // 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
