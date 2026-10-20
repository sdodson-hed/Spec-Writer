# Removal Cleanup Implementation Plan (work order step 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When subsections are removed, also drop the submittal items and reference entries whose only body uses were inside the removed content, and drop section cross-references that no longer appear. Without this, SpecsIntact's submittal and reference verification flags every leftover.

**Architecture:** A new `specgen/cleanup.py` computes the cleanup in master coordinates, from the parsed master and the removed subsections' spans. It is a pure function and the generator's only new dependency. `generate` puts a tracking marker on each element to clean up, using the same approach as subsections. After the structural pass removes the subsections, it removes the marked entries from the edited source (`<DEL>` in the revisions output), logs every one, and strips the markers before verification. Anything already gone through a bracket or tailoring removal is logged as such.

**Spec:** `docs/superpowers/specs/2026-10-13-design-data-annotations-design.md`, section 3, the cleanup bullets.

## Survey (WBDG UMRL July 2026, measured 2026-10-20)

Maxwell 23 64 10 with the 7 rule removals from step 3 orphans:
- 2 of 25 submittal items: Centrifugal Type Water Chiller[s] and Split-System Water Chiller[S]. Neither is bracketed or carries a G code.
- 12 of 26 references: AHRI 450, 460 and 480; ABMA 9 and 11; ASHRAE 90.1 IP and SI; ASTM A53/A53M; NFPA 37 and 54; SAE J537; UL 1236.
- 2 section cross-references: 22 00 00 and 23 65 00.

Corpus, removing every 5th non-governed subsection in all 431 masters:

| Measure | Count |
|---|---|
| submittal items | 8,523 |
| ... with a body `<SUB>` use matched by normalized name | 8,455 (99.2%) |
| ... orphaned by the removals | 2,604 |
| ... orphaned and inside a bracket group | 188 |
| ... orphaned and carrying a G/S reviewer code | 1,759 |
| declared references | 12,759 |
| ... used in the body | 12,758 |
| ... orphaned by the removals (Task 2 planner) | 622 single entries plus 100 whole organization blocks |
| ... orphaned and inside a bracket group | 0 |
| SD headings emptied | 278 |
| section cross-references dropped entirely | 563 |

The first draft of this table said 3,969 references. The survey script behind that number also counted references declared inside a removed REFERENCES subsection. Those go with the subsection, so cleanup never acts on them. The planner's count is the right one.

A submittal item is matched to its body uses by the normalized text of its first `<SUB>`: whitespace collapsed, case-insensitive. A reference is matched by its `<RID>` text. The 68 items with no body use in the master are never touched, because cleanup only acts on items that had uses and lost all of them.

## Decisions for review (answer before Task 2)

- **D1. Orphaned items inside a bracket group (188 in the survey).** **Recommended:** leave them in place. If the bracket is unanswered, report it in `.unresolved.md` with a note ("its only references were removed with SPT-x; consider delete"). If it was answered `keep`, log that it was kept by answer. That keeps the never-default rule strict, because no bracket decision gets made by inference. The alternative is to delete the whole bracket group automatically. That is tidier, but it answers a decision the engineer never saw.
- **D2. Empty containers.** When cleanup empties an SD heading (`<LST><SUB>SD-06 Test Reports</SUB></LST>` with no items left) or a reference organization block (`<REF><ORG>NFPA</ORG>` with no entries left), **remove the heading or block too**, and log it. Leaving them would show empty headings in SpecsIntact.
- **D3. Scope.** Cleanup reacts only to subsections removed by step 3 decisions. Content removed by bracket answers or tailoring is unchanged from today, so its submittal items are still the engineer's call. This matches the spec's wording ("inside removed content", in the structural-decisions section) and keeps the step reviewable. Extending cleanup to tailoring and bracket removals can be a later change.

## Global constraints

- Byte-identical round-trip and the never-default rule are unchanged. Cleanup never answers a bracket decision (D1).
- Every cleanup action is logged in `.redline.json` (`kind`: `submittal-item`, `reference`, `sd-heading`, `reference-org`) with the subsection or subsections that caused it. Removed items with a reviewer code also log that code.
- Markers never reach output. The existing "no marker" check grows to cover the new attribute.
- Revisions identities hold: resolving the revisions reproduces the clean output, and reverting reproduces the master.
- Same environment, gates and commit trailer as steps 1 to 3. Branch `cleanup`, one PR.

---

### Task 1: Manifest data for cleanup

**Files:**
- Modify: `specgen/manifest.py` (additive fields)
- Test: `tests/test_cleanup_manifest.py` (new)

The existing `submittals` entries gain `src` (the `<ITM>` span), `uses` (source spans of the body `<SUB>` matches), `reviewer` (the G/S code text or `null`) and `in_bracket`. `references` entries gain `src` (the declared `<RID>` span), `uses` and `org`. A new top-level `section_refs` maps each `<SRF>` number to its source spans.

- [ ] Tests first, on a synthetic section with: two SD groups; an item used once in the body; an item used twice; an item never used; an item with `; <SUB>G</SUB>`; a bracketed item; two references under one organization and one under another; and two `<SRF>` cross-references. Then implement, run the suite and corpus, and commit `Manifest: submittal, reference and section-ref uses`.

### Task 2: `specgen/cleanup.py`

**Interfaces:**

```python
def plan_cleanup(sec, manifest, removed: dict[str, tuple[int, int]]) -> dict:
    """removed: SPT id -> master source span of each removed subsection
    (outermost). Returns {"remove": [action], "blocked": [action],
    "section_refs_dropped": [num]}; each action is {"kind", "name", "src":
    [start, end] in master coords, "caused_by": [SPT ids], "reviewer"?}."""
```

Rules:
- An item or reference is orphaned when it had at least one use and every use sits inside a removed span. One that is itself inside a removed span is not orphaned: it goes with that span.
- The removal span is the element plus the run of `<BRK/>` and whitespace after it, up to the next element. That keeps the list spacing intact.
- An orphan inside a bracket group is `blocked` (D1).
- After the items are decided, an SD heading whose items were all removed or blocked-and-removed is removed. That is computed per heading, in document order up to the next heading. A `<REF>` whose entries are all removed is removed whole, replacing the entry actions (D2).

- [ ] Tests first: each rule above, including an item used once inside and once outside a removed subsection (kept), an item inside a removed subsection (not an action), the bracketed orphan (blocked), the emptied SD heading, the emptied organization, and the dropped section references. Implement, then commit `cleanup: plan submittal, reference and heading removals`.

### Task 3: Apply cleanup in `generate` (and revisions)

- [ ] In `generate`, after the answers resolve, compute the cleanup from the removal set and the manifest. Mark each action's element with `sg-cln="N"` (on the `<ITM>`, `<RID>`, `<LST>` or `<REF>` open tag) alongside the subsection markers.
- [ ] In the structural pass, after the subsections are removed, remove the marked spans that are still present (outermost first; extend each by its trailing `<BRK/>`/whitespace in the edited source) and wrap them in `<DEL>` in the revisions source.
- [ ] Log each removal, each "already removed with BRK/tailoring", and each blocked item. Blocked items go into `.unresolved.md` with the D1 note.
- [ ] The summary gains `submittal_items_removed`, `references_removed` and `section_refs_dropped`. `.redline.md` gets a Cleanup section.
- [ ] Strip `sg-cln` together with `sg-spt`, and extend the marker check.
- [ ] Tests first (`tests/test_cleanup_generate.py`): Maxwell-shaped synthetic section, revisions identities, a blocked item reported and untouched, an item inside removed tailoring, and no markers in any output. Commit `generate: remove orphaned submittals and references`.

### Task 4: Corpus gate

- [ ] Extend `tests/test_corpus_structural.py`. For each master and its every-5th removal, recount in the generated output, independently of generate's log: every submittal item and declared reference that had a body use in the master either still has one in the output, or is listed as blocked. No item or reference with zero remaining uses survives unless it had none in the master. Run on the WBDG corpus. Commit `Corpus gate: cleanup leaves no orphaned submittals or references`.

### Task 5: Decision page preview

- [ ] When subsections are removed on the page, strike the submittal items and reference entries that generate would drop, with a tooltip naming the subsection that caused it. Mark blocked items with an amber note instead. Add a pure helper `orphansAfter(items, removedSpans)` to `STRUCT_CORE_JS`, with Node tests, and run the same assertions in the browser. Browser check on 23 64 10: remove the 7 Maxwell subsections and confirm the 2 items and 12 references are struck. Commit `Decision page: preview cleanup`.

### Task 6: Maxwell, docs, PR

- [ ] Rerun the Maxwell demo. Report the counts (expected: 2 items, 12 references, 2 section references), and confirm the new output equals the step 3 output with exactly those entries, their trailing spacing, and any emptied headings or organization blocks removed.
- [ ] README: the cleanup paragraph.
- [ ] PR description with the corpus line, the cleanup gate result, test counts and the Maxwell numbers. Flag for Sam: run SpecsIntact's submittal and reference verification on the Maxwell revisions output (manual).

## Not in this plan

- Cleanup after tailoring or bracket removals (D3).
- Annotation rules and design data (step 5).
- The `22 60 70` control-character defect (queued separately).
