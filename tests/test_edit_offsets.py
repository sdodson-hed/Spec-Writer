"""Regression test for the DOM<->display offset mapping behind inline editing.

Edit mode renders the FLOWED layout: each whitespace run of the master text
(CRLF line wraps, blank lines, BRK breaks) renders as a non-editable
.flowbrk span holding its replacement, so the editable DOM contains only
real master chars — run chars are zero-width in DOM space. dispOffset /
setCaretAt translate via a per-display-char width table (gapWidthsIn) or
every caret lands earlier than the click (the "spec-the-ification" bug
lineage).

The DOM helpers live in the page template, so this harness pairs them with a
minimal hand-rolled DOM shim (no jsdom): just the surface those functions
touch, modelling navanchor + flowbrk spans (zero-width), lockedtxt spans
(counted), and prior <s>/<ins> edit runs.
"""

import shutil
import subprocess

import pytest

from specgen.htmlpage import _TEMPLATE, EDIT_CORE_JS


def _dom_helpers_js():
    """The DOM offset helpers as they ship in the page template."""
    i = _TEMPLATE.index("const SKIP_SEL")
    j = _TEMPLATE.index("function selCtx")
    return _TEMPLATE[i:j]


SHIM = r"""
// ---- minimal DOM shim: only what the offset helpers touch ----
function TextNode(text) {
  return { nodeType: 3, textContent: text, childNodes: [],
           parentNode: null, parentElement: null, previousSibling: null };
}
function El(cls, kids, tag) {
  const el = {
    nodeType: 1, tagName: tag || "SPAN", childNodes: kids, dataset: {},
    parentNode: null, parentElement: null, previousSibling: null,
    classList: { contains: (c) => (cls || "").split(" ").indexOf(c) >= 0 },
    get textContent() { return kids.map(k => k.textContent).join(""); },
    contains(n) { for (let p = n; p; p = p.parentNode) if (p === el) return true;
                  return false; },
    closest(sel) { const cs = sel.split(",").map(s => s.trim().slice(1));
      for (let p = el; p; p = p.parentElement)
        if (p.classList && cs.some(c => p.classList.contains(c))) return p;
      return null; },
  };
  kids.forEach((k, i) => {
    k.parentNode = el; k.parentElement = el;
    k.previousSibling = i > 0 ? kids[i - 1] : null;
  });
  return el;
}
const NodeFilter = { SHOW_TEXT: 4 };
const document = {
  createTreeWalker(root) {
    const texts = [];
    (function walk(n) {
      if (n.nodeType === 3) texts.push(n);
      else for (const c of n.childNodes) walk(c);
    })(root);
    let i = -1;
    return { nextNode() { i += 1; return texts[i] || null; } };
  },
  createRange() {
    return { startContainer: null, startOffset: 0,
             setStart(n, o) { this.startContainer = n; this.startOffset = o; },
             collapse() {} };
  },
};
let currentRange = null;
const window = {
  getSelection() {
    return { removeAllRanges() { currentRange = null; },
             addRange(r) { currentRange = r; } };
  },
};
"""

HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
// ---- gap composition mirroring the real 1.1 REFERENCES note bug ----
// CRLF master text; a navanchor (visible "1.1", zero-width in the model);
// a prior <s>/<ins> edit; a lockedtxt span; the caret after "and".
const CRLF = "\r\n";
const TEXT =
  "alpha line one" + CRLF +
  "REFERENCES" + CRLF +
  "The publications are referred to in the text by basic" + CRLF +
  "designation only and listed in this [para] graph." + CRLF;
const S = 0, E = TEXT.length;
const REC_START = TEXT.indexOf("publications");
const EDITS = { ["ME@" + REC_START]: { start: REC_START,
  end: REC_START + "publications".length,
  before: "publications", after: "docs", notes: "" } };
const LS = TEXT.indexOf("[para]"), LE = LS + "[para]".length;
const ANCHOR_AT = TEXT.indexOf("REFERENCES");
// page globals the helpers read
const DATA = { text: TEXT };
const state = { edits: EDITS };

// template wrapper the sliced helpers call (page defines it near the top)
let flowRuns = null;
function flowRunsAll() {
  if (!flowRuns) flowRuns = flowRunsFor(DATA.text);
  return flowRuns;
}

// Build the gap DOM exactly as gapInner renders it in FLOWED edit mode:
// non-run text verbatim in text nodes; every whitespace run replaced by a
// non-editable flowbrk span holding its replacement.
function flowKids(a, b) {
  const out = [];
  let pos = a;
  for (const r of flowRunsAll()) {
    if (r.e <= a || r.s >= b) continue;
    if (r.s > pos) out.push(TextNode(TEXT.slice(pos, r.s)));
    if (r.s >= a) out.push(El("flowbrk", [TextNode(r.rep)]));
    pos = Math.min(r.e, b);
  }
  if (pos < b) out.push(TextNode(TEXT.slice(pos, b)));
  return out;
}
const kids = [].concat(
  flowKids(0, ANCHOR_AT),
  [El("navanchor", [El("paranum", [TextNode("1.1")])])],
  flowKids(ANCHOR_AT, REC_START),
  [El("me", [TextNode("publications")], "S"),
   El("me", [TextNode("docs")], "INS")],
  flowKids(REC_START + "publications".length, LS),
  [El("lockedtxt", flowKids(LS, LE))],
  flowKids(LE, E),
);
const gap = El("gap", kids);
gap.dataset.s = String(S);
gap.dataset.e = String(E);

// ---- the user's click: caret right after "and" ----
const caretNode = kids.find(k =>
  k.nodeType === 3 && k.textContent.indexOf(" listed") >= 0);
const domOff = caretNode.textContent.indexOf(" listed");
const wantOrig = TEXT.indexOf(" listed");         // original offset after "and"

const runs = gapRuns(TEXT, EDITS, S, E);
const disp = dispOffset(gap, caretNode, domOff);
eq(displayToOrig(runs, S, disp), wantOrig,
   "clicked caret maps to the clicked original offset (flowed gap)");

// element-container selection (browser sometimes reports the gap element):
// offset counts child nodes; compute the expected orig from the DOM chars
// the first 5 children hold ("alpha line one" + flowbrk + navanchor +
// "REFERENCES" + flowbrk = 24 editable chars = orig 26, after REFERENCES)
eq(displayToOrig(runs, S, dispOffset(gap, gap, 5)),
   TEXT.indexOf("The publications") - 2,
   "element-container offset maps across zero-width fillers");

// ---- caret restore is the exact inverse ----
setCaretAt(gap, disp);
eq(dispOffset(gap, currentRange.startContainer, currentRange.startOffset), disp,
   "setCaretAt/dispOffset round-trip");
const ctx = currentRange.startContainer.textContent
  .slice(currentRange.startOffset - 3, currentRange.startOffset + 7);
eq(ctx, "and listed", "restored caret sits visually after 'and'");

// caret at end of a line and at start of the next line both map to the
// line-break run's start (zero-width cluster; ties resolve before it)
const basicNode = kids.find(k =>
  k.nodeType === 3 && k.textContent.indexOf("by basic") >= 0);
const eolDisp = dispOffset(gap, basicNode, basicNode.textContent.length);
eq(displayToOrig(runs, S, eolDisp), TEXT.indexOf("\r\ndesignation"),
   "end-of-line caret maps to the CRLF run start");
const nextNode = kids.find(k =>
  k.nodeType === 3 && k.textContent.indexOf("designation") >= 0);
eq(dispOffset(gap, nextNode, 0), eolDisp,
   "start-of-next-line caret maps to the same display offset");
console.log("OK");
"""


def _node():
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="node not on PATH")
def test_dom_display_offsets_with_crlf_text(tmp_path):
    js = tmp_path / "offsets_test.js"
    js.write_text(EDIT_CORE_JS + SHIM + _dom_helpers_js() + HARNESS,
                  encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(js)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout
