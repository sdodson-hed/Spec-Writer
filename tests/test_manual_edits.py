import json

from specgen import secfile
from specgen.answers import read_answers_json
from specgen.generate import generate, resolve_revisions, revert_revisions
from specgen.scan import scan_groups

SRC = (
    "<SEC><TXT>Provide scroll compressors for use A and B in the plant room."
    "<BRK/>Additional guidance follows. Provide [scroll][screw] compressors.</TXT></SEC>"
)


def _stream():
    _groups, text, offs = scan_groups(SRC)
    return text, offs


def _span(substr):
    text, _offs = _stream()
    start = text.index(substr)
    return start, start + len(substr)


def _write_master(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    return master


def test_valid_edit_applies_and_escapes(tmp_path):
    start, end = _span("use A and B")
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "ME@" + str(start): {
            "start": start,
            "end": end,
            "before": "use A and B",
            "after": "use A&B",
            "notes": "clarify",
        }
    }
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "use A&amp;B" in result
    changes = json.loads(
        out.with_suffix(".redline.json").read_text(encoding="utf-8")
    )["changes"]
    change = next(c for c in changes if c["kind"] == "manual-edit")
    assert change["action"] == "text edited"
    assert change["answer"] == "use A&B"
    assert change["after"] == "use A&amp;B"
    assert change["before"] == "use A and B"


def test_before_mismatch_is_skipped_and_unresolved(tmp_path):
    start, end = _span("use A and B")
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "ME@" + str(start): {
            "start": start,
            "end": end,
            "before": "use A and C",  # stale/wrong
            "after": "use X",
            "notes": "",
        }
    }
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "use A and B" in result  # untouched
    assert "use X" not in result
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "manual-edit" in unresolved_md
    assert "re-open the decision page" in unresolved_md


def test_markup_crossing_span_is_unresolved(tmp_path):
    text, _offs = _stream()
    start = text.index("compressors for")
    end = text.index("Additional") + len("Additional")
    before = text[start:end]
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "ME@" + str(start): {
            "start": start,
            "end": end,
            "before": before,
            "after": "x",
            "notes": "",
        }
    }
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "compressors for use A and B in the plant room." in result  # untouched
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "manual-edit" in unresolved_md
    assert "markup" in unresolved_md


def test_overlap_with_bracket_group_is_unresolved_group_still_applies(tmp_path):
    text, _offs = _stream()
    gstart = text.index("[scroll]")
    start, end = gstart + 1, gstart + 3  # inside the bracket group's span
    before = text[start:end]
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "BRK-0001": {"answer": "1", "notes": ""},
        "ME@" + str(start): {
            "start": start,
            "end": end,
            "before": before,
            "after": "zz",
            "notes": "",
        },
    }
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "scroll" in result and "screw" not in result  # group answer applied
    assert "zz" not in result
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "manual-edit" in unresolved_md
    assert "overlaps decision BRK-0001" in unresolved_md


def test_overlapping_edits_first_by_start_wins(tmp_path):
    text, _offs = _stream()
    s1 = text.index("use A and B")
    e1 = s1 + len("use A and B")
    s2 = text.index("A and B in the")  # overlaps [s1, e1)
    e2 = s2 + len("A and B in the")
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        # deliberately listed loser-first: acceptance order must be by
        # ascending start, not dict order
        "ME@" + str(s2): {
            "start": s2,
            "end": e2,
            "before": text[s2:e2],
            "after": "LOSER",
            "notes": "",
        },
        "ME@" + str(s1): {
            "start": s1,
            "end": e1,
            "before": text[s1:e1],
            "after": "WINNER",
            "notes": "",
        },
    }
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "WINNER" in result
    assert "LOSER" not in result
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert f"ME@{s2}" in unresolved_md
    assert f"overlaps another text edit (ME@{s1})" in unresolved_md


def test_revisions_wrap_edit_and_identities_hold(tmp_path):
    start, end = _span("use A and B")
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "BRK-0001": {"answer": "1", "notes": ""},
        "ME@" + str(start): {
            "start": start,
            "end": end,
            "before": "use A and B",
            "after": "use A&B",
            "notes": "",
        },
    }
    generate(master, {}, answers, out, revisions=True)
    clean = out.read_bytes().decode(secfile.ENCODING)
    rev = out.with_suffix(".revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert "<DEL>use A and B</DEL><ADD>use A&amp;B</ADD>" in rev
    assert resolve_revisions(rev) == clean
    assert revert_revisions(rev) == SRC


def test_read_answers_json_me_passthrough_and_malformed_skip(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "answers": {
                    "ME@5": {
                        "start": 5,
                        "end": 10,
                        "before": "hello",
                        "after": "hi",
                        "notes": "n",
                    },
                    "ME@999": {
                        "start": "x",  # non-int-able: malformed
                        "end": 10,
                        "before": "a",
                        "after": "b",
                    },
                    "ME@998": {"start": 1, "end": 2},  # missing before/after
                    "BRK-0001": {"answer": "1", "notes": ""},
                }
            }
        ),
        encoding="utf-8",
    )
    _profile, answers = read_answers_json(p)
    assert answers["ME@5"] == {
        "start": 5,
        "end": 10,
        "before": "hello",
        "after": "hi",
        "notes": "n",
    }
    assert "ME@999" not in answers
    assert "ME@998" not in answers
    assert answers["BRK-0001"]["answer"] == "1"
