# Design data, structural decisions and stable anchors: design

**Date:** 2026-10-13
**Status:** Draft for team review
**Scope:** specgen scanner and manifest, generator, answers format, new annotation layer, Maxwell pilot.
**Builds on:** 2026-07-14 decision-completeness design (keeps its answers JSON compatible; this is the "annotation layer / design-data pre-fill" listed there as a non-goal).

## Problem

A review on 2026-10-13 ran specgen against 431 current UFGS masters (Divisions 01, 03, 05, 07, 08, 09, 21, 22, 23, 26, 28, 31, 33; WBDG release with UMRL July 2026). The parser and audit hold up: 430 of 431 round-trip byte-identically and audit clean. Six gaps block the goal of design data in, tailored UFGS section out.

1. **Subsections can't be removed.** The generator removes only bracketed text and `<TAI>` blocks. Of 40,963 `<SPT>` elements in the 431 masters, 6,956 (17%) sit inside a bracket group or `<TAI>`. The other 34,007 can only be removed by hand. The Maxwell run (air-cooled scroll) still contains 2.4.2 Centrifugal, 2.6.7 Compressor Driver, Gas-Engine (10 children), 2.6.11 Water-Cooled Condenser Coil and 2.5.5 Remote Water-Cooled Condenser.
2. **Answers are per bracket.** One design fact ("scroll") should resolve many brackets and remove many subsections. The Maxwell demo hand-codes 8 answers and leaves 102 unresolved.
3. **Positional IDs break on quarterly releases.** `BRK-NNNN` is assigned in document order and the fingerprint gate rejects stale answers. Between the repo copy (UMRL April 2026) and WBDG (UMRL July 2026), 03 30 00 changed the text of 8 of 244 groups, but IDs shifted for 135 and every saved answer is rejected. 236 of 244 groups have identical text in both releases.
4. **Line endings.** Repo masters are LF; WBDG ships CRLF. 23 64 10 has no content change between the two, but the fingerprints differ.
5. **01 42 00 fails to parse.** UFGS ships `<URL HREF="https://standard.no/en"/>http://www.nsf.org</URL>` in the NORSOK entry (self-closing tag, then a stray close tag; the visible URL is also wrong). 01 42 00 is required for SpecsIntact address verification.
6. **No acceptance run on generator output.** The SGTEST QA reports in `masters/` came from `scripts/sgtest_edit.py`, not from `generate`.

## Goals

1. Any subsection can be kept or removed as a decision, with the same safety guarantees as bracket decisions.
2. Decision IDs survive quarterly UFGS releases when the decision's text and location are unchanged.
3. A section annotation maps design-data fields (equipment schedules, BOD, project attributes) to decisions. Applying it is deterministic.
4. Every resolved decision records where its answer came from, so the decision page can color-code by source and detect conflicts.
5. Unanswerable decisions stay unresolved with a reason naming the missing field. Nothing is defaulted.

## Non-goals

- Project-level layer (section selection from scope, cross-section reference checks, 01 33 00 register). Next design.
- Live sync with the Hedral platform. This design defines the design-data file the platform will later write.
- Code-compliance checks on design data (for example, schedule EER against ASHRAE 90.1). Noted under future work.

## Design

### 1. Hygiene (do first)

- Add `.gitattributes` with `*.SEC -text` and `*.sec -text` so git never rewrites line endings. Re-copy the four masters from the shared drive after the change.
- Fingerprint on normalized option text (collapse whitespace, normalize CRLF to LF) so line endings alone never change it. The byte-identical round-trip check stays on raw bytes.
- Tolerant parse mode: a close tag that matches nothing on the stack becomes a `Misc` node holding its raw text. Round-trip stays byte-identical. `audit` reports it as a source defect, not a pass. Default stays strict; the corpus script and `generate` use tolerant mode.
- `scripts/audit_corpus.py` takes a corpus directory argument (or `SPECGEN_CORPUS` env var) so it can run against a full WBDG release, not only `masters/Specifications`.

### 2. Stable anchors

Every decision (bracket group or subsection) gets an anchor in addition to its positional ID:

```
anchor = <path>#<kind>:<hash8>[~<n>]
```

- `path` is the chain of PRT/SPT titles from the root, each normalized (uppercase, collapse whitespace, strip bracket characters but keep their contents), joined with `/`. Example: `PART 2/SELF-CONTAINED WATER CHILLERS, VAPOR COMPRESSION TYPE/SCROLLRECIPROCATINGROTARY SCREW TYPE WATER CHILLERS`.
- `kind` is `choice`, `blank`, `optional`, `submittal-review`, `plural` or `spt`.
- `hash8` is the first 8 hex characters of SHA-1 over the normalized option texts joined with `\x1f`. For `spt`, it hashes the normalized title only.
- `~n` is added only when the same path, kind and hash occur more than once, numbered in document order from 2.

Answers files key on anchors. `BRK-NNNN` stays in the manifest and HTML for display. Loading an answers file:

1. Every anchor that resolves to exactly one decision in the current master applies.
2. Anchors that don't resolve go to `.unresolved.md` as "master changed: decision not found", with the old option text shown.
3. The fingerprint gate becomes a warning listing the count from step 2, not a hard stop. `--strict` restores the hard stop.

Acceptance: answers recorded against the April 2026 03 30 00 apply to the July 2026 copy with at least 236 of 244 decisions carried over and the rest reported.

Old answers files keyed on `BRK-NNNN` still load when their fingerprint matches; the loader converts them to anchors on read.

### 3. Structural decisions

- The manifest lists every `<SPT>` as a decision of kind `spt` with options `keep` and `remove`, its anchor, title, numbered location and source span. They appear in the decision page as collapsible outline rows, not in the bracket list.
- `remove` deletes the element's full source span. A removed parent removes its children; answers on children inside a removed parent are ignored and logged.
- `generate` applies structural removals after bracket resolution and tailoring, recomputing spans on the edited source (same pattern as tailoring today).
- Revisions output wraps removed subsections in `<DEL>` so SpecsIntact shows them as tracked deletions.
- Cleanup after removal, each logged in `.redline.json`:
  - Submittal items in the submittal article whose only body references were inside removed content are removed. If a removed item has a reviewer code, log it.
  - References in the reference article whose only body uses were inside removed content are removed.
  - Section references (other sections cited) inside removed content are dropped from the section's outbound reference list in the manifest.
- An `spt` decision with no answer means keep. This is the one place the absence of an answer has a meaning, because UFGS masters are written as "everything present until removed". The decision page shows unanswered `spt` rows as "kept by default", and the redline marks them `source: default` so a reviewer can tell them apart from deliberate keeps.

### 4. Design data file

One JSON file per project, written by an engineer today and by the Hedral platform later. Field names come from the schedules, lowercased with underscores.

```json
{
  "schema": "specgen.design-data/1",
  "project": { "name": "Maxwell AFB", "agency": "AIR FORCE", "units": "IP" },
  "sources": {
    "acc-sched-35": { "kind": "schedule", "title": "Air Cooled Chiller Schedule", "phase": "35%", "date": "2026-10-13" }
  },
  "equipment": [
    {
      "mark": "ACC-1", "schedule": "air_cooled_chiller", "source": "acc-sched-35",
      "type": "AIR-COOLED SCROLL", "nominal_tonnage": 100, "capacity_mbh": 1123.1,
      "eer": 9.98, "outside_air_temp_f": 95, "refrigerant": "R-454B",
      "refrigerant_circuits": 2, "compressor_type": "SCROLL", "compressor_qty": 4,
      "condenser_fan_qty": 8, "weight_lbs": 10136, "volts": 208, "phase": 3,
      "hz": 60, "mca": 474, "mop": 600, "sccr": 65000
    }
  ],
  "bod": {}
}
```

`bod` holds basis-of-design fields that aren't on a schedule (heat recovery, sound limits, BAS protocol and so on). It starts empty for Maxwell on purpose: those decisions must stay unresolved until someone fills them in.

### 5. Section annotation

One YAML file per section in `annotations/`, for example `annotations/23 64 10.yaml`. An annotation never contains spec text; it points at decisions by anchor pattern and says how design data answers them.

```yaml
section: "23 64 10"
applies_to:
  schedule: air_cooled_chiller        # equipment rows this section covers

derive:                               # named facts computed once per equipment row
  condenser:
    from: type
    map: { "AIR-COOLED SCROLL": air-cooled, "AIR-COOLED SCREW": air-cooled,
           "WATER-COOLED SCROLL": water-cooled, "WATER-COOLED CENTRIFUGAL": water-cooled }
  driver: { value: electric }         # every type this section schedules is electric

rules:
  - id: compressor-type
    target: { path: "PART 2/SELF-CONTAINED WATER CHILLER*/*TYPE WATER CHILLER*", kind: choice,
              options: [Scroll, Reciprocating, Rotary Screw] }
    choose: { match: "{compressor_type}" }   # case-insensitive match on option text

  - id: no-centrifugal-chiller
    target: { path: "PART 2/SELF-CONTAINED WATER CHILLER*/CENTRIFUGAL TYPE WATER CHILLER*", kind: spt }
    remove_unless: { any_equipment: { compressor_type: CENTRIFUGAL } }

  - id: no-gas-engine
    target: { path: "PART 2/CHILLER COMPONENTS/COMPRESSOR DRIVER, GAS-ENGINE", kind: spt }
    remove_unless: { any_equipment: { driver: gas-engine } }

  - id: refrigerant
    target: { path: "PART 2/CHILLER COMPONENTS/REFRIGERANT", kind: blank, nth: 1 }
    fill: "{refrigerant}"

  - id: heat-recovery
    target: { path: "PART 2/CHILLER COMPONENTS/HEAT RECOVERY CONDENSER COIL", kind: spt }
    remove_unless: { bod: { heat_recovery: true } }
    requires: [ bod.heat_recovery ]     # missing field leaves the decision unresolved
```

Rules for rule evaluation:

- **No expression strings, no `eval`.** Conditions are structured: `equals`, `in`, `any_equipment`, `all_equipment`, `bod`, `project`, combined with `all` / `any` / `not`.
- **Multiple equipment rows.** `remove_unless: any_equipment` removes content only when no row in `applies_to` needs it. Choices and fills that differ across rows are not resolved; they go to unresolved with "equipment rows disagree: ACC-1=X, ACC-2=Y" so the engineer can split the section or write a combined value.
- **Targets must resolve.** A rule whose target matches zero decisions, or more than one without `nth`, fails the annotation check (`python -m specgen annotate-check`). This catches annotations broken by a UFGS release before they write a wrong spec.
- **Missing data stays unresolved.** If a field a rule needs is absent, the decision is unresolved with the field name, never defaulted.
- **Order.** Structural rules apply first, then choices and fills; rules targeting decisions inside removed subsections are skipped and logged.

New command:

```
python -m specgen prefill "masters/23 64 10.SEC" \
    --design-data projects/maxwell/design-data.json \
    --annotation "annotations/23 64 10.yaml" \
    -o out/maxwell/23_64_10.answers.json
```

It writes a normal answers JSON (anchor-keyed) that `generate` and the HTML page already know how to load. Engineers review and override in the page, then generate.

### 6. Provenance

Each answer record gains two fields:

```json
"PART 2/.../#choice:3fa91c02": {
  "answer": "1",
  "source": { "kind": "schedule", "ref": "ACC-1.compressor_type", "rule": "compressor-type",
              "data_source": "acc-sched-35", "value": "SCROLL" },
  "state": "auto",
  "notes": ""
}
```

- `source.kind`: `rule` (project attributes), `schedule`, `bod`, `manual`, `ai`, `default` (unanswered `spt` keeps).
- `state`: `auto`, `overridden`, `conflict`.
- An engineer editing an `auto` answer sets `state: overridden` and keeps the original `source` and `value` under `source.was`.
- `prefill` re-run over an answers file: `auto` answers update; `overridden` answers are never changed, but if the rule's new value differs from `source.was.value`, the state becomes `conflict` and both values are shown.
- The decision page colors by `source.kind` and `state`, using the provenance palette from the 2026-10-13 product discussion. The issued `.sec` carries no provenance; `.redline.json` does.

## Maxwell expected outcome (23 64 10, ACC-1)

This is the acceptance target for the pilot. "Rule" rows are deterministic from the schedule. "Confirm" rows need an engineer to sign off on the rule before it goes in the annotation.

| Content | Expected | Basis |
|---|---|---|
| 2.4.1 compressor choice | Scroll | Rule: compressor_type |
| 2.4.2 Centrifugal Type | Removed | Rule |
| 2.4.3 to 2.4.7 heat pump, heater-chiller, multipipe | Removed | Confirm: schedule type is a cooling-only chiller |
| 2.5 Split-System Water Chillers (all) | Removed | Rule: packaged air-cooled unit |
| 2.6.5.2 Rotary Screw, 2.6.5.3 Centrifugal Compressors | Removed | Rule |
| 2.6.7 Gas-Engine driver (and 10 children) | Removed | Rule |
| 2.6.11 Water-Cooled Condenser Coil | Removed | Rule: condenser = air-cooled |
| 2.6.12 Heat Recovery Condenser Coil | Unresolved | Needs bod.heat_recovery |
| 2.6.13 Receivers | Unresolved | Needs engineer |
| 2.6.14 Chiller Purge System | Removed | Confirm: purge applies to low-pressure centrifugal only |
| 2.7.4 Automatic Tube Brush Cleaning | Removed | Confirm: water-cooled condenser tubes only |
| 2.10.3 Cooling Tower | Removed | Rule: condenser = air-cooled |
| Refrigerant, capacity, EER, OAT, electrical blanks | Filled | Rule: schedule fields |
| ARMY and NAVY tailoring | Removed | Rule: project.agency = AIR FORCE |

Report before and after counts of unresolved decisions in the PR. Today's baseline from the Maxwell demo: 102.

**Note, 2026-10-20 (step 6).** Two rows above did not survive contact with the master:

- **"Refrigerant, capacity, EER, OAT, electrical blanks: Filled"** cannot happen. 23 64 10 has no such blanks. Its Part 1 note puts chiller performance data on the drawing equipment schedule, and its only Part 2 blanks sit in 2.5 and 2.6.7, which are removed for Maxwell. In this section the schedule drives three choices instead: compressor type, compressor driver and condenser.
- **The "Confirm" rows** (2.4.3 to 2.4.7, 2.6.14, 2.7.4) are not in `annotations/23 64 10.yaml` until an engineer signs off on their rules. Until then they are kept by default and stay open.

Result with `annotations/23 64 10.yaml` and no hand answers: 80 unresolved decisions (`tests/test_maxwell.py`). The spec's own example YAML above is illustrative. Its `refrigerant` target matches nothing in the master, which `annotate-check` reports.

## Testing

- Unit tests for anchors: identical across CRLF and LF copies; stable when an unrelated group is inserted earlier in the section; `~n` numbering for repeats.
- Release test: answers made on the April 2026 03 30 00 applied to the July 2026 copy (check both into `tests/fixtures/`, CRLF preserved).
- Structural removal: parse, round-trip, well-formed XML after removal on every master in a corpus run; submittal and reference cleanup cases.
- Annotation check: every rule in `annotations/23 64 10.yaml` resolves to exactly one target on the current master.
- Maxwell end to end: `prefill` then `generate`; assert the table above.
- Corpus gate: all masters in the WBDG release still round-trip and audit clean, 01 42 00 included in tolerant mode.
- External gate (manual): open the Maxwell output in SpecsIntact on the AFCEC-required version and run section, reference, address, bracket and submittal verification. Save the reports beside the SGTEST ones and compare.

## Work order

1. Hygiene (section 1).
2. Anchors and anchor-keyed answers (section 2).
3. Structural decisions in manifest, generator, revisions output and HTML (section 3).
4. Submittal and reference cleanup (section 3).
5. Design data file, annotation loader, `annotate-check`, `prefill` (sections 4 and 5).
6. `annotations/23 64 10.yaml` and the Maxwell end-to-end test.
7. Provenance fields and HTML coloring (section 6).
8. SpecsIntact acceptance run.

Each step is its own PR with tests; steps 1 and 2 can merge before the rest is designed in detail.

## Future work

- Design-data checks: compare schedule values against code minimums (the ACC-1 EER of 9.98 needs checking against the applicable ASHRAE 90.1 path, and IPLV isn't scheduled).
- Project layer: section selection from scope, cross-section references, 01 33 00 register, 01 42 00 consistency.
- Annotations for 23 64 26 and 26 20 00, which share Maxwell design data with 23 64 10.
- Correction request to UFGS for the 01 42 00 NORSOK entry.
