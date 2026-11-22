"""
Headless Path of Building 2 engine client.

Spawns ``luajit pob_headless/bridge.lua`` inside an (unmodified) PathOfBuilding-PoE2
checkout and exchanges newline-delimited JSON. This gives PoB-exact calculations in
environments with no PoB desktop app (cloud sessions, CI). Set up with
``scripts/setup_headless_pob.sh``.

Env: POE2_POB_HOME (cache dir), POE2_POB_SRC (PoB2 ``src`` dir), POE2_LUAJIT (binary).
"""

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
BRIDGE = ROOT / "pob_headless" / "bridge.lua"
HOME = Path(os.environ.get("POE2_POB_HOME", Path.home() / ".cache" / "poe2-mcp"))


def pob_src_dir() -> Path:
    """PoB2 ``src`` dir. Order: $POE2_POB_SRC, a sibling ``../PathOfBuilding-PoE2`` checkout
    (the user's fork, kept current), then the cache clone made by setup_headless_pob.sh."""
    env = os.environ.get("POE2_POB_SRC")
    if env:
        return Path(env)
    sibling = ROOT.parent / "PathOfBuilding-PoE2" / "src"
    if (sibling / "HeadlessWrapper.lua").is_file():
        return sibling
    return HOME / "PathOfBuilding-PoE2" / "src"


# ninja defensiveStats key -> (PoB output key, comparison kind). Kinds are defined in
# calculator/reconcile_poe_ninja.py::_make_row: int (rounded equal), floor, floor100
# (PoB fraction * 100 floored), pct1 (within 1%), pts (percentage points).
# Verified against PoB2 Modules/CalcDefence.lua / CalcPerform.lua; see docs/verify/FIELD-MAP.md.
DEFENCE_FIELD_SET: Dict[str, Any] = {
    "life": ("Life", "int"),
    "energyShield": ("EnergyShield", "int"),
    "mana": ("Mana", "int"),
    "spirit": ("Spirit", "int"),
    "strength": ("Str", "int"),
    "dexterity": ("Dex", "int"),
    "intelligence": ("Int", "int"),
    "movementSpeed": ("EffectiveMovementSpeedMod", "floor100"),
    "evasionRating": ("Evasion", "int"),
    "armour": ("Armour", "int"),
    "evadeChance": ("EvadeChance", "int"),
    "deflectChance": ("DeflectChance", "int"),
    "fireResistance": ("FireResist", "int"),
    "coldResistance": ("ColdResist", "int"),
    "lightningResistance": ("LightningResist", "int"),
    "chaosResistance": ("ChaosResist", "int"),
    "fireResistanceOverCap": ("FireResistOverCap", "int"),
    "coldResistanceOverCap": ("ColdResistOverCap", "int"),
    "lightningResistanceOverCap": ("LightningResistOverCap", "int"),
    "chaosResistanceOverCap": ("ChaosResistOverCap", "int"),
    "enduranceCharges": ("EnduranceCharges", "int"),
    "frenzyCharges": ("FrenzyCharges", "int"),
    "powerCharges": ("PowerCharges", "int"),
    "effectiveHealthPool": ("TotalEHP", "pct1"),
    "physicalMaximumHitTaken": ("PhysicalMaximumHitTaken", "pct1"),
    "fireMaximumHitTaken": ("FireMaximumHitTaken", "pct1"),
    "coldMaximumHitTaken": ("ColdMaximumHitTaken", "pct1"),
    "lightningMaximumHitTaken": ("LightningMaximumHitTaken", "pct1"),
    "chaosMaximumHitTaken": ("ChaosMaximumHitTaken", "pct1"),
}
DEFENCE_POB_FIELDS: List[str] = sorted({pk for pk, _ in DEFENCE_FIELD_SET.values()})
# PoB2 commit the engine is pinned to (full sha: scripts/setup_headless_pob.sh fetches exactly this; goldens
# in tests/fixtures/pob_golden are recorded against it). Bump together with a golden regeneration.
POB_COMMIT_PIN_FULL = "601768bd105869618c3d6581b883e5d7aeec91b2"
POB_COMMIT_PIN = POB_COMMIT_PIN_FULL[:7]


def bridge_version() -> str:
    """Bridge protocol version, read from the ``-- bridge-version: N`` header of pob_headless/bridge.lua.
    Bump it in bridge.lua when handler semantics change; it is reported by headless_pob_status and is
    part of every cached result's key (src/pob/cache.py)."""
    try:
        with open(BRIDGE, encoding="utf-8") as f:
            for _ in range(10):
                m = re.match(r"--\s*bridge-version:\s*(\S+)", f.readline())
                if m:
                    return m.group(1)
    except OSError:
        pass
    return "unknown"


# First-class what-if args -> PoB Configuration-tab inputs. kind: int | bool | charges.
WHATIF_ARGS: Dict[str, str] = {
    "enemy_level": "enemyLevel (int; PoB caps normal enemies/bosses at 85)",
    "enemy_shocked": "conditionEnemyShocked (bool)",
    "shock_effect": "conditionShockEffect (int %; implies enemy_shocked)",
    "fire_exposure": "conditionEnemyFireExposure (bool; -20% fire res)",
    "cold_exposure": "conditionEnemyColdExposure (bool; -20% cold res)",
    "lightning_exposure": "conditionEnemyLightningExposure (bool; -20% lightning res)",
    "power_charges": "usePowerCharges + overridePowerCharges (int; 0 turns them off)",
    "frenzy_charges": "useFrenzyCharges + overrideFrenzyCharges (int; 0 turns them off)",
    "endurance_charges": "useEnduranceCharges + overrideEnduranceCharges (int; 0 turns them off)",
}


def build_config(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Merge the documented what-if args into the raw ``config`` dict (explicit raw keys win).
    Returns None when nothing is set."""
    cfg: Dict[str, Any] = {}
    if args.get("enemy_level") is not None:
        cfg["enemyLevel"] = int(args["enemy_level"])
    if args.get("enemy_shocked") is not None:
        cfg["conditionEnemyShocked"] = bool(args["enemy_shocked"])
    if args.get("shock_effect") is not None:
        cfg["conditionEnemyShocked"] = True
        cfg["conditionShockEffect"] = int(args["shock_effect"])
    for arg, key in (("fire_exposure", "conditionEnemyFireExposure"), ("cold_exposure", "conditionEnemyColdExposure"),
                     ("lightning_exposure", "conditionEnemyLightningExposure")):
        if args.get(arg) is not None:
            cfg[key] = bool(args[arg])
    for arg, name in (("power_charges", "Power"), ("frenzy_charges", "Frenzy"), ("endurance_charges", "Endurance")):
        n = args.get(arg)
        if n is not None:
            cfg[f"use{name}Charges"] = int(n) > 0
            if int(n) > 0:
                cfg[f"override{name}Charges"] = int(n)
    cfg.update(args.get("config") or {})
    return cfg or None


def pob_commit() -> str:
    """Short git hash of the PathOfBuilding-PoE2 checkout in use (falls back to the pin)."""
    src = pob_src_dir()
    try:
        r = subprocess.run(["git", "-C", str(src), "rev-parse", "--short=7", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return POB_COMMIT_PIN


class HeadlessPoBError(RuntimeError):
    pass


def decode_pob_code(code: str) -> str:
    """PoB share code (url-safe base64 of zlib) -> XML. XML input is returned unchanged."""
    raw = "".join(code.split())
    if raw.lstrip().startswith("<"):
        return code
    raw = raw.replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    return zlib.decompress(base64.b64decode(raw)).decode("utf-8")


def luajit_supports_compound_assign(luajit: Optional[str]) -> bool:
    """PoB2 source uses ``x += 1``; mainline LuaJIT (e.g. Ubuntu apt) cannot parse it."""
    if not luajit:
        return False
    try:
        r = subprocess.run([luajit, "-e", "local c=1 c+=1"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def find_environment() -> Dict[str, Any]:
    src = pob_src_dir()
    pinned = HOME / "LuaJIT" / "src" / "luajit"  # built by scripts/setup_headless_pob.sh
    luajit = os.environ.get("POE2_LUAJIT") or (str(pinned) if pinned.is_file() else None) or shutil.which("luajit")
    utf8 = HOME / "lua_modules" / "lib" / "lua" / "5.1" / "lua-utf8.so"
    return {
        "luajit": luajit,
        "pob_src": str(src),
        "pob_src_present": (src / "HeadlessWrapper.lua").is_file(),
        "lua_utf8": str(utf8) if utf8.is_file() else None,
        "bridge": str(BRIDGE),
        "bridge_version": bridge_version(),
        "pob_commit": pob_commit(),
        "luajit_compound_assign": luajit_supports_compound_assign(luajit),
        "ready": bool(
            luajit
            and (src / "HeadlessWrapper.lua").is_file()
            and BRIDGE.is_file()
            and luajit_supports_compound_assign(luajit)
        ),
        "setup": "bash scripts/setup_headless_pob.sh",
    }


class HeadlessPoB:
    """One long-lived luajit process. Use as a context manager."""

    def __init__(self, startup_timeout: float = 120.0, call_timeout: float = 60.0):
        self.startup_timeout = startup_timeout
        self.call_timeout = call_timeout
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        env = find_environment()
        if not env["ready"]:
            raise HeadlessPoBError(
                f"headless PoB not set up (luajit={env['luajit']}, pob_src={env['pob_src']}). "
                f"Run: {env['setup']}"
            )
        proc_env = dict(os.environ, POB_API_STDIO="1")
        so_dir = HOME / "lua_modules" / "lib" / "lua" / "5.1"
        proc_env["LUA_CPATH"] = f"{so_dir}/?.so;;"
        self.proc = subprocess.Popen(
            [env["luajit"], str(BRIDGE)],
            cwd=env["pob_src"],
            env=proc_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        ready = self._readline(self.startup_timeout)
        if not ready or not ready.get("ready"):
            self.close()
            raise HeadlessPoBError(f"bridge did not become ready: {ready}")

    def _readline(self, timeout: float) -> Optional[Dict[str, Any]]:
        box: List[Optional[str]] = []
        t = threading.Thread(target=lambda: box.append(self.proc.stdout.readline()), daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or not box or not box[0]:
            return None
        return json.loads(box[0])

    def call(self, action: str, **params: Any) -> Dict[str, Any]:
        if self.proc is None or self.proc.poll() is not None:
            raise HeadlessPoBError("bridge process is not running")
        with self._lock:
            self.proc.stdin.write(json.dumps({"action": action, "params": params}) + "\n")
            self.proc.stdin.flush()
            reply = self._readline(self.call_timeout)
        if reply is None:
            self.close()
            raise HeadlessPoBError(f"{action}: timed out / bridge died")
        if not reply.get("ok"):
            raise HeadlessPoBError(f"{action}: {reply.get('error')}")
        return reply

    def load_build(self, code_or_xml: str) -> Dict[str, Any]:
        return self.call("load_xml", xml=decode_pob_code(code_or_xml))

    def get_skill_table(self) -> List[Dict[str, Any]]:
        """Per enabled socket group: offence keys + damage-type split (bridge ``get_skill_table``)."""
        return self.call("get_skill_table").get("skills", [])

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write('{"action":"quit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.proc = None

    def __enter__(self) -> "HeadlessPoB":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def calc(code_or_xml: str, config: Optional[Dict[str, Any]] = None,
         fields: Optional[List[str]] = None, level: Optional[int] = None) -> Dict[str, Any]:
    """One-shot: load a build, optionally set level/config overrides, return PoB stats."""
    with HeadlessPoB() as pob:
        pob.load_build(code_or_xml)
        if level:
            pob.call("set_level", level=level)
        if config:
            return pob.call("set_config", config=config, fields=fields)
        return pob.call("get_stats", fields=fields)
