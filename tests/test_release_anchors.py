"""Release acceptance (spec 2026-10-13, section 2): answers recorded against
the April 2026 03 30 00 (UMRL April 2026) applied to the July 2026 copy
(UMRL July 2026, WBDG). Both fixtures are byte copies, CRLF as shipped.

Measured 2026-10-13: 244 groups, none in notes; 236 carry over, 8 orphan.
The numbers are pinned on purpose. If they change, find out why before
touching this test."""

import re
from pathlib import Path

from specgen import secfile
from specgen.anchors import section_anchors
from specgen.answers import resolve_answer_keys
from specgen.generate import generate
from specgen.scan import scan_groups

FIX = Path(__file__).parent / "fixtures" / "ufgs"
APR, JUL = FIX / "03 30 00 (2026-04).SEC", FIX / "03 30 00 (2026-07).SEC"
WS = re.compile(r"\s+")
ANSWER_FOR = {"choice": "1", "blank": "X", "optional": "keep",
              "submittal-review": "keep"}


def _answer_everything(path):
    sec = secfile.parse(path)
    groups = scan_groups(sec.source)[0]
    anchors = section_anchors(sec)
    return {
        anchors[g.gid]: {
            "answer": ANSWER_FOR[g.kind],
            "id": g.gid,
            "options": [WS.sub(" ", o.text).strip() for o in g.options],
        }
        for g in groups
        if not g.in_note
    }


def test_fixtures_are_crlf_and_round_trip():
    for p in (APR, JUL):
        assert b"\r\n" in p.read_bytes()
        assert secfile.parse(p).roundtrips()


def test_april_answers_carry_to_july():
    ans = _answer_everything(APR)
    assert len(ans) == 244  # 03 30 00 has no bracket groups inside notes
    sec = secfile.parse(JUL)
    groups = scan_groups(sec.source)[0]
    by_gid, orphans, status = resolve_answer_keys(ans, groups, section_anchors(sec), None)
    assert (len(by_gid), len(orphans), status) == (236, 8, "anchors")
    by_id = {g.gid: g for g in groups}
    for gid, rec in by_gid.items():  # every carried answer lands on identical text
        assert [WS.sub(" ", o.text).strip() for o in by_id[gid].options] == rec["options"]
    # positional ids would have pointed 135 of these answers at the wrong text
    moved = sum(1 for gid, rec in by_gid.items() if rec["id"] != gid)
    assert moved > 100


def test_generate_on_july_with_april_answers(tmp_path):
    s = generate(JUL, {}, _answer_everything(APR), tmp_path / "o.sec")
    assert (s["answers_carried"], s["answers_orphaned"]) == (236, 8)
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    assert md.count("master changed: decision not found") == 8
