#!/usr/bin/env python3
"""Generate the synthetic audit fixtures in tests/fixtures/builds/*.json (no user data).

Each fixture is a hand-assembled PoB2 build: the engine's blank new_build skeleton (Ranger, L80, empty tree)
plus a skill group and (optionally) a few custom-mod items. Needs a ready headless engine.
Usage: python scripts/make_synthetic_fixtures.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pob import headless  # noqa: E402

OUT = ROOT / "tests/fixtures/builds"

FIXTURES = {
    "synthetic_spell_fireball": {
        "level": 90,
        "gems": [("FireballPlayer", 20)],
        "items": [("Weapon 1", "Rarity: Rare\nTest Staff\nAshen Staff\n80% increased Spell Damage\n"
                               "25% increased Cast Speed\n+30% to Critical Damage Bonus\nPenetrate 15% Fire Resistance")],
    },
    "synthetic_attack_lightning_arrow": {
        "level": 90,
        "gems": [("LightningArrowPlayer", 20)],
        "items": [("Weapon 1", "Rarity: Rare\nTest Bow\nHeavy Bow\nAdds 20 to 40 Physical Damage\n"
                               "40% increased Attack Speed\n+25% to Critical Damage Bonus")],
    },
    "synthetic_dot_contagion": {
        "level": 90,
        "gems": [("ContagionPlayer", 20)],
        "items": [("Weapon 1", "Rarity: Rare\nTest Wand\nWithered Wand\n70% increased Chaos Damage\n"
                               "40% increased Skill Effect Duration")],
    },
    "synthetic_es_ci": {
        "level": 90,
        "gems": [("SparkPlayer", 20)],
        "items": [("Body Armour", "Rarity: Rare\nTest Robe\nSilk Robe\n+400 to maximum Energy Shield\n"
                                  "+40% to Fire Resistance\n+40% to Cold Resistance\n+30% to Lightning Resistance"),
                  ("Amulet", "Rarity: Rare\nTest Amulet\nJade Amulet\n+60 to maximum Energy Shield\n"
                             "Maximum Life becomes 1\nImmune to Chaos Damage")],
    },
}

SLOT_ORDER = ["Weapon 1", "Body Armour", "Amulet"]


def build_xml(skeleton: str, spec: dict) -> str:
    x = re.sub(r"\s*<PlayerStat[^>]*/>", "", skeleton)
    x = re.sub(r'level="\d+"', f'level="{spec["level"]}"', x, count=1)
    skills = "".join(
        f'<Skill enabled="true" mainActiveSkill="1" label="" slot="">'
        f'<Gem enabled="true" count="1" level="{lvl}" quality="0" skillId="{sid}" qualityId="Default"/></Skill>'
        for sid, lvl in spec["gems"])
    x = x.replace('<SkillSet id="1"/>', f'<SkillSet id="1">{skills}</SkillSet>')
    items, slots = [], []
    for i, (slot, text) in enumerate(spec["items"], 1):
        items.append(f'<Item id="{i}">\n{text}\n</Item>')
        slots.append((slot, i))
    x = re.sub(r"<Items [^>]*>", lambda m: m.group(0) + "".join(items), x, count=1)
    for slot, i in slots:
        x = x.replace(f'<Slot itemId="0" itemPbURL="" name="{slot}"/>', f'<Slot itemId="{i}" itemPbURL="" name="{slot}"/>', 1)
    return x


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with headless.HeadlessPoB() as pob:
        pob.call("new_build", level=80)
        skeleton = pob.call("export_xml")["xml"]
    for name, spec in FIXTURES.items():
        xml = build_xml(skeleton, spec)
        with headless.HeadlessPoB() as pob:
            pob.load_build(xml)
            st = pob.call("get_stats", fields=["TotalDPS", "CombinedDPS", "Life", "EnergyShield", "Speed"])["stats"]
        print(name, {k: round(v, 1) if isinstance(v, (int, float)) else v for k, v in st.items()})
        (OUT / f"{name}.json").write_text(json.dumps({"name": name, "synthetic": True, "pob_xml": xml}, indent=1) + "\n")


if __name__ == "__main__":
    main()
