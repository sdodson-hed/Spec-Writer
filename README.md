# specgen — UFGS Spec Section Generator (Phase 0)

Tooling for the SpecsIntact automation project: parse UFGS master sections
(`.SEC`, SpecsIntact XML), round-trip them losslessly, and extract the
**decision manifest** — every bracket choice, fill-in blank, optional phrase,
tailoring option, submittal, and reference a section demands of a specifier.

## Status

- Lossless parser: **all 431 masters in the current WBDG release
  round-trip byte-identically** (Divisions 01 03 05 07 08 09 21 22 23 26 28
  31 33, UMRL July 2026); 429 audit clean. 01 42 00 ships a stray `</URL>`
  in its NORSOK entry: tolerant mode keeps it as raw text and `audit`
  reports it as a source defect (exit 2), not a pass. 22 60 70 has a
  control character XML forbids ("Dental Surgical Vacuum\x13"), kept and
  reported the same way, and `generate` checks around it.
  SpecsIntact's own UFGS library (682 sections, July 2026) also round-trips
  completely: 678 audit clean, 4 source defects. The extra two are 02 83 00,
  with a corrupt byte ("off\x81-site"; the five bytes windows-1252 leaves
  undefined are read the way Windows reads them and kept byte for byte), and
  35 05 40.14 10, with two more \x13 characters.
  The earlier 56-master corpus (55 Division 23 + 26 20 00, UMRL April 2026)
  is in `masters/Specifications` on the shared drive.
- Stable anchors: answers are keyed by `<path>#<kind>:<hash8>[~n]`, not by
  positional `BRK-NNNN` ids, so they survive quarterly UFGS releases and
  CRLF/LF differences. Answers made on 03 30 00 (April 2026) carry 236 of
  244 decisions to the July 2026 copy; the other 8 are reported, not applied.
- Subsection decisions: every `<SPT>` (40,965 across the WBDG release) can be
  kept or removed, with the same guarantees as bracket decisions. Removing
  every 5th subsection in all 430 well-formed WBDG masters passes generate's
  verification. Cleanup drops the submittal items and references only
  removed subsections used.
- Design data drives Maxwell 23 64 10 end to end: `prefill` with
  `annotations/23 64 10.yaml` and the ACC-1 schedule answers 13 of 14 rules
  (7 subsections removed, compressor/driver/condenser chosen, ARMY and NAVY
  tailoring removed, IP units), and `generate` leaves 80 decisions for the
  engineer (102 before, with 8 hand-picked answers), checked against the
  spec's table by `tests/test_maxwell.py`.
- 23 64 26 (chilled, chilled-hot and condenser water piping) has an
  annotation too (`annotations/23 64 26.yaml`, 5 rules). A piping section
  serves the whole project, so its rules wait for explicit basis-of-design
  facts (`bod.condenser_water`, `bod.glycol`) rather than inferring them from
  the chiller schedule. With Maxwell's empty `bod` they stay open with that
  reason; recorded false, they remove condenser water treatment, its tests
  and one-year inspection, and glycol (`tests/test_maxwell_23_64_26.py`).
- Additive bracket lists: choice groups that are select-any lists
  ("[ single pole][, double pole][, and four-way]") render as checkboxes;
  connector-only spans ("[ or ]") are joiners, never options; kept items
  are rejoined with correct commas/and/or by `generate`. Mid-sentence
  choice groups demote "remove entirely" behind a confirmation.
- Decision manifests generated for the Maxwell pilot sections:
  - `23 64 10` Water Chillers, Vapor Compression Type (147 bracket groups)
  - `23 64 26` Chilled/Chilled-Hot/Condenser Water Piping Systems
- Completeness audit enforced corpus-wide: unknown bracket tokens and nested
  structure violations caught in CI (all 56 masters audit-clean).
- Markup signals surfaced: units (SI/IP), submittal-review groups, and
  markup-split conflicts all detectable and traceable in manifests and reports.
- XSD validation wired up but the official schema
  (`si.ksc.nasa.gov/sidownloads/xml/specsintactSEC.xsd`) was unreachable —
  drop it into `schema/` when obtainable (it ships with the SpecsIntact
  install, e.g. `C:\Program Files (x86)\SpecsIntact\...`).

## Usage

```
python -m specgen roundtrip "masters/23 64 10.SEC"   # byte-identical check
python -m specgen manifest  "masters/23 64 10.SEC" -o out/manifest.json
python -m specgen report    "masters/23 64 10.SEC" -o out/report.md
python -m specgen validate  "masters/23 64 10.SEC"  [--schema path.xsd]
python -m specgen answers   "masters/23 64 10.SEC" -o out/answers.xlsx
python -m specgen html      "masters/23 64 10.SEC" -o out/decisions.html
python -m specgen generate  "masters/23 64 10.SEC" \
    --answers out/answers.xlsx -o out/generated/23_64_10.sec   # or .json
python -m specgen audit     "masters/23 64 10.SEC"               # completeness gate
python -m specgen generate  ... --revisions   # also emit .revisions.sec (SI tracked changes)
python -m specgen generate  ... --strict      # refuse if any answer no longer resolves
python scripts/audit_corpus.py [corpus_dir]   # audit + round-trip every .SEC under a dir
                                              # (default $SPECGEN_CORPUS, else masters/Specifications)
python scripts/build_project.py <dir> <masters...>   # per-project batch + index
python -m specgen annotate-check "masters/23 64 10.SEC" --annotation "annotations/23 64 10.yaml"
python -m specgen prefill "masters/23 64 10.SEC" \
    --design-data projects/maxwell/design-data.json \
    --annotation "annotations/23 64 10.yaml" -o out/maxwell/23_64_10.answers.json
```

## The answer-file workflow (no platform integration required)

1. Emit the decision surface: `html` builds a single-file interactive page
   (open in any browser, no server; answers autosave locally; Export
   downloads an answers JSON). `answers` builds the same thing as an Excel
   workbook for engineers who prefer a spreadsheet. Both cover: choices,
   blanks, optionals, duplicate propagation, and a Project Profile block
   (tailoring keep/remove, plural [s] markers).
   The page also has an Edit mode: click Edit and type directly in the
   document like a tracked-changes Word doc — insertions show green,
   deletions show red strikethrough, and every change exports as an ME@
   record that `generate` applies and `--revisions` renders as native
   SpecsIntact ADD/DEL markup.
2. An engineer — or, later, the Hedral platform — fills in the answers.
3. `generate` accepts either the .xlsx or the exported .json (they are
   provably equivalent) and applies them: resolves brackets, strips removed
   tailoring blocks, and emits the tailored `.sec` plus `.redline.md`
   (human-readable change log), `.redline.json` (machine audit trail), and
   `.unresolved.md` (decisions needing engineer input). Output is verified
   (parse, round-trip, well-formed) before it is written; unanswered
   decisions are never defaulted. Structurally unsafe groups (bracket spans
   crossing markup unevenly) are flagged for manual editing, never touched.

Answer keys. Exports (`schema: specgen.answers/2`) and workbooks key each
bracket answer by its anchor: the PRT/SPT title path, the decision kind, and
a hash of its option text, e.g. `PART 2/REFRIGERANT#blank:2477bc03`. The
`BRK-NNNN` id and option texts ride along for display. When the master
changes (a new UFGS release), every anchor that still matches applies; an
anchor that no longer matches goes to `.unresolved.md` as "master changed:
decision not found" with the option text it was answered against, and is
applied to nothing. Older answer files keyed on `BRK-NNNN` still load when
their fingerprint matches this master. `--strict` turns any non-resolving
answer or fingerprint mismatch into a hard stop.

Subsections. Every `<SPT>` is also a keep/remove decision (manifest
`subsections`, anchor `<path>#spt:<hash8>`, workbook Subsections sheet,
keep/remove buttons on the page's outline). `remove` deletes the whole
subsection, its children and every decision inside it; the page drops those
decisions from the counter and collapses the text. An unanswered subsection
is kept: the one place a missing answer has a meaning, because UFGS masters
are written "everything present until removed". `.redline.json` logs it as
`kept by default` with `source: default`, so a reviewer can tell it from a
deliberate keep. A subsection that is the whole content of an optional
bracket (`[<SPT>...</SPT>]`) is the same decision as that bracket; answering
either sets both, and disagreeing answers are reported and neither applied.
Removed subsections appear as `<DEL>` blocks in `.revisions.sec`.

Cleanup after removal. When subsections are removed, `generate` also drops
what SpecsIntact's submittal and reference verification would otherwise
flag. That means submittal items (`<ITM>` in the SUBMITTALS article) and
reference entries (`<RID>`/`<RTL>`) whose only body uses were inside the
removed subsections, plus any SD heading or reference organization block
that this empties. Each one is logged in `.redline.json` with the
subsection that caused it (and the item's reviewer code, if it had one).
It becomes a `<DEL>` block in `.revisions.sec`, and the page strikes it as
a preview. Section cross-references that are no longer cited are listed in
the summary. An orphaned item inside a bracket is never removed, because
that would answer the bracket decision. It stays, and `.unresolved.md`
suggests deleting it. Only subsection removals trigger cleanup; text
removed by bracket answers or tailoring is handled as before.

Shared-drive workflow: `build_project.py` sets up a per-project layout
(`decisions/`, `answers/`, `generated/`, `index.html`) that organizes manifests,
filled-in answers, and generated outputs. Export from the HTML or Excel
interface produces an answers file that explicitly marks any unanswered
decisions, so the engineer can verify completeness before generation. When
`generate` is invoked with `--revisions`, both `.sec` and `.revisions.sec` are
written; the `.revisions.sec` file opens directly in SpecsIntact with native
red/green tracked-change markup, bridging the workflow back to the existing QA
tools.

## Design data and prefill

`prefill` answers a section from the project's design data, so the engineer
reviews exceptions instead of entering every value.

- **Design data** (`projects/<name>/design-data.json`, schema
  `specgen.design-data/1`) holds project attributes (`agency`, `units`),
  equipment schedule rows (fields named after the schedule columns, each row
  citing its source document) and basis-of-design fields (`bod`).
- **An annotation** (`annotations/<section>.yaml`) maps that data to one
  section's decisions. Each rule targets a decision by anchor path, kind,
  option text and `nth`. It then either chooses an option
  (`choose: {match: "{compressor_type}"}`), fills a blank
  (`fill: "{refrigerant}"`), or keeps or removes a subsection or optional text
  (`remove_unless: <condition>`). Conditions are YAML mappings over
  `any_equipment`, `all_equipment`, `bod` and `project`, combined with `all`,
  `any` and `not`. There are no expression strings. `derive` adds named facts
  per equipment row.
- **`annotate-check`** fails unless every rule matches exactly one decision in
  the current master. Run it after each UFGS release.
- **`prefill`** writes the same answers JSON the page and `generate` read, plus
  a `.prefill.md` report. Agency tailoring and units come from the project.
  Plural markers come only from an equipment `quantity`. Every answer records
  its `source` (`kind`, `ref`, `rule`, `data_source`, `value`) and
  `state: auto`.

Missing data is never defaulted. A missing field (a condition is
three-valued: true, false or unknown), disagreeing equipment rows, or a value
that matches no option leaves the decision unanswered. Its note, for example
"prefill (heat-recovery): needs bod.heat_recovery", appears on the page and in
`.unresolved.md`. Run `prefill` again on an existing answers file and it
merges (next section); `--force` replaces the file instead.

PyYAML reads the annotations (`requirements.txt`). On a Python with no
prebuilt PyYAML wheel, install it with `PYYAML_FORCE_LIBYAML=0` set to get
the pure-Python build.

Demo: `python scripts/maxwell_demo.py` runs `prefill` on 23 64 10 with
`projects/maxwell/design-data.json` and `annotations/23 64 10.yaml`, then
`generate --strict --revisions`, into `out/maxwell-demo/1-prefill/`. A second
scenario, `2-schedule-revision/`, re-runs prefill after a scripted engineer
review and a schedule change, which leaves one conflict. Open
`out/maxwell-demo/index.html`; the walkthrough is `docs/maxwell-demo.md`.
`python -m specgen html ... --answers <file>` builds a decision page that
opens with those answers loaded. Nothing in the first scenario is
hand-coded. The ACC-1 schedule removes the 7 subsections it rules out
(centrifugal, split-system, screw and centrifugal compressors, gas-engine
driver, water-cooled condenser coil, cooling tower) and picks scroll,
electric motor and air-cooled condenser coil. The project picks Air Force
tailoring and IP units. Everything else is listed in `.prefill.md` and
`.unresolved.md`.

## Provenance and re-runs

Every answer says where it came from, and the design data can change after
the engineer has worked on the file. Each answer record carries a `source`
and a `state`:

| state | meaning |
|---|---|
| `auto` | written by `prefill`; follows the data on every re-run |
| `overridden` | the engineer changed a prefilled answer; `source.kind` is `manual` and `source.was` keeps prefill's source and answer |
| `conflict` | the data changed under an override, or under an answer given by hand: `source.now` holds what prefill says now |
| (none) | answered by hand where prefill had nothing |

Run `prefill` again on the same `-o` file and it merges. Auto answers take the
new data. An override stays when the data it overrode is unchanged ("kept
override"). It becomes a conflict when the data moved. If the data now gives
the engineer's own answer, the override is marked as agreeing. Text edits
(`ME@`) and hand answers prefill does not touch are kept. Project settings
(`profile` with `profile_meta`) follow the same rules. The merge outcome of
each changed record is listed in the file (`prefill.merge`) and in
`.prefill.md`.

`generate` applies neither value of a conflict. The decision stays
unanswered, and `.unresolved.md` shows both, for example
"conflict: engineer answer 'Air-cooled condenser coil with factory-applied
coil coating'; prefill now '2' from ACC-1.condenser_component (derived) =
'Water-cooled condenser'". `--strict` refuses to generate while any conflict
is open. `.redline.json` records the source and state of each applied answer.

The decision page colors each answer by source. Schedule is blue, basis of
design teal, project rule indigo, engineer amber and default gray. An `ai`
source gets purple, reserved for later. An override shows the engineer's
color with prefill's value beside it, plus a Revert to prefill button. A
conflict shows a dashed red outline, both values, and Keep mine / Take
prefill. The header counts open conflicts, and Next unanswered visits them
first. Editing an answer on the page stamps it as an override, so an
exported file merges like one edited by hand.

A decision that appears twice (the 23 64 10 compressor choice in the
submittal list and in 2.4.1) is one decision. When a rule answers the later
instance, `prefill` writes the first instance with `same_as` pointing at it.
`generate`, the merge and the page then copy that record's answer, source
and state, override or conflict included. Editing the first instance on the
page drops `same_as` and makes it the engineer's own answer.

`tests/test_maxwell.py` runs the whole cycle on 23 64 10: prefill, an
engineer override of the condenser choice, a re-run on unchanged data (the
override is kept), ACC-1 changed to `WATER-COOLED SCROLL` (the condenser
choice becomes a conflict; 2.6.11 and 2.10.3 now stay and 2.6.10 goes), and
`generate` leaving the conflict open. The workbook does not show provenance.

## Layout

- `specgen/secfile.py` — raw-token parser/serializer (byte-identical output
  is guaranteed by keeping every token's source text; no XML library rewrites)
- `specgen/manifest.py` — flattens text with a char→location map, scans for
  literal bracket groups, extracts TAI/SUB/RID/NTE structure
- `masters/` — local copies of pilot sections (source of truth is
  `G:\Shared drives\Hedral-Shared\...\Mech\Specifications`; never edited)
- `out/` — generated manifests and reports

## Known heuristic limits (fine for Phase 0, resolved at annotation time)

- Adjacent bracket spans are grouped as one choice set; UFGS sometimes butts
  unrelated brackets together (e.g. an optional submittal item directly
  followed by a choice set), so some groups need manual splitting.
- Plural markers like `Chiller[s]` classify as `optional` — trivial to
  resolve (quantity > 1) but they inflate the optional count.

## Next (Phase 1/2)

1. Get the XSD from a SpecsIntact install; make `validate` part of CI.
2. Annotation layer: map each manifest decision ID for 23 64 10 to a
   design-data field or rule (chiller schedule, system alternative, project
   attributes). Deterministic at generation time.
3. Generator: apply an annotation + design data to the master, emit the job
   copy, unresolved-decision list, and redline log.
4. Open a generated file in SpecsIntact on the AFCEC-mandated version and run
   its QA reports — the external acceptance gate.
