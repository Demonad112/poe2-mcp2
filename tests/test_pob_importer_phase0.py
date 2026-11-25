"""Phase 0 decoder fixes: active sets, typed ConfigSet, PlayerStat, item tags, gzip."""

import gzip

from src.pob.importer import PoBImporter

XML = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
 <Build level="90" targetVersion="0_1">
  <PlayerStat stat="Life" value="4321"/>
  <PlayerStat stat="TotalDPS" value="12345.5"/>
  <MinionStat stat="Life" value="99"/>
  <FullDPSSkill stat="FullDPS" value="5" skillPart="1"/>
 </Build>
 <Tree activeSpec="2">
  <Spec nodes="1,2" classInternalId="Witch"/>
  <Spec nodes="10,11,12" treeVersion="0_5" classInternalId="Witch" ascendancyInternalId="Witch3"
        masteryEffects="{5,77}">
   <WeaponSet1 nodes="20"/>
   <Sockets><Socket nodeId="30" itemId="2"/></Sockets>
   <Overrides><AttributeOverride strNodes="10" dexNodes="11" intNodes="12"/></Overrides>
   <URL>https://example/tree</URL>
  </Spec>
 </Tree>
 <Skills activeSkillSet="2">
  <SkillSet id="1"><Skill slot="A"><Gem gemId="x" level="1"/></Skill></SkillSet>
  <SkillSet id="2"><Skill slot="B" mainActiveSkill="1"><Gem gemId="y" variantId="v" level="20" count="2"/></Skill></SkillSet>
 </Skills>
 <Items activeItemSet="2">
  <Item id="1">Rarity: RARE
Doom Coil
Gold Ring
Implicits: 1
{range:0.5}+10% to Fire Resistance
{crafted}+50 to maximum Life</Item>
  <ItemSet id="1"><Slot name="Ring 1" itemId="0"/></ItemSet>
  <ItemSet id="2"><Slot name="Ring 1" itemId="1"/></ItemSet>
 </Items>
 <Config activeConfigSet="2">
  <ConfigSet id="1"><Input name="enemyLevel" number="1"/></ConfigSet>
  <ConfigSet id="2">
   <Input name="enemyIsBoss" string="Uber"/>
   <Input name="enemyLevel" number="83"/>
   <Input name="conditionMoving" boolean="true"/>
   <Placeholder name="enemyLevel" number="82.5"/>
   <CustomModifierBlock title="t" enabled="true">+5 to Strength
10% increased Life</CustomModifierBlock>
  </ConfigSet>
 </Config>
</PathOfBuilding2>"""


def _build():
    return PoBImporter().import_xml_sync(XML)


def test_config_set_typed():
    cfg = _build()["config"]
    assert cfg["active_set"] == "2"
    assert cfg["inputs"] == {"enemyIsBoss": "Uber", "enemyLevel": 83, "conditionMoving": True}
    assert cfg["placeholders"]["enemyLevel"] == 82.5
    assert cfg["custom_mods"][0]["lines"] == ["+5 to Strength", "10% increased Life"]


def test_stats():
    b = _build()
    assert b["stats"] == {"Life": 4321.0, "TotalDPS": 12345.5}
    assert b["minion_stats"] == {"Life": 99.0}
    assert b["full_dps_skills"][0]["stat"] == "FullDPS"


def test_active_tree_spec():
    t = _build()["tree"]
    assert t["allocated_nodes"] == [10, 11, 12]
    assert t["ascendancy_internal_id"] == "Witch3"
    assert t["mastery_effects"] == {5: 77}
    assert t["weapon_set_1_nodes"] == [20]
    assert t["jewel_sockets"] == {30: "2"}
    assert t["attribute_overrides"]["dex"] == [11]


def test_active_skillset_no_duplication():
    skills = _build()["skills"]
    assert len(skills) == 1 and skills[0]["slot"] == "B"
    assert skills[0]["gems"][0]["gem_id"] == "y" and skills[0]["gems"][0]["count"] == 2


def test_active_itemset_and_mod_split():
    item = _build()["items"][0]
    assert item["slot"] == "Ring 1"
    assert item["implicits"] == ["+10% to Fire Resistance"]
    assert item["explicits"] == ["+50 to maximum Life"]
    assert item["mod_lines"][1]["tags"] == ["crafted"]


def test_gzip_and_question_mark_wrapping():
    import base64

    code = base64.urlsafe_b64encode(gzip.compress(XML.encode())).decode()
    assert PoBImporter().import_build_sync("?" + code + "?")["level"] == 90


def test_export_roundtrip_is_valid_pob2():
    import asyncio

    from src.pob.exporter import PoBExporter

    code = asyncio.run(
        PoBExporter().export_build(
            {
                "name": "t",
                "level": 90,
                "class": "Witch",
                "ascendancy": "Lich",
                "passives": {"hashes": [10, 11]},
            }
        )
    )
    assert "+" not in code and "/" not in code
    imp = PoBImporter()
    xml = imp._decode_pob_code(code)
    assert xml.startswith("<PathOfBuilding2")
    assert 'targetVersion="0_1"' in xml
    tree = imp.import_build_sync(code)["tree"]
    assert tree["allocated_nodes"] == [10, 11]
    assert tree["class_internal_id"] == "1"
    assert tree["ascendancy_internal_id"] == "Witch3"
