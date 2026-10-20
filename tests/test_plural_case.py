"""Plural markers written with a capital S ("Chiller[S]", 23 64 10 and 4 more
masters in the UMRL July 2026 release) must not produce "ChillerS"."""

import json

from specgen import secfile
from specgen.answers import PLURAL_KEY
from specgen.generate import generate

SRC = (
    "<SEC><PRT><TTL>PART 2 PRODUCTS</TTL><SPT><TTL>WATER CHILLER[S]</TTL>"
    "<TXT>Provide Split-System Water Chiller[S], Pump[s] and Box[ES].</TXT>"
    "</SPT></PRT></SEC>"
)


def _gen(tmp_path, action):
    p = tmp_path / "m.SEC"
    p.write_bytes(SRC.encode(secfile.ENCODING))
    generate(p, {PLURAL_KEY: action}, {}, tmp_path / "o.sec", revisions=True)
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    rev = (tmp_path / "o.revisions.sec").read_bytes().decode(secfile.ENCODING)
    changes = json.loads((tmp_path / "o.redline.json").read_text(encoding="utf-8"))["changes"]
    return out, rev, changes


def test_capital_marker_after_lowercase_word_is_lowercased(tmp_path):
    out, rev, changes = _gen(tmp_path, "keep")
    assert "Split-System Water Chillers," in out
    assert "Boxes." in out and "Pumps" in out
    # an all-caps word keeps its capital plural
    assert "<TTL>WATER CHILLERS</TTL>" in out
    # the case change is a visible edit in the revisions, which still resolve
    # and revert exactly (generate verifies both)
    assert "Chiller<DEL>[S]</DEL><ADD>s</ADD>" in rev
    assert "CHILLER<DEL>[</DEL>S<DEL>]</DEL>" in rev
    fixed = [c for c in changes if "lowercased" in c["action"]]
    assert len(fixed) == 2  # Chiller[S] and Box[ES]


def test_singular_is_unchanged(tmp_path):
    out, _, _ = _gen(tmp_path, "remove")
    assert "Split-System Water Chiller," in out and "<TTL>WATER CHILLER</TTL>" in out
    assert "Box." in out and "Pump " in out


def test_lowercase_marker_unchanged(tmp_path):
    out, rev, _ = _gen(tmp_path, "keep")
    assert "Pump<DEL>[</DEL>s<DEL>]</DEL>" in rev
