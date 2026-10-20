"""Corpus gate for subsection removal (plan 2026-10-19, Task 5).

For every master, answer every 5th subsection "remove" and run generate
with --revisions. generate's own verification is the main assertion: the
output parses, round-trips, is well-formed, carries no tracking marker, and
the revisions file resolves to the output and reverts to the master. Runs
only with SPECGEN_CORPUS set (the corpus is not in the repo)."""

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from specgen import secfile
from specgen.generate import generate
from specgen.manifest import build_manifest

CORPUS = Path(os.environ["SPECGEN_CORPUS"]) if os.environ.get("SPECGEN_CORPUS") else None
FILES = (
    sorted(p for p in CORPUS.rglob("*") if p.suffix.lower() == ".sec")
    if CORPUS and CORPUS.is_dir()
    else []
)

# Masters generate cannot verify as shipped, with the reason.
KNOWN_MALFORMED = {
    "22 60 70": "\\x13 control character in a <DTA> header field (not XML 1.0)",
}

pytestmark = pytest.mark.skipif(not FILES, reason="SPECGEN_CORPUS not set")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_remove_every_fifth_subsection(path, tmp_path):
    if path.stem in KNOWN_MALFORMED:
        pytest.skip(KNOWN_MALFORMED[path.stem])
    m = build_manifest(secfile.parse(path, tolerant=True))
    subs = {s["id"]: s for s in m["subsections"]}
    asked = [s for s in m["subsections"][::5]]
    asked_ids = {s["id"] for s in asked}
    answers = {s["anchor"]: {"answer": "remove", "id": s["id"]} for s in asked}

    summary = generate(path, {}, answers, tmp_path / "o.sec", revisions=True)

    def has_asked_ancestor(sid):
        p = subs[sid]["parent"]
        while p:
            if p in asked_ids:
                return True
            p = subs[p]["parent"]
        return False

    # governed subsections become bracket deletions, nested ones go with
    # their ancestor; every other answered subsection is removed itself
    expected = sum(
        1 for s in asked if not s["governed_by"] and not has_asked_ancestor(s["id"])
    )
    assert summary["subsections_removed"] == expected
    assert summary["answers_orphaned"] == 0

    # independent of generate's own bookkeeping: count what is left. Every
    # asked subsection without an asked ancestor goes, with its whole
    # subtree (governed ones through their bracket); nothing else changes.
    def subtree(sid):
        return 1 + sum(subtree(c) for c, s in subs.items() if s["parent"] == sid)

    gone = sum(subtree(s["id"]) for s in asked if not has_asked_ancestor(s["id"]))
    out = secfile.parse(tmp_path / "o.sec", tolerant=True)
    assert sum(1 for _ in out.root.iter("SPT")) == len(subs) - gone

    # Cleanup (plan 2026-10-20, Task 4), recounted from the output alone:
    # nothing that had a body use in the master is left with none, except
    # submittal items generate reports as blocked (inside a bracket, D1);
    # no SD heading or organization block that had entries is left empty.
    before, after = _usage(secfile.parse(path, tolerant=True)), _usage(out)
    changes = json.loads((tmp_path / "o.redline.json").read_text(encoding="utf-8"))["changes"]
    blocked = {
        _key(c["name"]) for c in changes
        if c["kind"] == "submittal-item" and c["action"].startswith("kept")
    }
    for name in after["items"]:
        if before["body_subs"][name] and not after["body_subs"][name]:
            assert name in blocked, f"orphaned submittal item survived: {name!r}"
    for rid in after["rids"]:
        if before["body_rids"][rid] and not after["body_rids"][rid]:
            raise AssertionError(f"orphaned reference survived: {rid!r}")
    for head, n in after["headings"].items():
        assert n or not before["headings"].get(head), f"empty SD heading left: {head!r}"
    for org, n in after["orgs"].items():
        assert n or not before["orgs"].get(org), f"empty organization block left: {org!r}"


def _key(text):
    return " ".join(text.split()).lower()


def _usage(sec):
    """Submittal items, SD headings (with item counts), declared references
    per organization, and body uses, read straight from the parse tree.
    Deliberately independent of specgen.manifest and specgen.cleanup."""
    root = sec.root
    titled = [
        s for s in root.iter("SPT")
        if s.first("TTL") is not None
        and _key(s.first("TTL").text()).startswith("submittal")
    ]
    art = next((s for s in titled if _key(s.first("TTL").text()) == "submittals"),
               titled[0] if titled else None)
    a0, a1 = (art.src_start, art.src_end) if art is not None else (-1, -1)
    items, headings = [], Counter()
    if art is not None:
        marks = []
        for lst in art.iter("LST"):
            t = lst.text().strip()
            if t.upper().startswith("SD-"):
                marks.append((lst.src_start, _key(t)))
                headings[_key(t)] += 0
        for itm in art.iter("ITM"):
            first = itm.first("SUB")
            if first is None:
                continue
            items.append(_key(first.text()))
            prior = [k for at, k in marks if at < itm.src_start]
            if prior:
                headings[prior[-1]] += 1
    body_subs = Counter(
        _key(e.text()) for e in root.iter("SUB") if not a0 <= e.src_start < a1
    )
    rids, orgs = [], Counter()
    for ref in root.iter("REF"):
        org = ref.first("ORG")
        name = _key(org.text()) if org is not None else ""
        orgs[name] += 0
        for rid in ref.iter("RID"):
            rids.append(_key(rid.text()))
            orgs[name] += 1
    body_rids = Counter(
        _key(e.text()) for e in root.iter("RID")
        if not any(a.name == "REF" for a in e.ancestors())
    )
    return {"items": items, "headings": headings, "body_subs": body_subs,
            "rids": rids, "orgs": orgs, "body_rids": body_rids}
