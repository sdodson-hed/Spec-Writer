# Structural Decisions Implementation Plan (work order step 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any `<SPT>` subsection be kept or removed as a decision, with the same safety guarantees as bracket decisions: anchored answers, verified output, `<DEL>` in the revisions file, and every outcome logged.

**Architecture:** The manifest gains a `subsections` list built from the PRT/SPT location index the anchors already use. Subsection answers travel in the same anchor-keyed answers file and go through the same `resolve_answer_keys`. In `generate`, every subsection marked for removal gets a temporary attribute on its open tag (`sg-rm="SPT-0012"`) before bracket resolution. The bracket, tailoring and units passes then edit the source as they do today, and the marker moves with the tag. After the units pass, the generator parses the edited source, removes each marked subsection's full element span (or wraps it in `<DEL>` in the revisions source), and strips every marker before verification. That is the spec's order ("after bracket resolution and tailoring, recomputing spans on the edited source") without having to map offsets through hundreds of splices.

**Tech Stack:** Python 3.10+, stdlib + openpyxl + lxml, pytest. Vanilla JS in `_TEMPLATE` (`specgen/htmlpage.py`). CI now runs the Node-backed JS tests, so new pure JS helpers get Node tests.

**Spec:** `docs/superpowers/specs/2026-10-13-design-data-annotations-design.md`, section 3 (structural decisions). Submittal and reference cleanup (also section 3) is work order step 4 and is not in this plan.

## Survey (WBDG UMRL July 2026, 431 masters, measured 2026-10-19)

| Measure | Count |
|---|---|
| `<SPT>` elements | 40,965 |
| inside a bracket group | 4,885 |
| ... wrapped exactly by a single optional bracket (`[<SPT>...</SPT>]`) | 2,735 |
| ... inside larger bracketed text | 2,150 |
| inside a `<TAI>` block (and not a bracket) | 2,071 |
| straddling a bracket group boundary | **0** |
| anchors needing `~n` (same path and title twice, e.g. tailoring alternates in 01 33 29) | 46 |
| sample removals (every 7th SPT, 6,043 cuts): output parses, round-trips, well-formed | 6,016 of 6,016 in masters that are well-formed as shipped |
| `sg-rm` appearing anywhere in a master | 0 |

4,885 + 2,071 = 6,956, matching the spec's figure for subsections that can already be removed. Because no subsection straddles a bracket boundary, removing a subsection's element span never leaves a stray `[` or `]`.

**Found during the survey (not this plan's scope):** `22 60 70.SEC` is not well-formed XML as shipped. A `<DTA>` header field contains a `\x13` control character. Tolerant parse and audit both pass it, but `generate`'s well-formedness check would reject any output for that section. This needs its own small fix: report it as a source defect in audit, and blank it out like stray tags in the well-formedness check.

## Decisions for review (answer before Task 2)

- **D1. Subsections wrapped exactly by an optional bracket (2,735).** Each one already has a bracket decision (`keep` / `delete`) that covers the same text. **Recommended:** the subsection row is an alias for that bracket decision (`governed_by: "BRK-0042"`). Toggling it in the page writes the bracket answer, an `spt` answer for it is translated to the bracket answer (`remove` to `delete`), and if both are answered and disagree the decision goes to `.unresolved.md` as a conflict and neither is applied. The alternative is two independent decisions where a bracket `delete` wins. That is simpler, but an engineer can then see "kept" on the outline while the text is gone.
- **D2. Logging default keeps.** The spec says unanswered subsections are kept and marked `source: default`. `.redline.json` gets one entry per default-kept subsection (23 64 10 has 104). `.redline.md` gets one summary line ("N subsections kept by default") rather than 104 lines.
- **D3. Workbook support.** The README promises xlsx and JSON are equivalent, and `scripts/maxwell_demo.py` uses the workbook. The plan adds a `Subsections` sheet (keep/remove dropdown, anchor column) so that stays true.

## Global constraints

- Byte-identical round-trip and the never-default rule are unchanged. The one sanctioned default is the spec's: an unanswered `spt` decision means keep, logged with `source: default`.
- A subsection inside a removed parent (or inside a bracket group answered `delete`, or a removed tailoring block) is gone with it. Any answer on it is ignored and logged, never an error.
- Markers never reach output. Verification fails if `sg-rm=` appears in the clean or revisions output.
- Revisions identities still hold: resolving revisions reproduces the clean output, reverting reproduces the master byte for byte.
- Bracket decision ids, anchors and counts do not change. Subsections are a separate manifest list, not new entries in `decisions`, so the workbook Answers sheet, the unanswered counter and existing answer files are unaffected.
- Environment and commands as in the steps 1 and 2 plan. Gate before every commit: `python -m pytest -q`, plus `scripts/audit_corpus.py` and the new corpus removal test with `SPECGEN_CORPUS` set. CI runs pytest (with Node) on the PR.
- Branch: `structural`, one PR into `main`.

---

### Task 1: Subsections in the manifest, with anchors

**Files:**
- Modify: `specgen/anchors.py` (`assign_spt_anchors`, `section_spt_anchors`)
- Modify: `specgen/manifest.py` (`subsections` list; `counts.subsections`)
- Test: `tests/test_subsections.py` (new)

**Interfaces:**
- `assign_spt_anchors(locs) -> dict[str, str]`: `SPT-NNNN` (document order over depth > 0 entries) to `<path>#spt:<hash8>[~n]`, where `path` is `group_path` at the subsection's own start (so it ends with its own title) and `hash8 = option_hash([norm_title(title)])`.
- Manifest `subsections[i]`: `{"id", "anchor", "num", "title", "depth", "parent", "src": [start, end], "span": [char_a, char_b], "governed_by": BRK id or null, "in_bracket": BRK id or null, "tailoring": OPT string or null}`. `span` indexes `manifest["text"]` like `tailoring_spans`.

- [ ] **Step 1: Write the failing tests** using a synthetic section with: two parts; a nested SPT; an SPT wrapped exactly by an optional bracket; an SPT inside larger bracketed text; an SPT inside `<TAI OPT="ARMY">`; two sibling SPTs with the same title. Assert ids, nums, anchor shapes (pinned hash for one title), `~2` on the repeat, `parent`, `governed_by` only on the exact wrap, `in_bracket` on the other, `tailoring` on the TAI one, `span` slicing `m["text"]` to the subsection text, and identical anchors for CRLF and LF copies. Add a corpus test (skips without `SPECGEN_CORPUS`) asserting unique anchors per section and the survey totals: 40,965 subsections, 2,735 `governed_by`.
- [ ] **Step 2: Run, expect FAIL** (`ImportError: assign_spt_anchors`).
- [ ] **Step 3: Implement.** `governed_by`: the innermost group containing the SPT is `optional`, has one option, and the source between the option bounds and the SPT element is whitespace only.
- [ ] **Step 4: Run tests, full suite, corpus. Commit** `Manifest: subsections with spt anchors`.

### Task 2: Subsection answers (JSON, workbook, resolver)

**Files:**
- Modify: `specgen/answers.py` (`read_answers_json` passes spt answers; `write_workbook` Subsections sheet; `read_workbook` reads it; `resolve_answer_keys` resolves spt anchors)
- Modify: `specgen/generate.py` (accept the resolved spt answers; nothing applied yet)
- Test: `tests/test_subsection_answers.py` (new)

**Interfaces:**
- Answer record: key = spt anchor, value `{"answer": "keep" | "remove", "id": "SPT-0012", "num": "2.6.7", "title": "..."}`. Any other answer value is rejected into `.unresolved.md` ("subsection answer must be keep or remove"), never guessed.
- `resolve_answer_keys(..., spt_anchors=...)` returns spt answers keyed `SPT-NNNN` in the same dict. Unresolved spt anchors become orphans with `options: [title]`.
- Governed subsections (D1): an spt answer on a governed subsection becomes the bracket answer (`remove` to `delete`, `keep` to `keep`) when the bracket is unanswered; same value is fine; different values produce a conflict entry in `.unresolved.md`, and the bracket answer is dropped (the bracket stays bracketed).

- [ ] **Step 1: Write the failing tests:** JSON round trip of spt answers; workbook Subsections sheet write/read (with and without the sheet, so old workbooks still load); resolver on April vs July style fixtures (spt anchor carried, spt orphan reported); governed translation, agreement, conflict; invalid answer value.
- [ ] **Step 2 to 4: Run (FAIL), implement, run suite and corpus. Commit** `Subsection answers: JSON, workbook, resolver`.

### Task 3: Removal in `generate` (clean output and redline)

**Files:**
- Modify: `specgen/generate.py`
- Test: `tests/test_structural_generate.py` (new)

**Order inside `generate`:**
1. Resolve answers (Task 2). Build `remove = {SPT ids answered remove, not governed}`. For each, if an ancestor is also in `remove`, drop it and log `ignored: inside removed SPT-x`.
2. Insert ` sg-rm="SPT-NNNN"` into the open tag of each subsection in `remove` (right after `<SPT`), in reverse offset order, before `rev = src` and before `scan_groups(src)`. All later offsets come from scanning the marked source, so brackets, manual edits and tailoring work unchanged.
3. Brackets, tailoring, units: unchanged.
4. Structural pass: parse the edited `src` (tolerant), collect `SPT` elements carrying `sg-rm`, keep outermost, splice out their spans in reverse order. Log each as `{"id", "kind": "subsection", "action": "removed subsection", "answer": "remove", "source": "answer", "num", "title", "before": first 200 chars}`.
5. Markers in `remove` that are no longer in the source were removed by a bracket `delete` or a tailoring removal: log `already removed (inside BRK-x / tailoring OPT)`.
6. Strip any remaining `sg-rm` attributes from `src` (none should remain in the clean output) and scrub them from redline `before`/`after` strings.
7. Rescan for unresolved (existing code). Brackets inside removed subsections no longer exist, so they drop out of `.unresolved.md` and are logged once per subsection as `N bracket decisions removed with SPT-x`.
8. Default keeps (D2): every subsection still present with no answer is logged `{"kind": "subsection", "action": "kept by default", "source": "default"}`; explicit keeps log `source: "answer"`. `.redline.md` gets the removed list plus one summary line for default keeps.
9. Verification (existing) plus: `"sg-rm=" not in src`.

- [ ] **Step 1: Write the failing tests:** remove a leaf; remove a parent whose child is answered (child ignored, logged); remove a subsection whose brackets were unanswered (not in `.unresolved.md`); remove a subsection inside a kept `<TAI>`; answer remove on a subsection inside a removed `<TAI>` (logged already removed); answer remove inside a bracket answered `delete`; a governed subsection answered remove (bracket deleted, logged once); unanswered subsections logged as default keeps; no `sg-rm` anywhere in outputs; summary gains `subsections_removed`, `subsections_kept_default`.
- [ ] **Step 2 to 4: Run (FAIL), implement, run suite and corpus. Commit** `generate: remove subsections after brackets and tailoring`.

### Task 4: Revisions output

**Files:**
- Modify: `specgen/generate.py`
- Test: extend `tests/test_structural_generate.py`

In the structural pass with `revisions=True`, parse `rev`, take marked `SPT` elements not inside a `<DEL>`, wrap each in `<DEL>...</DEL>` (outermost only), then strip markers from `rev`. The existing checks then prove `resolve_revisions(rev) == src` and `revert_revisions(rev) == master`.

- [ ] **Step 1: Write the failing tests:** removed subsection appears once inside `<DEL>` in `.revisions.sec`; nested removal wraps only the parent; subsection inside a bracket option that was deleted is not double-wrapped; both identities hold; no `sg-rm` in the revisions file.
- [ ] **Step 2 to 4: Run (FAIL), implement, run suite and corpus. Commit** `Revisions: removed subsections as <DEL>`.

### Task 5: Corpus removal gate

**Files:**
- Test: `tests/test_corpus_structural.py` (new, skips without `SPECGEN_CORPUS`)

For every master that is well-formed as shipped (today all but `22 60 70`, listed in a `KNOWN_MALFORMED` set with the reason), run `generate --revisions` with every 5th subsection answered `remove` and no other answers. `generate`'s own verification (parse, round-trip, well-formed, revisions identities, no markers) is the assertion. Also assert `subsections_removed` equals the number of answered subsections minus those nested inside another answered one.

- [ ] **Step 1: Write the test. Step 2: run against the WBDG corpus, fix anything it finds, record the time it takes. Commit** `Corpus gate: subsection removal on all masters`.

### Task 6: Decision page (outline rows, document view, export/import)

**Files:**
- Modify: `specgen/htmlpage.py`
- Test: `tests/test_htmlpage.py` (template hooks), `tests/test_subsection_js.py` (new, Node-backed pure JS)

Behavior:
- Each outline row in the Sections panel gets keep/remove buttons. Unanswered rows read "kept by default" in muted text; removed rows are struck through and their children dimmed.
- The document shows a removed subsection collapsed and struck, with the same pattern as removed tailoring (`▸ 2.6.7 COMPRESSOR DRIVER, GAS-ENGINE: 214 lines removed`). It expands on click.
- Bracket decisions inside a removed subsection leave the unanswered counter, the "next unanswered" walk and the export gate. This mirrors `inRemovedTai`.
- Governed rows (D1) read and write their bracket decision's answer.
- Export writes spt answers keyed by anchor with `id`, `num`, `title`. Import maps them back and counts orphans in the existing alert.
- Pure helpers for Node tests: `removedSubsections(subsections, answers, bracketAnswers) -> Set<id>` (applies parent removal and governed aliases) and `insideRemoved(span, removedSpans) -> bool`.

- [ ] **Step 1: Write the failing tests** (template hooks plus the Node tests for both helpers).
- [ ] **Step 2 to 4: Run (FAIL), implement, run suite. Manual check in the browser through the local HTTP server: remove 2.6.7 on 23 64 10, confirm the counter drops by the brackets it contains, export, clear, import, confirm the removal returns. Commit** `Decision page: subsection keep/remove`.

### Task 7: Maxwell check, docs, PR

- [ ] Run 23 64 10 with the existing 8 Maxwell answers plus the spec table's "Rule" subsection removals answered by hand: 2.4.2 Centrifugal, 2.5 Split-System Water Chillers, 2.6.5.2 Rotary Screw, 2.6.5.3 Centrifugal compressors, 2.6.7 Gas-Engine driver, 2.6.11 Water-Cooled Condenser Coil, 2.10.3 Cooling Tower. Report unresolved before (102) and after, and confirm with `git diff --no-index` on the outputs that nothing outside those subsections changed.
- [ ] Open the `.revisions.sec` and confirm the `<DEL>` blocks sit where expected. Flag for Sam: the real SpecsIntact check of tracked deletions is a manual step on the AFCEC-required version.
- [ ] README: subsection decisions, workbook sheet, page behavior, redline fields.
- [ ] PR description with the corpus line, the corpus removal gate result, test counts, and the Maxwell before/after.

## Not in this plan

- Step 4: dropping submittal items and references whose only uses were in removed subsections. Until then a removed subsection can leave a now-unused submittal item or reference, which SpecsIntact's submittal and reference verification would report.
- Annotation rules that answer subsections from design data (step 5).
- The `22 60 70` control-character defect (separate fix, see Survey).
