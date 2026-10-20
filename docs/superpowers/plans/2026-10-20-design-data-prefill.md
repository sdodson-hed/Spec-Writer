# Design Data and Prefill Implementation Plan (work order step 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn design data (equipment schedules, basis of design, project attributes) into an anchor-keyed answers file through a per-section annotation. The output is deterministic and every answer records where it came from. Anything the data cannot answer stays unresolved with the missing field named.

**Architecture:** Four new modules, each pure:
- `specgen/designdata.py` loads and validates the project file.
- `specgen/annotation.py` loads and validates a section annotation, and resolves rule targets against a manifest.
- `specgen/conditions.py` evaluates structured conditions in three-valued logic (true, false, unknown), so missing data is never treated as false.
- `specgen/prefill.py` applies the annotation to the design data and the manifest, and produces the answers JSON.

The answers JSON is the same `specgen.answers/2` format the page and `generate` already read. Two new commands, `annotate-check` and `prefill`, wrap these modules. The real 23 64 10 annotation and the Maxwell end-to-end test are step 6. Override and conflict handling for re-runs is step 7.

**Spec:** `docs/superpowers/specs/2026-10-13-design-data-annotations-design.md`, sections 4 and 5 (and the record shape from section 6).

## Findings (measured 2026-10-20 on 23 64 10)

- Target paths match segment by segment against anchor paths, with `fnmatch` within each segment. The spec's compressor-choice path (`PART 2/SELF-CONTAINED WATER CHILLER*/*TYPE WATER CHILLER*`, kind `choice`) matches **6** choice groups in 2.4.1. The `options` filter (`[Scroll, Reciprocating, Rotary Screw]`) is what narrows it to BRK-0023, so it is required wherever a path is ambiguous.
- The gas-engine, centrifugal and heat-recovery subsection targets resolve to exactly one subsection each.
- The spec's `refrigerant` example (`PART 2/CHILLER COMPONENTS/REFRIGERANT`, kind `blank`) matches **nothing**, because 2.6.1 has no fill-in blank. That is what `annotate-check` exists to catch. The spec's YAML is illustrative, and step 6 writes the real rules.

## Decisions for review (answer before Task 2)

- **D1. YAML parser.** The spec puts annotations in YAML, and specgen has no YAML parser. **Recommended:** add PyYAML (`yaml.safe_load` only) as a runtime dependency, in a new `requirements.txt` that CI installs. The alternative is JSON annotations, which need no dependency but cannot carry comments, and comments matter in a file engineers review.
- **D2. Project-level answers.** The spec's Maxwell table removes ARMY and NAVY tailoring by `project.agency`. **Recommended:** `prefill` answers these for every section without an annotation rule:
  - Tailoring options named after an agency (ARMY, NAVY, AIR FORCE, NASA, USACE) are kept when they match `project.agency` and removed otherwise.
  - Units come from `project.units` (IP or SI).
  - Any other tailoring option, such as NIAGARA FRAMEWORK, is left unanswered.
  - An annotation can override any of these in a `profile:` block.
- **D3. Unresolved reasons.** **Recommended:** a decision the data cannot answer is written as a record with an empty answer and a note, for example `{"answer": "", "notes": "prefill: needs bod.heat_recovery"}`. `read_answers_json` already keeps such records. `generate` gains one line so the note shows up in `.unresolved.md`. The page shows notes already. The decision stays unanswered and nothing is defaulted.
- **D4. Provenance now or in step 7.** **Recommended:** `prefill` writes the spec's `source` object (`kind`, `ref`, `rule`, `data_source`, `value`) and `state: "auto"` from the start, because it is the code that knows them. Step 7 then adds overrides, conflicts and page coloring on top of fields that already exist.
- **D5. Re-running prefill.** Until step 7 defines how `auto` and `overridden` answers merge, `prefill` refuses to overwrite an existing answers file unless `--force` is given, so it never silently drops an engineer's edits.
- **D6. Plural markers.** These are answered only from an explicit `quantity` field on the equipment rows: a total above 1 keeps the plural, a total of exactly 1 removes it. With no `quantity` field the decision stays unresolved. The Maxwell schedule has no quantity, so its plural decision stays open. Today's hand-coded demo answers "keep" because the demo assumed two chillers.

## Global constraints

- Never default. A missing field makes a rule `unknown`, which leaves the decision unresolved with the field named. A disagreement across equipment rows leaves it unresolved with each row's value listed.
- No expression strings and no `eval`. Conditions are YAML mappings evaluated by `conditions.py`.
- Annotations never contain spec text. Unknown keys fail validation, so typos never silently become no-ops.
- `prefill` output is deterministic. The same inputs produce byte-identical JSON, with sorted keys and no timestamps in the answer records. The export time goes in one top-level field.
- Byte-identical round-trip, the corpus gate, and the steps 1 to 4 guarantees are unchanged. `generate` changes by one line (D3).
- Branch `prefill`, one PR. Same gates and commit trailer as before.

---

### Task 1: `specgen/designdata.py`

Loads `projects/<name>/design-data.json` and checks it:
- The schema is `specgen.design-data/1`.
- `project.agency` and `project.units` (IP or SI) are present.
- Every equipment row has `mark`, `schedule` and `source`, and its `source` names a key in `sources`.
- Marks are unique.

It returns a typed view: `rows(schedule) -> list[dict]`, `bod`, `project`, and `source(mark) -> dict`. Unknown top-level keys are an error.

- [ ] Tests first, against the Maxwell file (loads, one `air_cooled_chiller` row) and against broken copies, one per rule. Implement, then commit.

### Task 2: `specgen/conditions.py`

Three-valued evaluation. `evaluate(cond, ctx) -> True | False | None`, where `None` means unknown and comes back with the missing field names.

- **Leaf matchers:** `{field: value}` (case-insensitive equality for strings), `{field: {in: [..]}}`, `{field: {equals: x}}`.
- **Scopes:** `any_equipment`, `all_equipment` (over the annotation's `applies_to` rows, with derived facts included), `bod` and `project`.
- **Combinators:** `all`, `any` and `not`, using Kleene logic. `any` is true if any operand is true, false only if every operand is false, and unknown otherwise.
- **Derived facts:** `derive:` entries are `{from: field, map: {..}}` or `{value: x}`, computed once per row. A `from` value that is missing from the map is unknown, never a default.

- [ ] Tests first. They cover every operator, Kleene truth tables with unknowns, and missing fields reported by name. They include the multi-row rule: `remove_unless: any_equipment` is false only when no row needs the content. Implement, then commit.

### Task 3: `specgen/annotation.py` and `annotate-check`

Loads YAML (D1) and validates it against the spec's schema:
- `section` and `applies_to.schedule`
- an optional `derive` and an optional `profile`
- `rules`, where each has an `id`, a `target {path, kind, options?, nth?}`, and exactly one action: `choose: {match}`, `fill`, or `remove_unless`. `requires` is optional.

`resolve_targets(annotation, manifest) -> {rule_id: [decision or subsection]}`. Paths match segment by segment with `fnmatch` within a segment. `options` filters by normalized, case-insensitive option text. `nth` picks the nth match in document order.

`python -m specgen annotate-check "<master>" --annotation <file>` prints each rule with its matches. It exits 1 if any rule matches zero, or more than one without `nth`, or if the annotation's `section` does not match the master.

- [ ] Tests first: schema errors (unknown key, two actions, missing target), zero, one and many matches, `options` narrowing, `nth`, a section mismatch, and the CLI exit codes. The fixture annotation targets the synthetic chiller section from the step 3 and step 4 tests. Implement, then commit.

### Task 4: `specgen/prefill.py` and `prefill`

`prefill(manifest, design_data, annotation) -> answers dict` (plus a report):

1. Project-level answers (D2), then the annotation's `profile:` overrides.
2. Structural rules (`remove_unless` on `spt` targets) first. Rules whose targets fall inside a subsection removed by an earlier rule are skipped and logged.
3. Choices and fills. `{field}` templates read the applies_to rows (with derived facts), `bod.x` or `project.x`. If rows disagree, the decision stays unresolved with "equipment rows disagree: ACC-1=X, ACC-2=Y". A `choose.match` value that matches no option is unresolved with the value shown.
4. `remove_unless` on an optional bracket answers `delete` or `keep`.
5. `requires` fields that are missing leave the decision unresolved (D3).
6. Every answered record carries `source` and `state: "auto"` (D4).

`python -m specgen prefill "<master>" --design-data <file> --annotation <file> -o <answers.json> [--force]` writes the answers JSON (D5) and `<answers>.prefill.md`. The `.prefill.md` lists every rule, what it answered or why it could not, and anything left for the engineer.

- [ ] Tests first: each step above on the synthetic section, deterministic output (two runs give identical bytes), D5 refusal, and the JSON loading through `read_answers_json`. Then a round trip: `prefill` into `generate --strict --revisions` on the synthetic section, asserting the expected removals, fills and choices. Implement, then commit.

### Task 5: `generate` shows unresolved notes (D3)

- [ ] When an unanswered decision's record carries notes, `.unresolved.md` shows them. Test first, then commit.

### Task 6: Docs and PR

- [ ] README: the design-data file, annotation format and both commands. PR description with the gates, test counts and an example `.prefill.md`. The real 23 64 10 annotation is step 6.

## Not in this plan

- `annotations/23 64 10.yaml` and the Maxwell end-to-end acceptance against the spec's table (step 6).
- Merging prefill re-runs with engineer overrides, conflict state, and page coloring by source (step 7).
- Code-compliance checks on design data, such as EER against ASHRAE 90.1 (future work in the spec).
