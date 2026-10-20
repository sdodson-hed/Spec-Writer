"""Decision page provenance (plan 2026-10-20 provenance, Task 4).

The pure helpers in STRUCT_CORE_JS run under Node when available (CI); the
template tests check the page wires them in."""

import shutil
import subprocess

import pytest

from specgen import secfile
from specgen.htmlpage import STRUCT_CORE_JS, write_html
from specgen.manifest import build_manifest
from tests.test_annotation import MINI

HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
const SRC = {kind: "schedule", ref: "ACC-1.compressor_type", rule: "compressor-type",
             data_source: "acc-sched-35", value: "SCROLL"};
const NOW = {kind: "schedule", ref: "ACC-1.compressor_type", rule: "compressor-type",
             data_source: "acc-sched-35", value: "ROTARY SCREW", answer: "3"};

// editing an auto answer makes it an override that remembers prefill's
let recs = {A: {answer: "2", source: {...SRC}, state: "auto"}};
stampEdits({A: "1"}, recs);
eq(recs.A, {answer: "2", source: {kind: "manual", was: {...SRC, answer: "1"}}, state: "overridden"},
   "auto edited -> overridden");
// a notes-only change (same answer) leaves provenance alone
recs = {A: {answer: "1", notes: "why", source: {...SRC}, state: "auto"}};
stampEdits({A: "1"}, recs);
eq(recs.A.state, "auto", "same answer: still auto");
// answering by hand where prefill had nothing
recs = {B: {answer: "keep"}};
stampEdits({}, recs);
eq(recs.B.source, {kind: "manual"}, "new answer -> manual");
// editing during a conflict decides it: override that acknowledges prefill now
recs = {C: {answer: "1", source: {kind: "manual", was: {...SRC, answer: "1"}, now: NOW}, state: "conflict"}};
stampEdits({C: "2"}, recs);
eq(recs.C, {answer: "1", source: {kind: "manual", was: NOW}, state: "overridden"}, "conflict edited");
eq(snapshot({A: {answer: "1"}, B: {notes: "x"}}), {A: "1", B: ""}, "snapshot");

// revert, keep mine, take prefill
const over = {answer: "2", id: "BRK-1", source: {kind: "manual", was: {...SRC, answer: "1"}}, state: "overridden"};
eq(revertOverride(over), {answer: "1", id: "BRK-1", source: SRC, state: "auto"}, "revert");
const conf = {answer: "2", id: "BRK-1", source: {kind: "manual", was: {...SRC, answer: "1"}, now: NOW}, state: "conflict"};
eq(keepMine(conf), {answer: "2", id: "BRK-1", source: {kind: "manual", was: NOW}, state: "overridden"}, "keep mine");
const {answer: _a, ...nowSrc} = NOW;
eq(takePrefill(conf), {answer: "3", id: "BRK-1", source: nowSrc, state: "auto"}, "take prefill");

// a duplicate's first instance follows its decision, override and conflict too
const MIR = {answer: "1", notes: "prefill (compressor-type): same decision as BRK-23",
             source: {...SRC}, state: "auto", same_as: "BRK-23"};
recs = {"BRK-23": {...over}, "BRK-2": {...MIR}};
followSameAs(recs);
eq(recs["BRK-2"], {answer: "2", source: over.source, state: "overridden",
                   notes: MIR.notes, same_as: "BRK-23"}, "mirror follows override");
recs = {"BRK-23": {...conf}, "BRK-2": {...MIR}};
eq(followSameAs(recs)["BRK-2"].state, "conflict", "mirror follows conflict");
recs = {"BRK-2": {...MIR}};
eq(followSameAs(recs), {}, "decision cleared: mirror cleared");
// editing the first instance itself releases it
recs = {"BRK-23": {...over}, "BRK-2": {...MIR, answer: "3"}};
releaseSameAs({"BRK-23": "2", "BRK-2": "1"}, recs);
followSameAs(recs);
eq([recs["BRK-2"].answer, "same_as" in recs["BRK-2"]], ["3", false], "released");

// classes for coloring
eq(provClass({answer: "1", source: SRC, state: "auto"}), "schedule", "auto schedule");
eq(provClass({answer: "keep", source: {kind: "bod"}, state: "auto"}), "bod", "bod");
eq(provClass(over), "overridden", "overridden");
eq(provClass(conf), "conflict", "conflict");
eq(provClass({answer: "x"}), "manual", "no source -> manual");
eq(provClass({answer: "", notes: "prefill (x): needs bod.y"}), "", "unanswered: none");
eq(provClass(undefined), "", "no record");
console.log("OK");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_provenance_core_under_node(tmp_path):
    js = tmp_path / "t.js"
    js.write_text(STRUCT_CORE_JS + HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "OK"


def test_page_wires_provenance(tmp_path):
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse_source(MINI)), out)
    html = out.read_text(encoding="utf-8")
    assert "function stampEdits(" in html and "stampAll()" in html
    assert "releaseSameAs(provSnap.a, state.answers);" in html
    assert "followSameAs(state.answers);" in html
    for hook in ("prov-schedule", "prov-conflict", "prov-overridden", "provlegend",
                 "Revert to prefill", "Keep mine", "Take prefill",
                 "profile_meta: state.profileMeta", "state.sptMeta"):
        assert hook in html, hook
    # palette (plan D1)
    for color in ("#2563eb", "#0d9488", "#6366f1", "#d97706", "#9333ea", "#6b7280", "#dc2626"):
        assert color in html, color
