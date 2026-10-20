"""Subsection notes survive the decision page (gap 1 from the step 7 browser
check): importing an answers file kept only keep/remove values, so prefill's
"needs bod.heat_recovery" on an unanswered subsection was lost on export."""

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
const NOTE = "prefill (heat-recovery): needs bod.heat_recovery";
const SRC = {kind: "bod", ref: "bod.heat_recovery", rule: "heat-recovery", value: true};
eq(readSptImport({answer: "", notes: NOTE, id: "SPT-0040"}), {value: "", notes: NOTE, meta: null},
   "notes only");
eq(readSptImport({answer: "Keep", notes: " mine ", source: SRC, state: "auto"}),
   {value: "keep", notes: "mine", meta: {source: SRC, state: "auto"}}, "answer, note and source");
eq(readSptImport("remove"), {value: "remove", notes: "", meta: null}, "bare string");
eq(readSptImport({answer: "maybe"}), {value: "", notes: "", meta: null}, "invalid value dropped");
console.log("OK");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_spt_import_under_node(tmp_path):
    js = tmp_path / "t.js"
    js.write_text(STRUCT_CORE_JS + HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "OK"


def test_page_keeps_subsection_notes(tmp_path):
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse_source(MINI)), out)
    html = out.read_text(encoding="utf-8")
    for hook in ("state.sptNotes = state.sptNotes || {}",   # stored
                 "readSptImport(v)",                      # import
                 "...Object.keys(state.sptNotes)",          # export
                 'class="sptnote"'):                        # outline marker
        assert hook in html, hook
