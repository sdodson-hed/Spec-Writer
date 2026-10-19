"""Anchor-keyed answer loading (spec 2026-10-13, section 2): anchors that
resolve apply; anchors that don't are reported as orphans and applied to
nothing; legacy BRK keys still need a matching fingerprint."""

import json

import pytest

from specgen import secfile
from specgen.anchors import section_anchors
from specgen.answers import resolve_answer_keys
from specgen.cli import main
from specgen.generate import GenerateError, generate
from specgen.scan import legacy_scan_fingerprint, scan_fingerprint, scan_groups

APR = ("<SEC><PRT><TTL>PART 2</TTL><SPT><TTL>CHILLERS</TTL>"
       "<TXT>Provide [scroll][screw] compressors.</TXT>"
       "<TXT>Refrigerant [R-410A][R-454B].</TXT></SPT></PRT></SEC>")
# July: a new group before both, and the refrigerant options changed
JUL = APR.replace("<TXT>Provide", "<TXT>New [x][y].</TXT><TXT>Provide").replace(
    "[R-410A][R-454B]", "[R-454B][R-32]")


def _ctx(src):
    sec = secfile.parse_source(src)
    return scan_groups(src)[0], section_anchors(sec)


def _apr_answers():
    _, a = _ctx(APR)
    return {
        a["BRK-0001"]: {"answer": "1", "id": "BRK-0001", "options": ["scroll", "screw"]},
        a["BRK-0002"]: {"answer": "2", "id": "BRK-0002", "options": ["R-410A", "R-454B"]},
    }


def test_anchor_answers_follow_the_decision_across_releases():
    groups, anchors = _ctx(JUL)
    by_gid, orphans, status = resolve_answer_keys(_apr_answers(), groups, anchors, None)
    assert list(by_gid) == ["BRK-0002"] and by_gid["BRK-0002"]["answer"] == "1"
    [o] = orphans
    assert o["kind"] == "orphan" and o["options"] == ["R-410A", "R-454B"]
    assert "master changed: decision not found (was BRK-0002)" in o["note"]
    assert status == "anchors"


def _write(tmp_path, src, name="jul.SEC"):
    m = tmp_path / name
    m.write_bytes(src.encode(secfile.ENCODING))
    return m


def test_orphan_is_never_applied_and_never_defaulted(tmp_path):
    s = generate(_write(tmp_path, JUL), {}, _apr_answers(), tmp_path / "o.sec")
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    assert "Provide scroll compressors." in out
    assert "[R-454B][R-32]" in out  # still bracketed
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    assert "master changed: decision not found" in md and "R-410A | R-454B" in md
    assert (s["answers_carried"], s["answers_orphaned"]) == (1, 1)
    assert s["answers_fingerprint"] == "anchors"


def test_strict_refuses_orphans(tmp_path):
    with pytest.raises(GenerateError, match="1 answer"):
        generate(_write(tmp_path, JUL), {}, _apr_answers(), tmp_path / "o.sec",
                 strict=True)


def test_strict_passes_when_everything_resolves(tmp_path):
    s = generate(_write(tmp_path, APR, "apr.SEC"), {}, _apr_answers(),
                 tmp_path / "o.sec", strict=True)
    assert (s["answers_carried"], s["answers_orphaned"]) == (2, 0)


def test_legacy_brk_keys_need_matching_fingerprint():
    groups, anchors = _ctx(JUL)
    stale = scan_fingerprint(scan_groups(APR)[0])
    with pytest.raises(GenerateError, match="different scan"):
        resolve_answer_keys({"BRK-0001": {"answer": "1"}}, groups, anchors, stale)
    forced, _, st = resolve_answer_keys({"BRK-0001": {"answer": "1"}}, groups,
                                        anchors, stale, force_stale=True)
    assert forced == {"BRK-0001": {"answer": "1"}} and st == "MISMATCH (forced)"
    for fp, want in [(scan_fingerprint(groups), "match"),
                     (legacy_scan_fingerprint(groups), "match (legacy)"),
                     (None, "unstamped")]:
        by_gid, _, status = resolve_answer_keys({"BRK-0001": {"answer": "1"}},
                                                groups, anchors, fp)
        assert by_gid == {"BRK-0001": {"answer": "1"}} and status == want


def test_strict_refuses_stale_fingerprint_even_with_anchors():
    groups, anchors = _ctx(JUL)
    stale = scan_fingerprint(scan_groups(APR)[0])
    with pytest.raises(GenerateError, match="different scan"):
        resolve_answer_keys({}, groups, anchors, stale, strict=True)


def test_same_decision_answered_twice_is_an_error():
    groups, anchors = _ctx(APR)
    fp = scan_fingerprint(groups)
    with pytest.raises(GenerateError, match="two answers for BRK-0001"):
        resolve_answer_keys(
            {"BRK-0001": {"answer": "1"}, anchors["BRK-0001"]: {"answer": "2"}},
            groups, anchors, fp)


def test_manual_edits_pass_through():
    groups, anchors = _ctx(APR)
    me = {"ME@3": {"start": 3, "end": 4, "before": "x", "after": "y"}}
    by_gid, _, _ = resolve_answer_keys(me, groups, anchors, None)
    assert by_gid == me


def test_cli_strict_and_warning(tmp_path, capsys):
    m = _write(tmp_path, JUL)
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"schema": "specgen.answers/2", "answers": _apr_answers()}))
    out = tmp_path / "o.sec"
    assert main(["generate", str(m), "--answers", str(a), "-o", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "WARNING: 1 answer(s) did not resolve (master changed)" in printed
    assert "carries no scan fingerprint" not in printed  # anchors need none
    assert main(["generate", str(m), "--answers", str(a), "-o", str(out),
                 "--strict"]) == 1
