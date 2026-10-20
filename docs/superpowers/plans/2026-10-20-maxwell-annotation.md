# Maxwell Annotation Implementation Plan (work order step 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write `annotations/23 64 10.yaml` and prove, end to end, that `prefill` followed by `generate` gives Maxwell 23 64 10 the outcome in the spec's acceptance table. The 7 subsection removals that `scripts/maxwell_demo.py` hand-codes today then come from the ACC-1 schedule.

**Spec:** `docs/superpowers/specs/2026-10-13-design-data-annotations-design.md`, "Maxwell expected outcome (23 64 10, ACC-1)".

## Findings (23 64 10, measured 2026-10-20)

**The spec's "fill the schedule blanks" row cannot be met as written.** The table expects "Refrigerant, capacity, EER, OAT, electrical blanks: Filled (Rule: schedule fields)". 23 64 10 has no such blanks. Its Part 1 note says chiller performance data "must be shown in the equipment schedule on the drawings". Part 2 has only two kinds of fill-in blank: a muffler dBA value inside 2.6.7 Gas-Engine, and low-ambient temperatures inside 2.5 Split-System. Both subsections are removed for Maxwell. The schedule data drives choices and removals in this section, not fills.

**The schedule does answer three choices:**

| Decision | Options | From |
|---|---|---|
| BRK-0023 (2.4.1 title) | Scroll / Reciprocating / Rotary Screw | `compressor_type` |
| BRK-0025 (2.4.1 component list) | electric motor / gas-engine | derived `driver` (every type this section schedules is electric) |
| BRK-0026 (2.4.1 component list) | Air-cooled condenser coil / Water-cooled condenser | derived from `type` |

**Subsection rules ("Rule" rows of the table, plus their keep-side twins):**

| Target | Rule |
|---|---|
| 2.4.2 Centrifugal Type | remove unless any row's `compressor_type` is CENTRIFUGAL |
| 2.5 Split-System (with all children) | remove unless any row is a split system (derived `arrangement` from `type`) |
| 2.6.5.1 Scroll / 2.6.5.2 Rotary Screw / 2.6.5.3 Centrifugal compressors | each removed unless a row has that compressor type |
| 2.6.6 Electric Motor / 2.6.7 Gas-Engine drivers | each removed unless a row has that driver |
| 2.6.10 Air-Cooled / 2.6.11 Water-Cooled condenser coil | each removed unless a row has that condenser |
| 2.10.3 Cooling Tower | remove unless a row is water-cooled |
| 2.6.12 Heat Recovery Condenser Coil | remove unless `bod.heat_recovery`; requires `bod.heat_recovery`, so it stays unresolved for Maxwell |

2.6.13 Receivers has no rule ("Needs engineer" in the table).

## Decisions for review

- **D1. The spec's "Confirm" rows.** The table removes three more items, but says each "needs an engineer to sign off on the rule before it goes in the annotation":
  - 2.4.3 to 2.4.7, the heat pump, heater-chiller and multipipe types: proposed rule is remove unless the derived `function` is not cooling-only.
  - 2.6.14 Chiller Purge System: proposed rule is remove unless a row is centrifugal, since purge applies to low-pressure centrifugal machines.
  - 2.7.4 Automatic Tube Brush Cleaning: proposed rule is remove unless a row is water-cooled. This subsection is governed by BRK-0119, so the answer goes to that bracket.

  **Options:** (a) you sign off now and the rules go in; (b) they stay out, so those subsections remain kept by default and are listed for review. **Recommended:** (b) until someone with engineering authority signs off. Those subsections are kept by default either way, so nothing is removed on assumption.
- **D2. The spec table's fill row.** **Recommended:** add a dated note under the spec's Maxwell table recording the finding above, and leave the table itself unchanged. The acceptance test asserts the corrected expectation: no fills in 23 64 10, and the schedule values drive the three choices instead.
- **D3. The demo.** **Recommended:** `scripts/maxwell_demo.py` becomes `prefill` plus `generate` on the new annotation, so the hand-coded answers and the annotation can't drift apart. The old demo's 8 hand-picked bracket answers include low-ambient and minimum-load values that no schedule field supports. Those return to unresolved, which is the honest state for them.

## Tasks

### Task 1: `annotations/23 64 10.yaml`

- [ ] Write the annotation from the findings tables: `derive` for `driver`, `condenser`, `condenser_component`, `arrangement` and `function`, mapped from `type`. A type missing from a map stays unknown, never defaulted. Include the D1 rules only if D1 is (a).
- [ ] `python -m specgen annotate-check "masters/23 64 10.SEC" --annotation "annotations/23 64 10.yaml"` must exit 0, with every rule resolving to exactly one target.
- [ ] Commit `Annotation: 23 64 10 from the chiller schedule`.

### Task 2: Maxwell acceptance test

- [ ] Write `tests/test_maxwell.py`, tests first. It runs `prefill` with `projects/maxwell/design-data.json` and the annotation, then `generate --strict --revisions` on `masters/23 64 10.SEC`, and asserts the spec table row by row:
  - 2.4.1 Scroll; 2.4.2 removed; 2.5 removed with all children; 2.6.5.2 and 2.6.5.3 removed; 2.6.7 removed with its 10 children; 2.6.11 removed; 2.10.3 removed.
  - 2.6.12 listed in `.unresolved.md` with "needs bod.heat_recovery".
  - 2.6.13 kept by default.
  - ARMY and NAVY tailoring removed, AIR FORCE kept.
  - The D1 rows, as decided.
  - No fills (D2).
  - Cleanup: 2 submittal items and 12 references removed (the step 4 numbers).
- [ ] Report the unresolved count before (102, the old demo) and after.
- [ ] Commit `Maxwell acceptance: prefill + generate meet the spec table`.

### Task 3: Demo, spec note, README, PR

- [ ] Rewrite `scripts/maxwell_demo.py` (D3) and add the spec note (D2).
- [ ] README: replace the hand-coded demo paragraph.
- [ ] PR description with the corpus line, test counts, the table-by-table result, the unresolved count before and after, and the D1/D2 notes.
