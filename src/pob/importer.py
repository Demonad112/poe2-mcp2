"""
Path of Building import functionality
Complete XML parser for PoB builds
"""

import base64
import binascii
import logging
import re
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Standard base64 alphabet (post URL-safe normalisation) — used to pinpoint
# corrupt characters in share codes instead of surfacing a raw binascii error.
_B64_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


class PoBImporter:
    """Import builds from Path of Building format"""

    def _decode_pob_code(self, pob_code: str) -> str:
        """
        Decode a PoB share code (base64 + zlib) into the XML string.

        Tolerates whitespace/newlines and PoB's URL-safe base64 variant
        ('-'/'_' for '+'/'/') and missing padding. Failures raise ValueError
        with diagnostics (length, corrupt-char position, truncation hint)
        rather than raw binascii/zlib errors — agent callers reproduce long
        codes imperfectly and need to know WHERE it broke.
        """
        code = "".join(pob_code.split()).strip("?")
        if not code:
            raise ValueError("PoB code is empty after stripping whitespace")

        # PoB share codes use URL-safe base64; standard alphabet never
        # contains '-'/'_' so this translation is lossless either way.
        code = code.replace("-", "+").replace("_", "/")

        bad = [(i, c) for i, c in enumerate(code) if c not in _B64_CHARS]
        if bad:
            idx, char = bad[0]
            raise ValueError(
                f"PoB code contains {len(bad)} non-base64 character(s); first is "
                f"{char!r} at position {idx} of {len(code)}. The code was corrupted "
                f"in transit — pass the export via a file (pob_file_path) instead "
                f"of inline text."
            )

        code += "=" * (-len(code) % 4)

        try:
            decoded = base64.b64decode(code)
        except binascii.Error as e:
            raise ValueError(f"Base64 decode failed for PoB code ({len(code)} chars): {e}")

        try:
            decompressed = zlib.decompress(
                decoded, 47
            )  # 47: auto-detect zlib/gzip like PoB's Inflate
        except zlib.error as e:
            raise ValueError(
                f"PoB code base64-decoded cleanly ({len(decoded)} bytes) but zlib "
                f"decompression failed: {e}. The code is truncated or corrupted "
                f"mid-stream — a single wrong character breaks the whole stream. "
                f"Save the exact export to a file and import via pob_file_path, "
                f"or supply the uncompressed XML directly."
            )

        return decompressed.decode("utf-8")

    def _build_data_from_root(self, root: ET.Element) -> Dict[str, Any]:
        """Extract the build dictionary from a parsed PoB XML root."""
        return {
            "name": self._get_build_name(root),
            "level": self._get_build_level(root),
            "class": self._get_build_class(root),
            "ascendancy": self._get_ascendancy(root),
            "items": self._parse_items(root),
            "skills": self._parse_skills(root),
            "tree": self._parse_tree(root),
            "config": self._parse_config(root),
            "stats": self._extract_stats(root),
            **{k: v for k, v in self._extract_extra_stats(root).items()},
            "notes": self._get_notes(root),
            "version": root.get("version", "Unknown"),
        }

    def import_build_sync(self, pob_code: str) -> Dict[str, Any]:
        """
        Synchronously import a PoB build code. PoB import is entirely
        CPU-bound (base64 + zlib + XML parsing), so a sync entry point lets
        callers invoke it from sync code paths (e.g. the character data
        normaliser at fetch time, #132). Same return shape as ``import_build``.

        Args:
            pob_code: Base64-encoded PoB build (whitespace and URL-safe
                base64 tolerated)

        Returns:
            Build data dictionary
        """
        try:
            xml_str = self._decode_pob_code(pob_code)
            return self.import_xml_sync(xml_str)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"PoB import failed: {e}", exc_info=True)
            raise ValueError(f"Invalid PoB code: {str(e)}")

    def import_xml_sync(self, xml_str: str) -> Dict[str, Any]:
        """
        Import a build from raw (uncompressed) PoB XML.

        Args:
            xml_str: PoB build XML as a string (BOM tolerated)

        Returns:
            Build data dictionary
        """
        try:
            root = ET.fromstring(xml_str.lstrip("﻿").strip())
        except ET.ParseError as e:
            raise ValueError(f"Invalid PoB XML: {e}")

        try:
            build_data = self._build_data_from_root(root)
        except Exception as e:
            logger.error(f"PoB XML parse failed: {e}", exc_info=True)
            raise ValueError(f"Failed to parse PoB build XML: {str(e)}")

        logger.info(f"Successfully imported build: {build_data['name']}")
        return build_data

    async def import_build(self, pob_code: str) -> Dict[str, Any]:
        """
        Import a PoB build code (async wrapper around ``import_build_sync``).

        Args:
            pob_code: Base64-encoded PoB build

        Returns:
            Build data dictionary
        """
        return self.import_build_sync(pob_code)

    async def import_xml(self, xml_str: str) -> Dict[str, Any]:
        """Import raw PoB XML (async wrapper around ``import_xml_sync``)."""
        return self.import_xml_sync(xml_str)

    async def import_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Import a PoB build from a local file. The file may contain either
        the raw build XML (a saved .xml build) or a base64 share code
        (e.g. a .txt the export was pasted into) — auto-detected.

        Args:
            file_path: Path to the PoB build file

        Returns:
            Build data dictionary
        """
        path = Path(file_path).expanduser()
        try:
            # utf-8-sig strips a BOM if present (Notepad saves leave one)
            content = path.read_text(encoding="utf-8-sig")
        except OSError as e:
            raise ValueError(f"Cannot read PoB file {path}: {e}")

        try:
            if content.lstrip().startswith("<"):
                build_data = self.import_xml_sync(content)
            else:
                build_data = self.import_build_sync(content)
        except ValueError as e:
            raise ValueError(f"Failed to import build from {path}: {e}")

        logger.info(f"Successfully imported build from file: {file_path}")
        return build_data

    def _get_build_name(self, root: ET.Element) -> str:
        """Extract build name"""
        build_elem = root.find("./Build")
        if build_elem is not None:
            return build_elem.get("name", "Unnamed Build")
        return root.get("name", "Unnamed Build")

    def _get_build_level(self, root: ET.Element) -> int:
        """Extract character level"""
        build_elem = root.find("./Build")
        if build_elem is not None:
            return int(build_elem.get("level", 0))
        return 0

    def _get_build_class(self, root: ET.Element) -> str:
        """Extract character class"""
        build_elem = root.find("./Build")
        if build_elem is not None:
            return build_elem.get("className", "Unknown")
        return "Unknown"

    def _get_ascendancy(self, root: ET.Element) -> Optional[str]:
        """Extract ascendancy class"""
        build_elem = root.find("./Build")
        if build_elem is not None:
            return build_elem.get("ascendClassName")
        return None

    def _get_notes(self, root: ET.Element) -> str:
        """Extract build notes"""
        notes_elem = root.find("./Notes")
        if notes_elem is not None and notes_elem.text:
            return notes_elem.text
        return ""

    # ------------------------------------------------------------------
    # Active-set selection helpers (PoB stores several sets; one is active)
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_set(
        parent: Optional[ET.Element], tag: str, active: Optional[str], by_index: bool = False
    ):
        """Return the active child ``tag`` of ``parent`` (first one if unresolved).

        ``activeSpec`` is a 1-based index into the Spec list; the other
        ``active*Set`` attributes match the child's ``id``.
        """
        if parent is None:
            return None
        children = parent.findall(tag)
        if not children:
            return None
        if active:
            if by_index:
                try:
                    idx = int(active) - 1
                    if 0 <= idx < len(children):
                        return children[idx]
                except ValueError:
                    pass
            else:
                for child in children:
                    if child.get("id") == active:
                        return child
        return children[0]

    @staticmethod
    def _typed_input(elem: ET.Element) -> Any:
        """Config <Input>/<Placeholder> value with PoB's own typing."""
        if elem.get("boolean") is not None:
            return elem.get("boolean") == "true"
        raw_num = elem.get("number")
        if raw_num is not None:
            try:
                num = float(raw_num)
            except ValueError:
                return raw_num
            return int(num) if num.is_integer() else num
        return elem.get("string")

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def _parse_items(self, root: ET.Element) -> List[Dict[str, Any]]:
        """
        Parse items from PoB XML.

        <Item id=N> elements carry no slot; slot assignments live in the
        ACTIVE <ItemSet> (``activeItemSet``) as <Slot name itemId>. Unassigned
        items (spares/swaps) keep slot=None.
        """
        items: List[Dict[str, Any]] = []
        items_elem = root.find("./Items")

        if items_elem is None:
            return items

        item_set = self._pick_set(items_elem, "ItemSet", items_elem.get("activeItemSet"))
        if item_set is None:
            item_set = root.find(".//ItemSet")

        slot_by_item_id: Dict[str, str] = {}
        if item_set is not None:
            for slot_elem in item_set.findall("Slot"):
                item_id = slot_elem.get("itemId")
                slot_name = slot_elem.get("name")
                if item_id and item_id != "0" and slot_name:
                    slot_by_item_id[item_id] = slot_name

        for item_elem in items_elem.findall("Item"):
            item_id = item_elem.get("id")
            slot = self._get_item_slot(item_elem) or slot_by_item_id.get(item_id or "")
            item_data: Dict[str, Any] = {
                "id": item_id,
                "slot": slot,
                "weapon_set": self._weapon_set_for_slot(slot),
                "raw_text": item_elem.text or "",
                "enabled": item_elem.get("enabled", "1") == "1",
            }
            if item_data["raw_text"]:
                item_data.update(self._parse_item_text(item_data["raw_text"]))
            items.append(item_data)

        return items

    @staticmethod
    def _weapon_set_for_slot(slot: Optional[str]) -> Optional[int]:
        """Map a PoB slot name to its weapon set.

        PoE2 weapon swap: "Weapon 1"/"Weapon 2" are weapon set 1;
        "Weapon 1 Swap"/"Weapon 2 Swap" are weapon set 2. Only ONE set is
        active at a time, so set-specific weapon stats apply only while that
        set is equipped. Non-weapon slots return None.
        """
        if not slot:
            return None
        if slot.startswith("Weapon") and "Swap" in slot:
            return 2
        if slot.startswith("Weapon"):
            return 1
        return None

    def _get_item_slot(self, item_elem: ET.Element) -> Optional[str]:
        """Determine which slot an item is equipped in"""
        return item_elem.get("slot")

    _TAG_RE = re.compile(r"^(\{[^}]*\})+")
    _TAG_ITEMS_RE = re.compile(r"\{([^}]*)\}")

    @classmethod
    def _split_mod_line(cls, line: str) -> Dict[str, Any]:
        """Strip leading ``{range:…}{crafted}…`` tags from a mod line."""
        tags: List[str] = []
        m = cls._TAG_RE.match(line)
        if m:
            tags = cls._TAG_ITEMS_RE.findall(m.group(0))
            line = line[m.end() :].strip()
        return {"text": line, "tags": tags}

    def _parse_item_text(self, text: str) -> Dict[str, Any]:
        """
        Parse PoB item text (name follows the Rarity line, base type after).

        ``Implicits: N`` marks the next N lines as implicit mods; everything
        after them is explicit. Leading ``{…}`` tags (range/crafted/rune/…)
        are stripped from mod text and kept in ``mod_lines``.
        """
        lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
        if not lines:
            return {}

        name = "Unknown"
        base_type = ""
        rarity_idx = next(
            (i for i, ln in enumerate(lines) if ln.lower().startswith("rarity:")),
            None,
        )
        if rarity_idx is not None and rarity_idx + 1 < len(lines):
            name = lines[rarity_idx + 1]
            candidate = lines[rarity_idx + 2] if rarity_idx + 2 < len(lines) else ""
            if candidate and ":" not in candidate:
                base_type = candidate
        elif lines:
            name = lines[0]

        implicits: List[str] = []
        explicits: List[str] = []
        mod_lines: List[Dict[str, Any]] = []
        impl_idx: Optional[int] = None
        n_impl = 0
        for i, ln in enumerate(lines):
            m = re.match(r"Implicits:\s*(\d+)", ln)
            if m:
                impl_idx, n_impl = i, int(m.group(1))
                break
        if impl_idx is not None:
            for j, ln in enumerate(lines[impl_idx + 1 :]):
                parsed = self._split_mod_line(ln)
                parsed["implicit"] = j < n_impl
                mod_lines.append(parsed)
                (implicits if j < n_impl else explicits).append(parsed["text"])

        return {
            "name": name,
            "type_line": base_type,
            "base_type": base_type,
            "item_level": self._extract_item_level(text),
            "rarity": self._extract_rarity(text),
            "requirements": self._extract_requirements(text),
            "mods": self._extract_mods(text),
            "implicits": implicits,
            "explicits": explicits,
            "mod_lines": mod_lines,
            "full_text": text,
        }

    def _extract_item_level(self, text: str) -> int:
        """Extract item level from text"""
        match = re.search(r"Item Level: (\d+)", text)
        return int(match.group(1)) if match else 0

    def _extract_rarity(self, text: str) -> str:
        """Extract item rarity"""
        if "Rarity: UNIQUE" in text or "Rarity: Unique" in text:
            return "Unique"
        elif "Rarity: RARE" in text or "Rarity: Rare" in text:
            return "Rare"
        elif "Rarity: MAGIC" in text or "Rarity: Magic" in text:
            return "Magic"
        return "Normal"

    def _extract_requirements(self, text: str) -> Dict[str, int]:
        """Extract stat requirements"""
        reqs = {}

        str_match = re.search(r"Requires Level \d+.*?(\d+) Str", text)
        if str_match:
            reqs["strength"] = int(str_match.group(1))

        dex_match = re.search(r"(\d+) Dex", text)
        if dex_match:
            reqs["dexterity"] = int(dex_match.group(1))

        int_match = re.search(r"(\d+) Int", text)
        if int_match:
            reqs["intelligence"] = int(int_match.group(1))

        return reqs

    def _extract_mods(self, text: str) -> List[str]:
        """Heuristic mod-line list (tag-stripped). Prefer ``implicits``/``explicits``."""
        mods = []
        for line in text.split("\n"):
            line = self._split_mod_line(line.strip())["text"]
            if not line:
                continue
            # Mod lines carry a number plus '+' or '%' (parenthesised to fix the
            # old `a and b or c` precedence bug that admitted any '%' line)
            if any(ch.isdigit() for ch in line) and ("+" in line or "%" in line):
                mods.append(line)
        return mods

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def _parse_skills(self, root: ET.Element) -> List[Dict[str, Any]]:
        """Parse skill groups from the ACTIVE <SkillSet> (legacy: direct <Skill>)."""
        skills: List[Dict[str, Any]] = []
        skills_elem = root.find("./Skills")
        if skills_elem is None:
            return skills

        skill_set = self._pick_set(skills_elem, "SkillSet", skills_elem.get("activeSkillSet"))
        container = skill_set if skill_set is not None else skills_elem

        for skill in container.findall("Skill"):
            skill_data: Dict[str, Any] = {
                "label": skill.get("label", ""),
                "enabled": skill.get("enabled", "true") == "true",
                "slot": skill.get("slot"),
                "main_active_skill": skill.get("mainActiveSkill"),
                "gems": [],
            }
            for gem in skill.findall("Gem"):
                skill_data["gems"].append(
                    {
                        "name": gem.get("nameSpec", gem.get("gemId", "Unknown")),
                        "level": int(gem.get("level", 1)),
                        "quality": int(gem.get("quality", 0)),
                        "enabled": gem.get("enabled", "true") == "true",
                        "skill_id": gem.get("skillId"),
                        "gem_id": gem.get("gemId"),
                        "variant_id": gem.get("variantId"),
                        "count": int(gem.get("count", 1)),
                    }
                )
            skills.append(skill_data)

        return skills

    # ------------------------------------------------------------------
    # Tree
    # ------------------------------------------------------------------

    @staticmethod
    def _int_list(csv: Optional[str]) -> List[int]:
        return [int(n) for n in (csv or "").split(",") if n.strip().lstrip("-").isdigit()]

    def _parse_tree(self, root: ET.Element) -> Dict[str, Any]:
        """Parse the ACTIVE passive spec (``activeSpec`` is a 1-based index)."""
        tree_elem = root.find("./Tree")
        if tree_elem is None:
            return {}

        spec = self._pick_set(tree_elem, "Spec", tree_elem.get("activeSpec"), by_index=True)
        allocated: List[int] = []
        tree_data: Dict[str, Any] = {
            "allocated_nodes": allocated,
            "total_points": 0,
            "ascendancy_nodes": [],
            "mastery_effects": {},
        }
        if spec is None:
            return tree_data

        allocated.extend(self._int_list(spec.get("nodes")))
        tree_data["total_points"] = len(allocated)
        tree_data["tree_version"] = spec.get("treeVersion")
        tree_data["class_internal_id"] = spec.get("classInternalId")
        tree_data["ascendancy_internal_id"] = spec.get("ascendancyInternalId")
        tree_data["title"] = spec.get("title")

        # masteryEffects="{node,effect},{node,effect}" (PoB: {nodeId,effectId} pairs)
        for node, effect in re.findall(r"\{(\d+),(\d+)\}", spec.get("masteryEffects", "")):
            tree_data["mastery_effects"][int(node)] = int(effect)

        for n in (1, 2):
            ws = spec.find(f"WeaponSet{n}")
            if ws is not None:
                tree_data[f"weapon_set_{n}_nodes"] = self._int_list(ws.get("nodes"))

        tree_data["jewel_sockets"] = {
            int(s.get("nodeId")): s.get("itemId")
            for s in spec.findall("./Sockets/Socket")
            if (s.get("nodeId") or "").isdigit()
        }

        overrides = spec.find("Overrides")
        if overrides is not None:
            tree_data["attribute_overrides"] = {
                attr: self._int_list(ao.get(f"{attr}Nodes"))
                for ao in overrides.findall("AttributeOverride")
                for attr in ("str", "dex", "int")
            }

        url = spec.find("URL")
        if url is not None and url.text:
            tree_data["url"] = url.text.strip()

        return tree_data

    # ------------------------------------------------------------------
    # Config / stats
    # ------------------------------------------------------------------

    def _parse_config(self, root: ET.Element) -> Dict[str, Any]:
        """
        Parse the ACTIVE <ConfigSet> (legacy: <Input> directly under <Config>).

        Returns ``{"inputs", "placeholders", "custom_mods", "active_set"}`` with
        PoB-typed values (bool/int/float/str). Only non-default inputs are
        written by PoB, so absent options mean "default".
        """
        result: Dict[str, Any] = {
            "inputs": {},
            "placeholders": {},
            "custom_mods": [],
            "active_set": None,
        }
        config_elem = root.find("./Config")
        if config_elem is None:
            return result

        cfg_set = self._pick_set(config_elem, "ConfigSet", config_elem.get("activeConfigSet"))
        container = cfg_set if cfg_set is not None else config_elem
        if cfg_set is not None:
            result["active_set"] = cfg_set.get("id")

        for el in container.findall("Input"):
            if el.get("name"):
                result["inputs"][el.get("name")] = self._typed_input(el)
        for el in container.findall("Placeholder"):
            if el.get("name"):
                result["placeholders"][el.get("name")] = self._typed_input(el)
        for el in container.findall("CustomModifierBlock"):
            result["custom_mods"].append(
                {
                    "title": el.get("title", ""),
                    "enabled": el.get("enabled", "true") != "false",
                    "lines": [ln.strip() for ln in (el.text or "").split("\n") if ln.strip()],
                }
            )
        return result

    def _extract_stats(self, root: ET.Element) -> Dict[str, Any]:
        """
        PoB's own calculated numbers from <Build>: PlayerStat (output only —
        PoB ignores them on load). Values are floats where numeric.
        MinionStat / FullDPSSkill are exposed via ``_extract_extra_stats``.
        Falls back to a note when the export carried no calcs.
        """
        build = root.find("./Build")
        stats: Dict[str, Any] = {}
        if build is not None:
            for el in build.findall("PlayerStat"):
                stat = el.get("stat")
                if not stat:
                    continue
                try:
                    stats[stat] = float(el.get("value", ""))
                except ValueError:
                    stats[stat] = el.get("value")
        if not stats:
            return {
                "note": "No PlayerStat in export; stats must be calculated or fetched from the character API"
            }
        return stats

    def _extract_extra_stats(self, root: ET.Element) -> Dict[str, Any]:
        build = root.find("./Build")
        out: Dict[str, Any] = {"minion_stats": {}, "full_dps_skills": []}
        if build is None:
            return out
        for el in build.findall("MinionStat"):
            try:
                out["minion_stats"][el.get("stat")] = float(el.get("value", ""))
            except ValueError:
                out["minion_stats"][el.get("stat")] = el.get("value")
        for el in build.findall("FullDPSSkill"):
            out["full_dps_skills"].append(dict(el.attrib))
        return out
