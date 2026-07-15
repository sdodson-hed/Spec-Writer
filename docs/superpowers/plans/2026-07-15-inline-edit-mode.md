# Inline Edit Mode (Live Tracked Changes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the HTML decision page's select-and-replace text editing with a Word-like Edit mode: free typing in the document with live tracked changes (green insertions, red strikethrough deletions), stored in the existing `ME@` answer format.

**Architecture:** The DOM stays a pure view. Every keystroke is intercepted via `beforeinput`, computed against a pure "run model" (original/deleted/inserted text runs derived from `state.edits`), the `ME@` records are updated, and the one affected gap re-renders with the caret restored. A review card on the right shows any clicked change with notes + revert. Custom per-decision text reuses the existing freeform-answer path (`generate` already applies it).

**Tech Stack:** Python 3 (specgen), vanilla JS inside the `_TEMPLATE` string in `specgen/htmlpage.py`, pytest; optional Node for pure-JS unit tests (skipped when absent).

**Spec:** `docs/superpowers/specs/2026-07-15-inline-edit-mode-design.md` — read it first.

## Global Constraints

- The page must stay ONE self-contained HTML file: no external libraries, no network, no server. All JS lives inside `_TEMPLATE` / `EDIT_CORE_JS` strings in `specgen/htmlpage.py`.
- Manual edits keep the exact existing answer format: key `ME@<start>`, value `{start, end, before, after, notes}` in original-master character offsets (`DATA.text`). `answers.py` must not change; `generate.py` may change only in the single validation widening Task 5 Step 1 specifies (accepting insertion-only records).
- Never default or silently drop an answer; drops are counted and surfaced (existing `staleEditsDropped` notice pattern).
- Test commands: `python -m pytest tests/ -q` (full suite currently 108 passing), `python scripts/audit_corpus.py` (55/55 must stay green).
- Run all commands from the repo root `C:\Users\Victor Colosi\dev\Spec intact`.
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- JS style: match the template's existing style (2-space indent, `const`/arrow functions, no semicolon omission, `esc()` for all interpolated text).

---

### Task 1: Pure edit core (run model) + Node-backed unit tests

**Files:**
- Modify: `specgen/htmlpage.py` (add module constant `EDIT_CORE_JS`; inject into `_TEMPLATE` via a `__EDIT_CORE__` placeholder inside the `<script>` block, right after the `esc` helper definition around line 219; extend `write_html`)
- Test: `tests/test_edit_core.py` (new)

**Interfaces:**
- Produces (pure JS, no DOM, no globals — later tasks call these):
  - `gapRuns(text, records, s, e) -> [{t:"o"|"d"|"i", text}]`
  - `runsToRecords(runs, gapStart, oldRecords) -> {"ME@<start>": {start,end,before,after,notes}}`
  - `applyGapOp(text, records, s, e, op, lockedOrig) -> {records, caret} | {blocked:true} | null`
    - `op` is one of `{kind:"ins", at, text}`, `{kind:"replace", from, to, text}`, `{kind:"del", from, to}`, `{kind:"bs", caret}`, `{kind:"fwd", caret}` — all offsets are *display offsets* (positions in the concatenated run texts)
    - `lockedOrig` is `[[origStart, origEnd], ...]`
  - `origToDisplay(runs, gapStart, origOff) -> displayOff`
- Produces (Python): `from specgen.htmlpage import EDIT_CORE_JS` (the raw JS string)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_edit_core.py`:

```python
"""Unit tests for the pure JS edit core, run under Node when available.

The core is DOM-free by design so it can be tested headlessly. The harness
appends assertions to the core source and runs `node` on the result; any
failed assertion exits non-zero with a message.
"""

import shutil
import subprocess

import pytest

from specgen.htmlpage import EDIT_CORE_JS

HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
const TEXT = "0123456789ABCDEF";       // stand-in master text
const S = 2, E = 12;                   // gap covers "23456789AB"

// fresh gap: one original run
eq(gapRuns(TEXT, {}, S, E), [{t:"o",text:"23456789AB"}], "fresh gap");

// type "xy" at display 3 -> ins run, caret after typed text
let r = applyGapOp(TEXT, {}, S, E, {kind:"ins", at:3, text:"xy"}, []);
eq(r.records, {"ME@5":{start:5,end:5,before:"",after:"xy",notes:""}}, "insert record");
eq(r.caret, 5, "insert caret");
// display is now "234xy56789AB"

// backspace at caret 5 removes the typed 'y' for real
r = applyGapOp(TEXT, r.records, S, E, {kind:"bs", caret:5}, []);
eq(r.records, {"ME@5":{start:5,end:5,before:"",after:"x",notes:""}}, "bs on ins char");
eq(r.caret, 4, "bs caret");
// display "234x56789AB"

// select display [4,6) = original "56" and delete -> strikethrough, coalesced
r = applyGapOp(TEXT, r.records, S, E, {kind:"del", from:4, to:6}, []);
eq(r.records, {"ME@5":{start:5,end:7,before:"56",after:"x",notes:""}}, "coalesced d+i");
// canonical display "234" + del"56" + ins"x" + "789AB" = "23456x789AB"
eq(r.caret, 5, "selection-delete caret sits after the strikethrough");

// backspace with the caret right after the struck run skips it, strikes '4'
r = applyGapOp(TEXT, r.records, S, E, {kind:"bs", caret:5}, []);
eq(r.records["ME@4"], {start:4,end:7,before:"456",after:"x",notes:""}, "bs skips struck run");
eq(Object.keys(r.records).length, 1, "records merged");
eq(r.caret, 2, "bs caret lands before the strikethrough");

// typed-then-erased no-op records are dropped
let n = applyGapOp(TEXT, {}, S, E, {kind:"ins", at:3, text:"q"}, []);
n = applyGapOp(TEXT, n.records, S, E, {kind:"bs", caret:4}, []);
eq(n.records, {}, "no-op record dropped");

// notes carry over when start+before are unchanged
let withNote = {"ME@5":{start:5,end:7,before:"56",after:"x",notes:"why"}};
let k = applyGapOp(TEXT, withNote, S, E, {kind:"ins", at:9, text:"Z"}, []);
eq(k.records["ME@5"].notes, "why", "note carried");
eq(k.records["ME@9"], {start:9,end:9,before:"",after:"Z",notes:""}, "second record");

// replace: selection typed over -> strike + insert after the strikethrough
let rp = applyGapOp(TEXT, {}, S, E, {kind:"replace", from:1, to:3, text:"NEW"}, []);
eq(rp.records, {"ME@3":{start:3,end:5,before:"34",after:"NEW",notes:""}}, "replace record");
eq(rp.caret, 6, "replace caret after inserted text");

// forward delete targets the next unstruck char
let fw = applyGapOp(TEXT, {"ME@3":{start:3,end:5,before:"34",after:"",notes:""}}, S, E,
                    {kind:"fwd", caret:1}, []);
eq(fw.records["ME@3"], {start:3,end:6,before:"345",after:"",notes:""}, "fwd extends strike");

// boundary: backspace at display 0 is a null (nothing to do)
eq(applyGapOp(TEXT, {}, S, E, {kind:"bs", caret:0}, []), null, "bs at gap start");

// locked ranges block ops that touch them; boundary insert is allowed
const LOCKED = [[7, 9]];  // original "78"
eq(applyGapOp(TEXT, {}, S, E, {kind:"del", from:4, to:6}, LOCKED), {blocked:true}, "del into locked");
eq(applyGapOp(TEXT, {}, S, E, {kind:"ins", at:6, text:"w"}, LOCKED), {blocked:true}, "ins inside locked");
let ok = applyGapOp(TEXT, {}, S, E, {kind:"ins", at:5, text:"w"}, LOCKED);
eq(ok.records, {"ME@7":{start:7,end:7,before:"",after:"w",notes:""}}, "ins at locked boundary ok");

// invariant: o+d text always reconstructs the original slice
function odText(runs) { return runs.filter(r2 => r2.t !== "i").map(r2 => r2.text).join(""); }
eq(odText(gapRuns(TEXT, r.records, S, E)), TEXT.slice(S, E), "o+d invariant");

// origToDisplay maps original offsets through insertions: display is
// "234" + "56"(struck) + "xxx"(ins) + "789AB"; orig 9 ("9") -> display 10
let runs2 = gapRuns(TEXT, {"ME@5":{start:5,end:7,before:"56",after:"xxx",notes:""}}, S, E);
eq(origToDisplay(runs2, S, 9), 10, "orig offset through a d+i cluster");
console.log("OK");
"""


def _node():
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="node not on PATH")
def test_edit_core_under_node(tmp_path):
    js = tmp_path / "core_test.js"
    js.write_text(EDIT_CORE_JS + HARNESS, encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(js)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout


def test_edit_core_is_injected_into_page(tmp_path):
    from specgen import secfile
    from specgen.htmlpage import write_html
    from specgen.manifest import build_manifest

    p = tmp_path / "t.SEC"
    p.write_bytes(
        "<SEC><TXT>Provide [scroll][screw] compressors.</TXT></SEC>".encode(
            secfile.ENCODING
        )
    )
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "function applyGapOp(" in html
    assert "function gapRuns(" in html
    assert "__EDIT_CORE__" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_edit_core.py -q`
Expected: FAIL / ERROR with `ImportError: cannot import name 'EDIT_CORE_JS'`

- [ ] **Step 3: Implement the core**

In `specgen/htmlpage.py`, add above `_TEMPLATE`:

```python
# Pure edit-core: the run model behind inline editing. DOM-free by design so
# it is unit-testable under Node (tests/test_edit_core.py). Injected into
# _TEMPLATE at __EDIT_CORE__.
EDIT_CORE_JS = r"""
// ---- inline edit core (pure; no DOM, no globals) ----
// Runs {t:"o"|"d"|"i", text}: original kept, deleted original, inserted.
// Invariant: concatenated o+d texts === text.slice(s, e).
// "Display offsets" index the concatenation of ALL run texts (the visible
// redline text). Records are the ME@ format: {start,end,before,after,notes}
// in original-text offsets; insertion-only records have start === end.
function gapRuns(text, records, s, e) {
  const recs = Object.values(records || {})
    .filter(r => r.start >= s && r.end <= e)
    .sort((a, b) => a.start - b.start);
  const runs = [];
  let pos = s;
  for (const r of recs) {
    if (r.start > pos) runs.push({ t: "o", text: text.slice(pos, r.start) });
    if (r.before) runs.push({ t: "d", text: r.before });
    if (r.after) runs.push({ t: "i", text: r.after });
    pos = r.end;
  }
  if (pos < e) runs.push({ t: "o", text: text.slice(pos, e) });
  return runs;
}
function mergeRuns(runs) {
  const out = [];
  for (const r of runs) {
    if (!r.text) continue;
    const top = out[out.length - 1];
    if (top && top.t === r.t) top.text += r.text;
    else out.push({ t: r.t, text: r.text });
  }
  return out;
}
function splitRuns(runs, at) {
  const L = [], R = [];
  let pos = 0;
  for (const r of runs) {
    const end = pos + r.text.length;
    if (end <= at) L.push({ t: r.t, text: r.text });
    else if (pos >= at) R.push({ t: r.t, text: r.text });
    else {
      L.push({ t: r.t, text: r.text.slice(0, at - pos) });
      R.push({ t: r.t, text: r.text.slice(at - pos) });
    }
    pos = end;
  }
  return [L, R];
}
function runsToRecords(runs, gapStart, oldRecords) {
  const recs = {};
  let orig = gapStart, i = 0;
  while (i < runs.length) {
    if (runs[i].t === "o") { orig += runs[i].text.length; i++; continue; }
    const start = orig;
    let before = "", after = "";
    while (i < runs.length && runs[i].t !== "o") {
      if (runs[i].t === "d") { before += runs[i].text; orig += runs[i].text.length; }
      else after += runs[i].text;
      i++;
    }
    if (before === after) continue;   // typed-then-erased no-op
    const rec = { start, end: orig, before, after, notes: "" };
    for (const old of Object.values(oldRecords || {}))
      if (old.notes && old.start === start && old.before === before)
        rec.notes = old.notes;
    recs["ME@" + start] = rec;
  }
  return recs;
}
function origToDisplay(runs, gapStart, origOff) {
  let disp = 0, orig = gapStart;
  for (const r of runs) {
    if (r.t === "i") { disp += r.text.length; continue; }
    if (origOff <= orig + r.text.length) return disp + (origOff - orig);
    orig += r.text.length;
    disp += r.text.length;
  }
  return disp;
}
function displayToOrig(runs, gapStart, at) {
  // original offset at display position `at` (i chars are zero-width)
  let disp = 0, orig = gapStart;
  for (const r of runs) {
    const end = disp + r.text.length;
    if (at <= end) {
      if (r.t === "i") return orig;
      return orig + (at - disp);
    }
    disp = end;
    if (r.t !== "i") orig += r.text.length;
  }
  return orig;
}
function deleteTarget(runs, caret, dir) {
  // The single display char a collapsed Backspace (dir -1) / Delete (dir +1)
  // affects, skipping already-struck chars; null at the gap boundary.
  const types = [];
  for (const r of runs)
    for (let k = 0; k < r.text.length; k++) types.push(r.t);
  let i = dir < 0 ? caret - 1 : caret;
  while (i >= 0 && i < types.length && types[i] === "d") i += dir;
  if (i < 0 || i >= types.length) return null;
  return { from: i, to: i + 1 };
}
function skipDel(runs, at) {
  // an insertion point strictly inside a struck run moves to its end, so
  // replacement text always follows its strikethrough
  let pos = 0;
  for (const r of runs) {
    const end = pos + r.text.length;
    if (r.t === "d" && at > pos && at < end) return end;
    pos = end;
  }
  return at;
}
function insLead(runs, at) {
  // i chars in the caret's cluster strictly before display `at` (clusters
  // are maximal d/i stretches; an o run resets the count)
  let disp = 0, lead = 0;
  for (const r of runs) {
    const end = disp + r.text.length;
    if (r.t === "o" && end <= at) lead = 0;
    if (r.t === "i" && at > disp) lead += Math.min(at, end) - disp;
    if (end >= at) break;
    disp = end;
  }
  return lead;
}
function opBlocked(runs, gapStart, lockedOrig, from, to) {
  const a = displayToOrig(runs, gapStart, from);
  const b = displayToOrig(runs, gapStart, to);
  for (const [ls, le] of lockedOrig || []) {
    if (from === to ? a > ls && a < le : a < le && b > ls) return true;
  }
  return false;
}
function applyGapOp(text, records, s, e, op, lockedOrig) {
  let runs = gapRuns(text, records, s, e);
  const dispLen = runs.reduce((n, r) => n + r.text.length, 0);
  let from, to, ins = "";
  if (op.kind === "ins") { from = to = skipDel(runs, op.at); ins = op.text; }
  else if (op.kind === "replace") { from = op.from; to = op.to; ins = op.text; }
  else if (op.kind === "del") { from = op.from; to = op.to; }
  else {
    const t = deleteTarget(runs, op.caret, op.kind === "bs" ? -1 : 1);
    if (!t) return null;
    from = t.from; to = t.to;
  }
  if (from > to) { const x = from; from = to; to = x; }
  if (from < 0 || to > dispLen) return null;
  if (opBlocked(runs, s, lockedOrig, from, to)) return { blocked: true };
  // 1) strike/remove the selected range
  let struckEnd = from;
  if (to > from) {
    const [L, MR] = splitRuns(runs, from);
    const [M, R] = splitRuns(MR, to - from);
    const mid = M.filter(r => r.t !== "i").map(r => ({ t: "d", text: r.text }));
    struckEnd = from + mid.reduce((n, r) => n + r.text.length, 0);
    runs = mergeRuns([].concat(L, mid, R));
  }
  // 2) insert after the strikethrough
  let insAt = struckEnd, lead = 0;
  if (ins) {
    insAt = skipDel(runs, insAt);
    lead = insLead(runs, insAt);
    const [L2, R2] = splitRuns(runs, insAt);
    runs = mergeRuns([].concat(L2, [{ t: "i", text: ins }], R2));
  }
  const recs = runsToRecords(runs, s, records);
  // 3) caret in CANONICAL display space (records render d-then-i per cluster)
  const canon = gapRuns(text, recs, s, e);
  const opOrig = displayToOrig(runs, s, ins ? insAt : from);
  let caret;
  const cluster = Object.values(recs)
    .find(r => r.start <= opOrig && opOrig <= r.end);
  if (!cluster) {
    caret = origToDisplay(canon, s, opOrig);
  } else {
    // display start of the cluster's strikethrough
    let dispStart = 0, orig = s;
    for (const r of canon) {
      if (orig === cluster.start && (r.t === "d" || r.t === "i")) break;
      dispStart += r.text.length;
      if (r.t !== "i") orig += r.text.length;
    }
    if (ins) caret = dispStart + cluster.before.length + lead + ins.length;
    else if (op.kind === "bs") caret = dispStart;
    else caret = dispStart + cluster.before.length;
  }
  return { records: recs, caret };
}
"""
```

Note for the implementer: if any harness expectation disagrees with the
implementation, debug the implementation with `node <file>` directly (the
harness prints got/expected); the harness values were hand-derived and are
the source of truth for behavior.

Inject into the template: inside `_TEMPLATE`, immediately after the line
`const esc = s => ...;` (around line 219), add a line containing only
`__EDIT_CORE__`. Then in `write_html`, add to the replacement chain:

```python
        .replace("__EDIT_CORE__", EDIT_CORE_JS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_edit_core.py -q`
Expected: 2 passed (or 1 passed, 1 skipped where node is unavailable — on this machine node exists, so 2 passed)

- [ ] **Step 5: Run the full suite (nothing else should move)**

Run: `python -m pytest tests/ -q`
Expected: 110 passed

- [ ] **Step 6: Commit**

```bash
git add specgen/htmlpage.py tests/test_edit_core.py
git commit -m "Pure run-model edit core with Node-backed unit tests"
```

---

### Task 2: Inline edit-run rendering + review card; remove select-and-replace

**Files:**
- Modify: `specgen/htmlpage.py` (`_TEMPLATE` JS: `buildDoc`, new `gapInner`/`origHtml`, delete `onDocMouseUp`/`rejectSelection`/`startEdit`/`renderEditCard`/`saveEdit`/`removeEdit`/`updateMeMark`/`meState`; new `renderMeCard`/`meCardId`; CSS)
- Test: `tests/test_htmlpage.py` (update `test_manual_text_edit_hooks_present`; add new tests)

**Interfaces:**
- Consumes: `gapRuns` from Task 1.
- Produces:
  - `.gap` spans now carry `data-s` AND `data-e` (original-offset bounds).
  - Manual edits render inline inside gaps as `<s class="me" data-me="ME@N">before</s><ins class="me" data-me="ME@N">after</ins>` (redline view) or `<span class="me" data-me="ME@N">after</span>` (clean view).
  - `renderGap(gapEl)` — re-renders one gap from records and re-wires its `.me` click handlers (Task 3 calls this after every keystroke).
  - `meCardId` (string|null) + `renderMeCard(p)` — the review card; `renderPanel()` dispatches to it when `meCardId` is set.
  - `lockedOrigIn(s, e) -> [[start, end], ...]` — plural/in-note decision spans inside a gap (Task 3 passes these to `applyGapOp`; this task renders them as `<span class="lockedtxt" contenteditable="false">`).
  - Module-level `docAnchors` — nav anchors with a `gap` field naming the owning gap's `data-s`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_htmlpage.py`, replace `test_manual_text_edit_hooks_present` and add:

```python
def test_manual_text_edit_hooks_present(tmp_path):
    # Inline edit mode: edits render inside gaps; review card replaces the
    # old select-and-replace card.
    html = _page(tmp_path)
    assert 'class="gap" data-s=' in html    # offset-mapped gaps
    assert "data-e=" in html                # gap end bound for the editor
    assert "TEXT EDIT" in html              # review-card chip
    assert "data-me" in html                # edit-run attribute/lookup
    assert "state.edits" in html            # edit records persisted in state
    assert "renderMeCard" in html           # review & revert card
    assert "Revert this change" in html


def test_select_and_replace_flow_removed(tmp_path):
    html = _page(tmp_path)
    assert "onDocMouseUp" not in html
    assert "rejectSelection" not in html
    assert "renderEditCard" not in html
    assert "updateMeMark" not in html
    assert 'addEventListener("mouseup"' not in html


def test_edits_render_inline_not_as_islands(tmp_path):
    html = _page(tmp_path)
    assert "gapInner" in html
    assert 's class="me"' in html or 'class=\\"me\\"' in html or "s.me" in html
    assert "#doc s.me" in html              # CSS for inline deleted run
    assert "#doc ins.me" in html            # CSS for inline inserted run
    assert "mark.me" not in html            # old island styling/wiring gone


def test_locked_inline_spans_present(tmp_path):
    html = _page(tmp_path)
    assert "lockedtxt" in html
    assert "lockedOrigIn" in html
    # plural and in-note bracket spans are page-locked for generate parity
    assert "d.in_note || d.plural" in html


def test_prune_also_rejects_locked_overlaps(tmp_path):
    html = _page(tmp_path)
    body = html.split("function meConflict(")[1].split("\nfunction ")[0]
    assert "in_note" in body and "plural" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_htmlpage.py -q`
Expected: the 5 tests above FAIL (others pass)

- [ ] **Step 3: Implement the rendering rework**

All changes inside `_TEMPLATE` in `specgen/htmlpage.py`.

3a. **CSS** — in the `<style>` block, REMOVE the `#doc mark.me { ... }` rule and ADD:

```css
#doc s.me { color: var(--del-ink); background: var(--del);
  text-decoration: line-through; cursor: pointer; border-radius: 3px; }
#doc ins.me { color: var(--done-ink); background: var(--done);
  text-decoration: underline; cursor: pointer; border-radius: 3px; }
#doc span.me { cursor: pointer; border-bottom: 1px dashed var(--accent); }
#doc .lockedtxt { border-radius: 3px; }
#doc.editing .gap { cursor: text; }
#doc.editing .gap:focus { outline: none; }
#doc.editing mark, #doc.editing .lockedtxt, #doc.editing s.unitcut {
  box-shadow: 0 0 0 1px var(--line) inset; background-clip: padding-box; }
```

3b. **`activeSpans()`** — delete the two lines that push manual-edit spans:

```js
  for (const [id, rec] of Object.entries(state.edits || {}))
    spans.push({ s: rec.start, e: rec.end, pri: 3, me: id });
```

3c. **`buildDoc()`** — replace the whole function (and delete the old inner
`gapHtml`) with:

```js
let docAnchors = [];
function computeDocAnchors(roots) {
  // pin anchors that fall inside a root island to the island start, then
  // assign each anchor to the gap that renders it (same cursor walk the old
  // gapHtml used, so boundary anchors land exactly once)
  const anchors = (DATA.nav || [])
    .map((n, i) => ({ c: n.char, i }))
    .sort((a, b) => a.c - b.c);
  for (const a of anchors)
    for (const sp of roots)
      if (a.c > sp.s && a.c < sp.e) { a.c = sp.s; break; }
  const gaps = [];
  let pos = 0;
  for (const sp of roots) { gaps.push([pos, sp.s]); pos = sp.e; }
  gaps.push([pos, DATA.text.length]);
  let ai = 0;
  for (const [from, to] of gaps)
    while (ai < anchors.length && anchors[ai].c <= to) {
      anchors[ai].gap = from;
      anchors[ai].c = Math.max(anchors[ai].c, from);
      ai++;
    }
  docAnchors = anchors;
}
function lockedOrigIn(s, e) {
  return DATA.decisions
    .filter(d => (d.in_note || d.plural) && d.char_start >= s && d.char_end <= e)
    .map(d => [d.char_start, d.char_end])
    .sort((a, b) => a[0] - b[0]);
}
function origHtml(gapStart, a, b) {
  // original text slice [a,b) with nav anchors and locked-span tints
  const marks = docAnchors
    .filter(an => an.gap === gapStart && an.c >= a && an.c <= b)
    .map(an => ({ at: an.c, anchor: an.i }));
  for (const [ls, le] of lockedOrigIn(a, b))
    marks.push({ at: ls, lockEnd: le });
  marks.sort((x, y) => x.at - y.at);
  let html = "", pos = a;
  for (const m of marks) {
    html += esc(DATA.text.slice(pos, m.at));
    pos = m.at;
    if (m.anchor !== undefined) {
      const n = DATA.nav[m.anchor];
      const num = n && n.depth > 0 && n.num
        ? `<span class="paranum">${esc(n.num)}</span>` : "";
      html += `<span class="navanchor" contenteditable="false" id="nav-${m.anchor}">${num}</span>`;
    } else {
      html += `<span class="lockedtxt" contenteditable="false">${esc(DATA.text.slice(m.at, m.lockEnd))}</span>`;
      pos = m.lockEnd;
    }
  }
  html += esc(DATA.text.slice(pos, b));
  return html;
}
function gapInner(s, e) {
  const recs = Object.values(state.edits || {})
    .filter(r => r.start >= s && r.end <= e)
    .sort((a, b) => a.start - b.start);
  let html = "", pos = s;
  for (const r of recs) {
    html += origHtml(s, pos, r.start);
    const id = "ME@" + r.start;
    if (state.view === "redline") {
      if (r.before) html += `<s class="me" data-me="${esc(id)}">${esc(r.before)}</s>`;
      if (r.after) html += `<ins class="me" data-me="${esc(id)}">${esc(r.after)}</ins>`;
    } else if (r.after) {
      html += `<span class="me" data-me="${esc(id)}">${esc(r.after)}</span>`;
    }
    pos = r.end;
  }
  html += origHtml(s, pos, e);
  return html;
}
function gapAttrs() {
  return editMode ? ' contenteditable="true" spellcheck="false"' : "";
}
function wireMeRuns(root) {
  root.querySelectorAll(".me[data-me]").forEach(el => el.onclick = () => {
    meCardId = el.dataset.me;
    const prev = activeId;
    activeId = null;
    if (prev && byId[prev]) updateMark(byId[prev]);
    renderPanel();
  });
}
function renderGap(gapEl) {
  gapEl.innerHTML = gapInner(+gapEl.dataset.s, +gapEl.dataset.e);
  wireMeRuns(gapEl);
}
function buildDoc() {
  const doc = document.getElementById("doc");
  const spans = activeSpans();
  const roots = spans.filter(sp => !sp.parent);
  computeDocAnchors(roots);
  let html = "", pos = 0;
  const emit = (sp) => {
    const kids = spans.filter(k => k.parent === sp);
    let inner = "", p = sp.s;
    for (const k of kids) { inner += esc(DATA.text.slice(p, k.s)); inner += emit(k); p = k.e; }
    inner += esc(DATA.text.slice(p, sp.e));
    if (sp.d) return `<mark data-id="${sp.d.id}" id="mk-${sp.d.id}">${inner}</mark>`;
    if (sp.tai) {
      const n = sp.e - sp.s;
      return state.view === "redline"
        ? `<mark class="deleted taicut" data-opt="${esc(sp.tai)}" title="click to expand">▸ ${esc(sp.tai)} removed (${n} chars)</mark>`
        : "";
    }
    return state.view === "redline" ? `<s class="unitcut">${inner}</s>` : "";
  };
  const gap = (from, to) =>
    `<span class="gap" data-s="${from}" data-e="${to}"${gapAttrs()}>${gapInner(from, to)}</span>`;
  for (const sp of roots) {
    html += gap(pos, sp.s);
    html += emit(sp);
    pos = sp.e;
  }
  html += gap(pos, DATA.text.length);
  doc.innerHTML = html;
  doc.classList.toggle("editing", editMode);
  doc.querySelectorAll("mark[data-id]").forEach(m => m.onclick = () => select(m.dataset.id, false));
  doc.querySelectorAll("mark.taicut").forEach(m => m.onclick = () => {
    alert("Tailoring block '" + m.dataset.opt + "' is removed by the Project Profile. Set it back to 'keep' to restore the text.");
  });
  wireMeRuns(doc);
  ds.forEach(updateMark);
}
```

`editMode` does not exist until Task 3 — declare a placeholder near the top
of the script (after `let meState = null;`, which this task deletes):
`let editMode = false; let meCardId = null;`

3d. **Delete the whole select-and-replace block** (`// ---- manual text
edits (select-and-replace, tracked changes) ----` through `removeEdit`)
EXCEPT `pruneStaleEdits` and `meConflict`, which stay. Delete
`Object.keys(state.edits || {}).forEach(updateMeMark);` (now gone from
buildDoc), the `updateMeMark` function, the `mark.me` click wiring, the
`doc.addEventListener("mouseup", onDocMouseUp)` line, `let meState = null;`,
and the `meState = null;` resets in `select()` / `btnClear` (replace those
resets with `meCardId = null;`).

3e. **Extend `meConflict`** (import-time parity with generate): after the
`for (const d of ds)` loop add:

```js
  for (const d of DATA.decisions)
    if ((d.in_note || d.plural) && s < d.char_end && e > d.char_start)
      return `locked text (${d.id})`;
```

3f. **Review card.** Replace `renderPanel`'s first line dispatch
`if (meState) { renderEditCard(p); return; }` with
`if (meCardId) { renderMeCard(p); return; }` and add:

```js
function renderMeCard(p) {
  const rec = state.edits[meCardId];
  if (!rec) { meCardId = null; renderPanel(); return; }
  let h = `<div class="dec-top"><span class="chip">TEXT EDIT</span>
    <span class="chip">${esc(meCardId)}</span></div>`;
  h += `<div class="loc">Deleted text</div>
    <div class="hint" style="font-style:normal;white-space:pre-wrap;text-decoration:line-through">${esc(rec.before) || "(nothing)"}</div>`;
  h += `<div class="loc">Inserted text</div>
    <div class="hint" style="font-style:normal;white-space:pre-wrap">${esc(rec.after) || "(nothing)"}</div>`;
  h += `<div class="notes-row"><input id="meNotes"
    placeholder="note for the audit log (optional)" value="${esc(rec.notes || "")}"></div>`;
  h += `<div class="navrow"><button class="danger" id="meRevert">Revert this change</button></div>`;
  h += `<div class="muted" style="margin-top:6px">All retyping happens in the
    document — turn Edit on and type. This card reviews one change.</div>`;
  p.innerHTML = h;
  document.getElementById("meNotes").onchange = ev => {
    rec.notes = ev.target.value.trim();
    save();
  };
  document.getElementById("meRevert").onclick = () => {
    delete state.edits[meCardId];
    meCardId = null;
    save(); buildDoc(); refresh();
  };
}
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_htmlpage.py tests/test_edit_core.py -q`
Expected: all pass (the updated hooks test, 4 new tests, all pre-existing ones)

- [ ] **Step 5: Sanity-build a real page**

Run: `python -m specgen html "masters/23 64 10.SEC" -o out/decisions-inline.html`
Expected: exits 0. (Full visual check happens in the Task 5 manual checklist.)

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: all pass

```bash
git add specgen/htmlpage.py tests/test_htmlpage.py
git commit -m "Inline edit-run rendering, review card; remove select-and-replace"
```

---

### Task 3: Edit mode engine — toggle, beforeinput, caret, hint, undo

**Files:**
- Modify: `specgen/htmlpage.py` (`_TEMPLATE`: header button, edit-mode JS block, hint CSS)
- Test: `tests/test_htmlpage.py` (add tests)

**Interfaces:**
- Consumes: `applyGapOp`, `gapRuns` (Task 1); `renderGap`, `gapAttrs`, `lockedOrigIn`, `editMode` (Task 2).
- Produces: `Edit: on/off` header toggle (`id="btnEdit"`), `beforeinput`-driven editing, `showHint(msg)`, session undo/redo.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_htmlpage.py`:

```python
def test_edit_mode_hooks_present(tmp_path):
    html = _page(tmp_path)
    assert 'id="btnEdit"' in html
    assert 'addEventListener("beforeinput"' in html
    assert "contenteditable" in html
    assert "spellcheck" in html
    assert "insertParagraph" in html      # Enter inserts a literal newline
    assert "insertFromPaste" in html      # paste is plain-text only
    assert "deleteByCut" in html
    assert "showHint" in html
    assert "editUndo" in html and "editRedo" in html


def test_edit_mode_forces_redline_view(tmp_path):
    html = _page(tmp_path)
    body = html.split('id="btnEdit"')[0]  # anywhere is fine; assert on JS
    assert 'state.view = "redline"' in html
    assert "btnView\").disabled = editMode" in html.replace("'", '"')


def test_edit_ops_check_locked_ranges(tmp_path):
    html = _page(tmp_path)
    body = html.split("function applyDocOp(")[1].split("\nfunction ")[0]
    assert "lockedOrigIn(" in body
    assert "blocked" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_htmlpage.py -q`
Expected: the 3 new tests FAIL

- [ ] **Step 3: Implement**

3a. **Header button** — in the HTML `<header>`, after the `btnNavToggle`
button, add:

```html
  <button id="btnEdit">Edit: off</button>
```

3b. **Hint CSS** — add to the `<style>` block:

```css
#editHint { position: fixed; bottom: 64px; left: 50%; transform: translateX(-50%);
  background: var(--ink); color: var(--bg); font-size: 12.5px; padding: 7px 14px;
  border-radius: 99px; opacity: 0; pointer-events: none; transition: opacity .2s;
  z-index: 20; }
#editHint.show { opacity: .92; }
```

3c. **Edit-mode block** — add after the review-card code (all new):

```js
// ---- edit mode (Word-like typing with live tracked changes) ----
let editUndo = [], editRedo = [];
let hintTimer = null;
function showHint(msg) {
  let el = document.getElementById("editHint");
  if (!el) {
    el = document.createElement("div");
    el.id = "editHint";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => el.classList.remove("show"), 1800);
}
function textLenNoAnchors(n) {
  if (n.nodeType === 3)
    return n.parentElement && n.parentElement.closest(".navanchor")
      ? 0 : n.textContent.length;
  if (n.classList && n.classList.contains("navanchor")) return 0;
  let sum = 0;
  for (const c of n.childNodes) sum += textLenNoAnchors(c);
  return sum;
}
function dispOffset(gapEl, node, off) {
  // display offset of (node, off) within the gap, skipping anchor content
  if (node.nodeType !== 3) {
    let sum = 0;
    const el = node;
    if (!gapEl.contains(el)) return null;
    for (let i = 0; i < off && i < el.childNodes.length; i++)
      sum += textLenNoAnchors(el.childNodes[i]);
    // add everything before `el` inside the gap
    let n2 = el;
    while (n2 !== gapEl) {
      let sib = n2.previousSibling;
      while (sib) { sum += textLenNoAnchors(sib); sib = sib.previousSibling; }
      n2 = n2.parentNode;
    }
    return sum;
  }
  if (node.parentElement.closest(".navanchor")) return null;
  let sum = off, n2 = node;
  while (n2 !== gapEl) {
    let sib = n2.previousSibling;
    while (sib) { sum += textLenNoAnchors(sib); sib = sib.previousSibling; }
    n2 = n2.parentNode;
    if (!n2) return null;
  }
  return sum;
}
function setCaretAt(gapEl, disp) {
  const walker = document.createTreeWalker(gapEl, NodeFilter.SHOW_TEXT);
  let n, pos = 0, last = null;
  while ((n = walker.nextNode())) {
    if (n.parentElement.closest(".navanchor")) continue;
    const len = n.textContent.length;
    if (disp <= pos + len) {
      const r = document.createRange();
      r.setStart(n, disp - pos);
      r.collapse(true);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      return;
    }
    pos += len;
    last = n;
  }
  if (last) {
    const r = document.createRange();
    r.setStart(last, last.textContent.length);
    r.collapse(true);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }
}
function selCtx() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const r = sel.getRangeAt(0);
  const gapEl = (r.startContainer.nodeType === 1 ? r.startContainer
    : r.startContainer.parentElement).closest(".gap");
  const gapEl2 = (r.endContainer.nodeType === 1 ? r.endContainer
    : r.endContainer.parentElement).closest(".gap");
  if (!gapEl || gapEl !== gapEl2) return null;
  const a = dispOffset(gapEl, r.startContainer, r.startOffset);
  const b = dispOffset(gapEl, r.endContainer, r.endOffset);
  if (a == null || b == null) return null;
  return { gap: gapEl, s: +gapEl.dataset.s, e: +gapEl.dataset.e,
           from: Math.min(a, b), to: Math.max(a, b) };
}
function editsIn(s, e) {
  const out = {};
  for (const [k, r] of Object.entries(state.edits))
    if (r.start >= s && r.end <= e) out[k] = r;
  return out;
}
function replaceEditsIn(s, e, recs) {
  for (const [k, r] of Object.entries(state.edits))
    if (r.start >= s && r.end <= e) delete state.edits[k];
  Object.assign(state.edits, recs);
}
function applyDocOp(ctx, op) {
  const before = editsIn(ctx.s, ctx.e);
  const res = applyGapOp(DATA.text, state.edits, ctx.s, ctx.e, op,
    lockedOrigIn(ctx.s, ctx.e));
  if (!res) return;
  if (res.blocked) {
    showHint("That text is locked — brackets are answered from the panel.");
    return;
  }
  replaceEditsIn(ctx.s, ctx.e, res.records);
  editUndo.push({ s: ctx.s, e: ctx.e, before,
    after: editsIn(ctx.s, ctx.e), caretBefore: ctx.from, caretAfter: res.caret });
  if (editUndo.length > 100) editUndo.shift();
  editRedo = [];
  save();
  renderGap(ctx.gap);
  setCaretAt(ctx.gap, res.caret);
  updateProgress();
}
function onBeforeInput(ev) {
  if (!editMode) return;
  ev.preventDefault();
  const ctx = selCtx();
  if (!ctx) {
    showHint("Edit one text region at a time — brackets are answered from the panel.");
    return;
  }
  const it = ev.inputType;
  let op = null;
  if (it === "insertText" || it === "insertParagraph" ||
      it === "insertLineBreak" || it === "insertFromPaste") {
    const text = it === "insertParagraph" || it === "insertLineBreak" ? "\n"
      : it === "insertFromPaste"
        ? ((ev.dataTransfer && ev.dataTransfer.getData("text/plain")) || "")
        : (ev.data || "");
    if (!text) return;
    op = ctx.from < ctx.to
      ? { kind: "replace", from: ctx.from, to: ctx.to, text }
      : { kind: "ins", at: ctx.from, text };
  } else if (it === "deleteContentBackward") {
    op = ctx.from < ctx.to ? { kind: "del", from: ctx.from, to: ctx.to }
                           : { kind: "bs", caret: ctx.from };
  } else if (it === "deleteContentForward") {
    op = ctx.from < ctx.to ? { kind: "del", from: ctx.from, to: ctx.to }
                           : { kind: "fwd", caret: ctx.from };
  } else if (it === "deleteByCut" || it === "deleteByDrag") {
    if (ctx.from < ctx.to) op = { kind: "del", from: ctx.from, to: ctx.to };
  }
  if (op) applyDocOp(ctx, op);
}
document.getElementById("doc").addEventListener("beforeinput", onBeforeInput);
document.addEventListener("keydown", ev => {
  if (!editMode || !(ev.ctrlKey || ev.metaKey)) return;
  const key = (ev.key || "").toLowerCase();
  if (key !== "z" && key !== "y") return;
  ev.preventDefault();
  const redo = key === "y" || (key === "z" && ev.shiftKey);
  const stack = redo ? editRedo : editUndo;
  const other = redo ? editUndo : editRedo;
  const step = stack.pop();
  if (!step) return;
  other.push(step);
  replaceEditsIn(step.s, step.e, redo ? step.after : step.before);
  save();
  const gapEl = document.querySelector(`.gap[data-s="${step.s}"]`);
  if (gapEl) {
    renderGap(gapEl);
    setCaretAt(gapEl, redo ? step.caretAfter : step.caretBefore);
  }
  updateProgress();
});
document.getElementById("btnEdit").onclick = () => {
  editMode = !editMode;
  if (editMode && state.view !== "redline") {
    state.view = "redline";
    document.getElementById("btnView").textContent = "Redline view: on";
    save();
  }
  document.getElementById("btnView").disabled = editMode;
  const b = document.getElementById("btnEdit");
  b.textContent = "Edit: " + (editMode ? "on" : "off");
  b.classList.toggle("primary", editMode);
  buildDoc();
};
```

3d. Clear the undo stacks wherever edits are bulk-replaced: in the
`fileImport` handler and the `btnClear` handler, add
`editUndo = []; editRedo = [];`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_htmlpage.py tests/test_edit_core.py -q`
Expected: all pass

- [ ] **Step 5: Full suite + rebuild sample page**

Run: `python -m pytest tests/ -q` then
`python -m specgen html "masters/23 64 10.SEC" -o out/decisions-inline.html`
Expected: all pass; exit 0

- [ ] **Step 6: Commit**

```bash
git add specgen/htmlpage.py tests/test_htmlpage.py
git commit -m "Edit mode: beforeinput engine, caret mapping, hint, session undo"
```

---

### Task 4: Decision-card "Edit text…", submittal-review freeform, unsafe copy fix

**Files:**
- Modify: `specgen/htmlpage.py` (`renderPanel` in `_TEMPLATE`)
- Test: `tests/test_htmlpage.py` (update + add), `tests/test_submittal_review.py` (add generate test)

**Interfaces:**
- Consumes: existing `freeform(d, e, ph)`, `setAnswer`, `generate`'s literal-answer path (`after = ans`, action `"custom text"`).
- Produces: `data-act="edittext"` button on every answerable decision card; freeform input on `submittal-review` cards; new unsafe-group copy.

- [ ] **Step 1: Write the failing tests**

Update the unsafe-copy assertion inside `test_manual_text_edit_hooks_present`
in `tests/test_htmlpage.py` — the old string is gone after this task, so move
it here as its own test:

```python
def test_unsafe_card_copy_points_to_si_editor(tmp_path):
    html = _page(tmp_path)
    assert (
        "This bracket crosses structural markup and can't be answered as a "
        "choice; it is flagged in the unresolved report for manual editing "
        "in SI Editor after generation."
    ) in html
    assert "edit it directly instead" not in html


def test_decision_card_has_edit_text_button(tmp_path):
    html = _page(tmp_path)
    assert 'data-act="edittext"' in html
    assert "Edit text…" in html
    # submittal-review card gains the freeform custom-text input
    sub = html.split('d.kind === "submittal-review"')[2]
    assert "freeform(d, e" in sub.split("} else if")[0]
```

(The `[2]` index: occurrence 0 is `resolvedText`, occurrence 1 is the
office-input wiring guard — verify with a quick search and adjust the index
so the sliced text is the `renderPanel` branch; the assertion goal is that
`freeform(` appears inside the submittal-review branch of `renderPanel`.)

Add to `tests/test_submittal_review.py`:

```python
def test_generate_applies_custom_text_on_submittal_review(tmp_path):
    # The decision page's freeform input stores literal text; generate must
    # apply it to a submittal-review group like any custom answer, with
    # working --revisions output.
    from specgen.generate import generate, resolve_revisions, revert_revisions
    from specgen import secfile
    from specgen.manifest import build_manifest

    src = (
        "<SEC><TXT>SD-03 Product Data; Chillers[; G[, ___]]</TXT></SEC>"
    )
    p = tmp_path / "s.SEC"
    p.write_bytes(src.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    subs = [d for d in m["decisions"] if d["kind"] == "submittal-review"]
    assert subs, "fixture must scan as a submittal-review decision"
    gid = subs[0]["id"]
    out = tmp_path / "out.sec"
    summary = generate(
        p, {}, {gid: {"answer": "; G, RO"}}, out, revisions=True
    )
    text = out.read_bytes().decode(secfile.ENCODING)
    assert "; G, RO" in text
    rev = (tmp_path / "out.revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert resolve_revisions(rev) == text
    assert revert_revisions(rev) == src
    assert summary["unresolved"] == 0
```

If the fixture does not scan as `submittal-review` (check
`specgen/scan.py`'s submittal-review detection for the exact required shape
— look at existing fixtures at the top of `tests/test_submittal_review.py`
and copy their source shape), reuse one of that file's existing fixture
strings instead; the assertion that matters is literal-text answer →
applied + revisions round-trip.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_htmlpage.py tests/test_submittal_review.py -q`
Expected: the new tests FAIL (the generate test may already PASS — generate
already supports custom text; if it passes, keep it as a regression pin and
note it in the commit message)

- [ ] **Step 3: Implement the card changes**

In `renderPanel` inside `_TEMPLATE`:

3a. Unsafe-group copy — replace the dupnote line:

```js
    h += `<div class="dupnote">This bracket crosses structural markup and can't be answered as a choice; it is flagged in the unresolved report for manual editing in SI Editor after generation.</div>` + navRow();
```

3b. In the `submittal-review` branch, after the office `freeform` row, add:

```js
    h += freeform(d, e, "…or type replacement text");
```

3c. After the `notes-row` line (`h += `<div class="notes-row">...`), insert
the Edit text button for every card that has a freeform input:

```js
  h += `<div class="navrow"><button data-act="edittext">Edit text… (start from the original)</button></div>`;
```

and wire it with the other handlers (next to the `data-act=apply` wiring):

```js
  const et = p.querySelector("[data-act=edittext]");
  if (et) et.onclick = () => {
    const ci = p.querySelector("[data-custom]");
    if (ci) {
      ci.value = DATA.text.slice(d.char_start, d.char_end);
      ci.focus();
    }
  };
```

The button label copy must be exactly `Edit text… (start from the original)`
so the static test's `"Edit text…"` assertion holds.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_htmlpage.py tests/test_submittal_review.py -q`
Expected: all pass

- [ ] **Step 5: Full suite + commit**

Run: `python -m pytest tests/ -q`
Expected: all pass

```bash
git add specgen/htmlpage.py tests/test_htmlpage.py tests/test_submittal_review.py
git commit -m "Decision-card Edit text prefill, submittal-review freeform, unsafe copy fix"
```

---

### Task 5: End-to-end fixture, corpus gate, docs, manual checklist

**Files:**
- Test: `tests/test_manual_edits.py` (add E2E test)
- Modify: `README.md` (workflow paragraph), `docs/superpowers/specs/2026-07-15-inline-edit-mode-design.md` (no change — reference only)
- Create: `docs/manual-browser-checklist.md`

**Interfaces:**
- Consumes: everything above; `generate` (unchanged).
- Produces: regression pin that inline-edit-shaped exports generate correctly.

- [ ] **Step 1: Write the failing (or pinning) E2E test**

Add to `tests/test_manual_edits.py`:

```python
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
```

**Watch out:** `_invalid_edit_reason` requires `0 <= start < end <= len`,
which REJECTS insertion-only records (`start == end`). If the second half of
this test fails with the record in the unresolved report, that is a real
gap between the new page format and generate: fix `_invalid_edit_reason` to
accept `start == end` when `before == ""`:

```python
    if not (0 <= start <= end <= len(stream)):
        return "manual edit start/end is out of range for this master"
    if start == end and str(edit.get("before", "")):
        return "zero-length manual edit carries deleted text"
```

and in the contiguity check, guard the empty range:

```python
    if end > start and offs[end - 1] - offs[start] != end - 1 - start:
        return "selection crosses structural markup"
```

This is the ONLY generate.py change permitted by this plan; it widens
validation to a shape the page now legitimately produces. Also check
`_edit_sort_key`/overlap logic treats `start == end` records correctly
(zero-width ranges only conflict when strictly inside an accepted span —
the existing `start < a_end and end > a_start` test already handles this).

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_manual_edits.py -q`
Expected: the first half passes as-is; the second half FAILS on the
insertion-only record until the `_invalid_edit_reason` fix is applied.

- [ ] **Step 3: Apply the insertion-only fix (if Step 2 failed) and re-run**

Run: `python -m pytest tests/test_manual_edits.py -q`
Expected: all pass

- [ ] **Step 4: Corpus regression gate**

Run: `python scripts/audit_corpus.py`
Expected: 55/55 audit + round-trip green (this exercises parsing only, but
it is the standing gate; run it every time htmlpage/generate change)

- [ ] **Step 5: Update README**

In `README.md`, in the answer-file workflow section, replace the sentence
fragment describing select-and-replace editing (if present) and append to
the item-1 paragraph:

```markdown
   The page also has an Edit mode: click Edit and type directly in the
   document like a tracked-changes Word doc — insertions show green,
   deletions show red strikethrough, and every change exports as an ME@
   record that `generate` applies and `--revisions` renders as native
   SpecsIntact ADD/DEL markup.
```

- [ ] **Step 6: Write the manual browser checklist**

Create `docs/manual-browser-checklist.md`:

```markdown
# Manual browser checklist — decision page

Build: `python -m specgen html "masters/23 64 10.SEC" -o out/decisions.html`
and open `out/decisions.html`. Run top to bottom; also covers the pending
Tasks 7/8 items (redline view, tailoring profile).

## Inline edit mode
- [ ] Click Edit → button reads "Edit: on", view forced to redline, view toggle disabled
- [ ] Click in plain text, type — characters appear green at the caret
- [ ] Backspace over original text — red strikethrough, caret hops left past it
- [ ] Backspace over green text you just typed — genuinely removed
- [ ] Forward Delete — strikethrough grows rightward
- [ ] Select a phrase, press a letter — phrase struck red, letter green after it
- [ ] Select a phrase, Ctrl+X — struck red (and on the clipboard)
- [ ] Paste rich text from Word/browser — inserts as plain green text
- [ ] Enter — inserts a literal newline (green)
- [ ] Ctrl+Z / Ctrl+Y — steps edits backward/forward, caret follows
- [ ] Try to type inside a yellow bracket mark — blocked, hint toast appears
- [ ] Try to select across a bracket mark and delete — blocked + hint
- [ ] Try to type inside a plural "[s]" or designer-note bracket — blocked + hint
- [ ] Progress footer shows "· N text edits"
- [ ] Toggle Edit off — document read-only again, edits still shown

## Review card
- [ ] Click any green/red run (view mode) — TEXT EDIT card with before/after
- [ ] Add an audit note — persists after reload (autosave)
- [ ] Revert this change — text restored, record gone
- [ ] In edit mode, clicking a run both places the caret and shows the card

## Decisions & custom text
- [ ] Click a bracket decision → answer via options — unchanged behavior
- [ ] "Edit text… (start from the original)" prefills the freeform input
- [ ] Saving freeform text shows <s>original</s><ins>custom</ins> redline
- [ ] Submittal-review card has the freeform input
- [ ] Unsafe (dashed red) decision card copy mentions SI Editor, not select-to-edit

## Round trip
- [ ] Export answers (JSON) → includes ME@ records
- [ ] Clear all → import the JSON → edits and answers all restored
- [ ] Hand-corrupt one ME@ "before" in the JSON, import → dropped with notice
- [ ] `python -m specgen generate "masters/23 64 10.SEC" --answers <export>.json -o out/generated/t.sec --revisions` → open the .revisions.sec in SpecsIntact: inline edits show as red/green tracked changes

## Pre-existing checks (Tasks 7/8 pass)
- [ ] Redline view toggle: clean view hides strikethroughs and shows chosen text
- [ ] Tailoring profile remove → blocks collapse to "▸ NAME removed" chips; keep restores
- [ ] Units SI/IP toggle strikes the unchosen halves in redline view
```

- [ ] **Step 7: Full suite, then commit**

Run: `python -m pytest tests/ -q && python scripts/audit_corpus.py`
Expected: all pass; 55/55

```bash
git add tests/test_manual_edits.py specgen/generate.py README.md docs/manual-browser-checklist.md
git commit -m "E2E inline-edit fixture, insertion-only edit support, docs + manual checklist"
```

---

## Self-Review Notes (already applied)

- Spec coverage: UX 1-2 → Task 3; UX 3 (locked islands + in-gap locked
  ranges) → Tasks 2+3; UX 4-5 (review card, select-and-replace removal) →
  Task 2; UX 6 (Edit text…, submittal freeform) → Task 4; UX 7 (forced
  redline) → Task 3; UX 8 (unsafe copy) → Task 4; run model + derivation →
  Task 1; undo/hint/caret → Task 3; import pruning parity → Task 2 (3e);
  insertion-only generate acceptance → Task 5; testing section → every task
  + Task 5 checklist.
- Known judgment call: insertion-only `ME@` records (`start == end`) are new
  to generate; Task 5 owns making generate accept them, and it is the only
  permitted generate.py change.
- Type consistency: record shape `{start,end,before,after,notes}` and the
  `ME@<start>` key are used identically in Tasks 1, 2, 3, 5; `applyGapOp`'s
  signature in Task 1 matches its call in Task 3's `applyDocOp`;
  `lockedOrigIn` is defined in Task 2 and consumed in Task 3.
```
