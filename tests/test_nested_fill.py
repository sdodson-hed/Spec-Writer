"""E2E: a composed nested-fill answer from the decision page flows through
generate unchanged.

The page stores the final text (blanks replaced) as a literal answer plus
`option`/`fills` re-edit metadata. generate reads only answer/notes/office,
so the extra keys must pass through without error and the composed text must
splice as custom text — no brackets left, no OPEN@ follow-up.
"""

import json

from specgen import secfile
from specgen.generate import generate, resolve_revisions, revert_revisions

SRC = "<SEC><TXT>Provide [scroll][water at [_____] degrees] units.</TXT></SEC>"

ANSWERS = {
    "BRK-0001": {
        "answer": "water at 40 degrees",
        "option": 2,
        "fills": ["40"],
        "notes": "",
    }
}


def _gen(tmp_path, revisions=False):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    summary = generate(master, {}, ANSWERS, out, revisions=revisions)
    result = out.read_bytes().decode(secfile.ENCODING)
    return summary, out, result


def test_composed_fill_answer_splices_final_text(tmp_path):
    summary, out, result = _gen(tmp_path)
    assert "water at 40 degrees" in result
    assert "[" not in result and "]" not in result
    assert summary["bracket_chars_remaining"] == 0
    changes = json.loads(
        out.with_suffix(".redline.json").read_text(encoding="utf-8")
    )["changes"]
    change = next(c for c in changes if c["id"] == "BRK-0001")
    assert change["action"] == "custom text"
    assert change["after"] == "water at 40 degrees"
    unresolved = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "OPEN@" not in unresolved
    assert summary["unresolved"] == 0


def test_composed_fill_answer_round_trips_revisions(tmp_path):
    _summary, out, clean = _gen(tmp_path, revisions=True)
    rev = out.with_name("out.revisions.sec").read_bytes().decode(
        secfile.ENCODING
    )
    assert "<DEL>" in rev and "<ADD>" in rev
    assert resolve_revisions(rev) == clean
    assert revert_revisions(rev) == SRC
