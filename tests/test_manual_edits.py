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


def test_inline_edit_export_shape_generates_with_revisions(tmp_path):
    # An answers payload shaped exactly like the page's Export: bracket
    # answers and ME@ records in one dict, including an insertion-only
    # record (start == end, before == "") from inline typing.
    from specgen.generate import generate, resolve_revisions, revert_revisions
    from specgen import secfile
    from specgen.manifest import build_manifest

    src = "<SEC><TXT>Provide [scroll][screw] compressors for the plant.</TXT></SEC>"
    p = tmp_path / "m.SEC"
    p.write_bytes(src.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    text = m["text"]
    gid = next(d["id"] for d in m["decisions"] if d["kind"] == "choice")

    # strike " for the plant" and insert " (Building 1401)" after "compressors"
    anchor = text.index(" for the plant")
    answers = {
        gid: {"answer": "1"},
        f"ME@{anchor}": {
            "start": anchor,
            "end": anchor + len(" for the plant"),
            "before": " for the plant",
            "after": " (Building 1401)",
            "notes": "sanity edit",
        },
    }
    out = tmp_path / "out.sec"
    summary = generate(p, {}, answers, out, revisions=True)
    got = out.read_bytes().decode(secfile.ENCODING)
    assert "scroll compressors (Building 1401)" in got
    assert "for the plant" not in got
    rev = (tmp_path / "out.revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert resolve_revisions(rev) == got
    assert revert_revisions(rev) == src
    assert summary["unresolved"] == 0

    # insertion-only record (start == end): typed text with nothing deleted
    ins_at = text.index(" compressors")
    answers2 = {
        gid: {"answer": "2"},
        f"ME@{ins_at}": {
            "start": ins_at, "end": ins_at, "before": "",
            "after": ",", "notes": "",
        },
    }
    out2 = tmp_path / "out2.sec"
    generate(p, {}, answers2, out2, revisions=True)
    got2 = out2.read_bytes().decode(secfile.ENCODING)
    assert "screw, compressors" in got2


def test_insertion_after_stripped_markup_does_not_duplicate(tmp_path):
    # The insertion point sits immediately after <BRK/> (stripped from the
    # stream), so stream chars start-1 (".") and start ("A") are NOT
    # source-contiguous. A zero-width insertion (start == end, before == "")
    # must splice a zero-width source range at offs[start]; the buggy
    # src_end = offs[start-1]+1 inverts the range and duplicates <BRK/>.
    text, _offs = _stream()
    start = text.index("Additional")
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "BRK-0001": {"answer": "1", "notes": ""},
        "ME@" + str(start): {
            "start": start,
            "end": start,
            "before": "",
            "after": "INSERTEDMARK ",
            "notes": "",
        },
    }
    generate(master, {}, answers, out, revisions=True)
    clean = out.read_bytes().decode(secfile.ENCODING)
    assert clean.count("INSERTEDMARK ") == 1
    assert clean.count("<BRK/>") == 1  # markup not duplicated
    assert "<BRK/>INSERTEDMARK Additional" in clean  # lands right before "Additional"
    rev = out.with_suffix(".revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert resolve_revisions(rev) == clean
    assert revert_revisions(rev) == SRC


def test_insertion_at_index_zero(tmp_path):
    # ME@0 insertion: start == end == 0, before == "". The buggy
    # src_end = offs[-1]+1 points at end-of-text -> catastrophic deletion.
    master = _write_master(tmp_path)
    out = tmp_path / "out.sec"
    answers = {
        "BRK-0001": {"answer": "1", "notes": ""},
        "ME@0": {
            "start": 0,
            "end": 0,
            "before": "",
            "after": "INSERTEDZERO ",
            "notes": "",
        },
    }
    generate(master, {}, answers, out, revisions=True)
    clean = out.read_bytes().decode(secfile.ENCODING)
    assert clean.count("INSERTEDZERO ") == 1
    assert "<TXT>INSERTEDZERO Provide" in clean  # lands at very start of the text
    assert "Provide scroll compressors" in clean  # nothing deleted
    rev = out.with_suffix(".revisions.sec").read_bytes().decode(secfile.ENCODING)
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
    _profile, answers, _fp = read_answers_json(p)
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
