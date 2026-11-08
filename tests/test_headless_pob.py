"""Headless PoB2 engine tests. Skipped unless scripts/setup_headless_pob.sh has been run."""
import pytest

from src.pob import headless

pytestmark = pytest.mark.skipif(
    not headless.find_environment()["ready"], reason="headless PoB2 engine not set up"
)


def test_native_build_levels_and_roundtrip():
    with headless.HeadlessPoB(startup_timeout=240) as p:
        p.call("new_build", level=1)
        low = p.call("get_stats", fields=["Life"])["stats"]["Life"]
        high = p.call("set_level", level=80, fields=["Life"])["stats"]["Life"]
        assert high > low * 5
        xml = p.call("export_xml")["xml"]
        assert xml.lstrip().startswith("<?xml") and "<PathOfBuilding2>" in xml
        p.call("new_build")
        p.load_build(xml)
        r = p.call("get_stats", fields=["Life", "Spirit"])
        assert r["level"] == 80 and r["stats"]["Life"] == high and r["stats"]["Spirit"] == 100


def test_rejects_poe1_xml_and_unknown_action():
    with headless.HeadlessPoB(startup_timeout=240) as p:
        with pytest.raises(headless.HeadlessPoBError, match="PathOfBuilding2"):
            p.call("load_xml", xml="<PathOfBuilding><Build level='90'/></PathOfBuilding>")
        with pytest.raises(headless.HeadlessPoBError, match="unknown action"):
            p.call("bogus")
