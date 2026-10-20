# Provenance Implementation Plan (work order step 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every answer says where it came from. An engineer's edit to a prefilled answer is kept as an override, with the original preserved. Re-running `prefill` after the design data changes never silently replaces an engineer's answer: it flags a conflict that shows both values. The decision page colors each answer by its source.

**Spec:** `docs/superpowers/specs/2026-10-13-design-data-annotations-design.md`, section 6 (provenance).

## Starting point

`prefill` already writes `source` (`kind`, `ref`, `rule`, `data_source`, `value`) and `state: "auto"` (step 5, D4). The page's import and export keep unknown fields, so those survive a round trip. Nothing yet changes `state`, nothing merges a re-run, and nothing shows provenance.

The spec's "provenance palette from the 2026-10-13 product discussion" is not in the repo, and a search of Notion did not find it. Notion did have a related precedent: the External-Sync-Workflow spike resolves "changed on both sides" conflicts by asking the user to **keep, take, or override**. The conflict card below follows that pattern.

## Record shapes

```json
"<anchor>": {"answer": "1", "id": "BRK-0023", "notes": "",
  "source": {"kind": "schedule", "ref": "ACC-1.compressor_type", "rule": "compressor-type",
             "data_source": "acc-sched-35", "value": "SCROLL"},
  "state": "auto"}
```

- **Engineer edits it (page):**
  - `answer` becomes the new value.
  - `source` becomes `{"kind": "manual", "was": {<original source>, "answer": "1"}}`.
  - `state` becomes `"overridden"`.
- **Engineer answers something prefill did not:** `source` is `{"kind": "manual"}` and there is no `state`.
- **Prefill re-run, data changed under an override:**
  - `state` becomes `"conflict"`.
  - `source.now` holds `{<new source>, "answer": "3"}`.
  - `answer` keeps the engineer's value.
- **Subsection answers** get the same record on the page. Today only `"remove"` or `"keep"` is stored, so their provenance is lost on import.
- **Project settings** (tailoring, units, plural) get the same treatment in a new `profile_meta` map (D5).

## Decisions for review

- **D1. Palette.** Not found, so this one is proposed. It is used as a colored underline on each decision mark, a dot on outline rows, and a legend in the header. The colors read on light and dark themes and stay clear of the redline green and red:

  | Source | Color |
  |---|---|
  | schedule | blue `#2563eb` |
  | basis of design | teal `#0d9488` |
  | project rule | indigo `#6366f1` |
  | manual | amber `#d97706` |
  | ai | purple `#9333ea` (reserved; nothing produces it yet) |
  | kept by default | gray `#6b7280` |
  | conflict | red `#dc2626` dashed outline |

  Overridden answers use the manual color plus an "edited" badge. Swap in the real palette if it turns up.
- **D2. A conflict in `generate`.** **Recommended:** neither value is applied. The decision goes to `.unresolved.md` showing both: "you answered Scroll; prefill now says Rotary Screw from ACC-1.compressor_type = ROTARY SCREW". This matches step 3's governed-bracket conflicts. The engineer resolves it on the page (keep or take), and `--strict` refuses while any conflict is open.
- **D3. A manual answer that predates prefill.** If the engineer answered a decision before prefill had a value for it, and prefill later produces a different value, that is a conflict. If the values agree, the manual answer stays.
- **D4. `prefill` re-runs merge by default.** This replaces step 5's "refuse to overwrite". Merging:
  - updates `auto` answers;
  - keeps overrides, and flags a conflict when the new value differs from `source.was`;
  - drops `auto` answers no rule produces any more;
  - keeps manual answers and text edits;
  - lists all of it in a new "Merge" section of `.prefill.md`.

  `--force` still replaces the file outright.
- **D5. Project-settings provenance.** Settings are tracked in `profile_meta`, with the same merge and conflict rules. A conflicted setting is left unanswered, so its tailoring blocks are kept and it is listed for review, consistent with D2.
- **D6. The workbook.** The workbook path stays provenance-free: answers read from xlsx count as manual. Provenance lives in the JSON and page workflow.

## Tasks

### Task 1: `specgen/provenance.py`: merging a re-run

`merge(existing: dict, fresh: dict) -> (payload, report)` works on answers JSON payloads, applying the D3, D4 and D5 rules per anchor and per profile setting.

- [x] Tests first, each case on its own:
  - auto replaced by new auto
  - auto replaced by a new unresolved note
  - auto dropped when no rule produces it
  - override kept when the data is unchanged
  - override becomes a conflict when the data changes
  - a conflict returns to overridden when the data reverts
  - a conflict updates `source.now` on a second change
  - a manual answer equal to the new value is kept
  - a manual answer that differs becomes a conflict
  - manual answers and text edits are kept when prefill is silent
  - profile_meta follows the same rules
  - the output is deterministic
- [x] Implement, then commit.

### Task 2: `prefill` merges by default

- [x] `prefill -o existing.json` merges (D4). `--force` replaces.
- [x] `prefill` writes `profile_meta`.
- [x] `.prefill.md` gains a Merge section listing kept overrides, new conflicts, resolved conflicts and dropped auto answers.
- [x] Tests first (CLI round trips on the step 5 fixture), then commit.

### Task 3: `generate` honors provenance

- [x] A `conflict` record leaves the decision unanswered. `.unresolved.md` shows both values with their sources (D2). Duplicate propagation never fills it. Subsections and project settings are covered too. `--strict` refuses while a conflict is open.
- [x] `.redline.json` entries carry `source` and `state`. The issued `.sec` carries none, as the spec says.
- [x] Tests first, then commit.

### Task 4: Decision page

- [x] **Pure JS in `STRUCT_CORE_JS`**, with Node tests and the same assertions run in the browser:
  - `stampEdits(prevAnswers, answers)`: the snapshot comparison that turns changed `auto` or `conflict` records into overrides, and new answers into `manual`.
  - `revertOverride(rec)`
  - `keepMine(rec)` and `takePrefill(rec)`
- [x] **Wiring.** `save()` stamps against a snapshot taken at load and after each import, so a dozen code paths need no individual changes. Subsection and profile records keep their provenance through import and export.
- [x] **UI:**
  - D1 colors on decision marks and outline rows, plus a legend.
  - The decision card shows the source ("from ACC-1.compressor_type = SCROLL, chiller schedule 35%, rule compressor-type").
  - Overridden: "you changed this from Scroll", with **Revert to prefill**.
  - Conflict: both values, with **Keep mine** and **Take prefill**.
  - The header gains a conflict counter, and "next unanswered" visits conflicts first.
- [x] Browser check on 23 64 10 with Maxwell's prefill: colors and legend, edit then revert, and a conflict made by re-running prefill with ACC-1 changed to ROTARY SCREW, resolved both ways.
- [x] Commit.

### Task 5: Maxwell re-run scenario and docs

- [x] `tests/test_maxwell.py` gains the full round trip:
  1. prefill
  2. an engineer override of the condenser choice (an edit to the answers JSON). As built, the override is custom text: the choice has two options, so picking Water-cooled would agree with step 4's schedule instead of conflicting with it
  3. prefill again with unchanged data: the override is kept
  4. ACC-1 changed to `WATER-COOLED SCROLL` and prefill again: the condenser choice is a conflict showing both values; 2.6.11 and 2.10.3 now stay; 2.6.10 goes
  5. `generate` leaves the conflict unresolved with both values
- [x] README provenance section, then the PR.

## Not in this plan

- An `ai` producer: the palette reserves its color.
- Provenance in the workbook (D6).
- Step 8, the manual SpecsIntact acceptance run.
