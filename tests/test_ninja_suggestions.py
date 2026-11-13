import json
from pathlib import Path

from src.calculator.ninja_suggestions import format_suggestions_markdown, suggest_from_charmodel

FIX = Path(__file__).parent / "fixtures" / "ninja_yykiuy_charmodel.json"


def _m():
    d = json.loads(FIX.read_text(encoding="utf-8"))
    return d.get("charModel", d)


def test_yykiuy_top_suggestions():
    r = suggest_from_charmodel(_m())
    f = [s["finding"] for s in r["suggestions"]]
    assert r["offline"] and r["suggestions"][0]["severity"] == 3
    assert any("physical is the weak point: 4,399" in x for x in f)
    assert any("chaos resistance 6% under cap" in x for x in f)
    assert any("overcap" in x for x in f)


def test_split_uses_ninja_order():
    # regression for the app bug: ninja order is [phys, lightning, cold, fire, chaos]
    r = suggest_from_charmodel(_m())
    main = [s for s in r["suggestions"] if s["area"] == "damage"][0]
    assert "Falling Thunder" in main["finding"] and "lightning 47%" in main["evidence"] and "fire 8%" in main["evidence"]


def test_markdown_and_empty():
    assert "| # |" in format_suggestions_markdown(suggest_from_charmodel(_m()))
    assert suggest_from_charmodel({})["suggestions"] == []
