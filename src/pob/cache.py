"""On-disk cache for headless PoB results.

Key = sha256(build XML) + PoB commit + sorted config + sorted fields (+ action/params).
A cache hit never starts LuaJIT: the engine is only launched lazily on the first miss.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import headless

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "pob"
BRIDGE_LUA = Path(__file__).resolve().parents[2] / "pob_headless" / "bridge.lua"


def bridge_hash() -> str:
    """Short sha256 of bridge.lua: any bridge change invalidates cached engine results."""
    try:
        return hashlib.sha256(BRIDGE_LUA.read_bytes()).hexdigest()[:12]
    except OSError:
        return "nobridge"


def cache_key(
    xml: str,
    action: str = "get_stats",
    config: Optional[dict] = None,
    fields: Optional[list] = None,
    params: Optional[dict] = None,
    commit: Optional[str] = None,
    level: Optional[int] = None,
) -> str:
    h = hashlib.sha256()
    h.update(hashlib.sha256(xml.encode("utf-8")).digest())
    meta = {
        "commit": commit or headless.pob_commit(),
        "action": action,
        "config": sorted((config or {}).items()),
        "fields": sorted(fields or []),
        "params": sorted((params or {}).items(), key=lambda kv: kv[0]),
        "bridge": bridge_hash(),
        "bridge_version": headless.bridge_version(),
        "level": level,
    }
    h.update(json.dumps(meta, sort_keys=True, default=str).encode())
    return h.hexdigest()


class CachedEngine:
    """One lazily-started engine session; loads each build once; caches every query on disk."""

    def __init__(self, refresh: bool = False, cache_dir: Path = CACHE_DIR):
        self.refresh, self.dir = refresh, Path(cache_dir)
        self._pob: Optional[headless.HeadlessPoB] = None
        self._loaded: Optional[Tuple[str, Optional[int]]] = None
        self.engine_launches = 0
        self._commit = headless.pob_commit()

    def _engine(self) -> headless.HeadlessPoB:
        if self._pob is None:
            self._pob = headless.HeadlessPoB(startup_timeout=300)
            self._pob.start()
            self.engine_launches += 1
        return self._pob

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def query(
        self,
        xml: str,
        action: str = "get_stats",
        config: Optional[dict] = None,
        fields: Optional[list] = None,
        level: Optional[int] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        key = cache_key(xml, action, config, fields, params, self._commit, level)
        f = self._path(key)
        if not self.refresh and f.exists():
            try:
                cached: Dict[str, Any] = json.loads(f.read_text())
                return cached
            except Exception:
                pass
        pob = self._engine()
        if self._loaded != (xml, level) or config:
            pob.load_build(xml)
            self._loaded = (xml, level) if not config else None
            if level:
                pob.call("set_level", level=level)
            if config:
                pob.call("set_config", config=config)
        kw = dict(params)
        if fields:
            kw["fields"] = fields
        res = pob.call(action, **kw)
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(res))
        os.replace(tmp, f)  # atomic: readers never see a half-written entry
        return res

    def stats(self, xml, config=None, fields=None, level=None):
        return self.query(xml, "get_stats", config, fields, level)["stats"]

    def skill_table(self, xml):
        return self.query(xml, "get_skill_table").get("skills", [])

    def sum_mod(self, xml, names, db="player", mod_type="BASE", cfg=None):
        """db: player | enemy | skill (main skill's skillModList + skill cfg). cfg="skill" evaluates
        conditional mods with the skill cfg. mod_type: BASE | INC | MORE (More = product)."""
        kw = {"names": list(names), "db": db, "mod_type": mod_type}
        if cfg:
            kw["cfg"] = cfg
        return self.query(xml, "sum_mod", **kw)["sums"]

    def close(self):
        if self._pob:
            self._pob.close()
            self._pob = None
            self._loaded = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
