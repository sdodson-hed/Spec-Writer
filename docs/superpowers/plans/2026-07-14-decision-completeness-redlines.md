# Decision Completeness + Redlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee every input signal in a UFGS `.SEC` is surfaced in the HTML decision page (machine-checked), make unanswered decisions unmissable, and emit red/green redlines both live in the page and as native SpecsIntact `<ADD>/<DEL>` revision markup.

**Architecture:** All bracket intelligence stays in `specgen/scan.py` (the single scan that drives both manifest and generator). A new `specgen/audit.py` enforces the completeness invariant (every signal → surfaced | excluded-by-named-rule | unknown). The HTML page gains a redline renderer over the existing char-span machinery. The generator grows a parallel "revisions source" that receives the same splices wrapped in `<DEL>/<ADD>`.

**Tech Stack:** Python 3.10+, stdlib + openpyxl (already a dep), pytest for tests, vanilla JS in the single-file HTML template.

**Spec:** `docs/superpowers/specs/2026-07-14-decision-completeness-redlines-design.md`

## Global Constraints

- `.SEC` files are windows-1252 (`secfile.ENCODING`); never decode as UTF-8.
- Byte-identical round-trip is sacred: the parser/serializer path must not change token text. Note masking affects *scanning only*, never serialization.
- `BRK-xxxx` IDs are assigned in document order over **all** scanned groups, including groups inside notes — this keeps IDs stable with existing manifests/answer files (e.g. `out/23 64 10.answers.maxwell.json`).
- Unanswered decisions are NEVER defaulted; they flow to `.unresolved.md`.
- No new runtime dependencies. Dev-only: pytest.
- Test corpus: `masters/Specifications/*.SEC` (55 files). Tests that need it must `pytest.mark.skipif` on its absence.
- All new manifest keys are additive — existing consumers (xlsx, HTML, generate) must keep working on old fields.
- Run all commands from the repo root: `C:\Users\Victor Colosi\dev\Spec intact`.

---

### Task 1: Note masking in the scanner

Brackets inside `<NTE>` designer notes are guidance, not decisions. Mark them at the scanner level so every consumer (manifest, HTML, generator, audit) agrees, and so a note bracket can never merge with a body bracket.

**Files:**
- Modify: `specgen/scan.py` (`text_stream`, `Group`, `scan_groups`)
- Modify: `specgen/secfile.py` (add `parse_source` so tests don't need temp files)
- Modify: `specgen/manifest.py:107-116` (use `g.in_note`, drop tree-based note spans)
- Modify: `specgen/generate.py:80-105, 201-221` (skip note groups)
- Create: `tests/__init__.py` (empty), `tests/test_scan_notes.py`

**Interfaces:**
- Produces: `text_stream(src) -> tuple[str, list[int], list[bool]]` (chars, offsets, mask; `mask[i]` True = inside a note). `Group` gains field `in_note: bool = False`. `secfile.parse_source(source: str, path: Path = Path("<memory>")) -> SecFile`.
- `scan_groups` keeps its `(groups, text, offs)` return shape.

- [ ] **Step 1: Install pytest (dev only) and create test package**

```
python -m pip install pytest
```

Create empty `tests/__init__.py`.

- [ ] **Step 2: Write the failing tests**

`tests/test_scan_notes.py`:

```python
from specgen.scan import scan_groups, text_stream

# balanced brackets in a note, plus a body choice
BAL = (
    "<SEC><NTE><NPR>NOTE: choose [copper][steel] per project.</NPR></NTE>"
    "<TXT>Provide [scroll][screw] compressors.</TXT></SEC>"
)

# 23 09 23.01 idiom: a note QUOTING an unmatched bracket character
UNBAL = (
    '<SEC><NTE><NPR>NOTE: "a Gateway [or " appears only when selected.</NPR></NTE>'
    "<TXT>Provide [one][two] units.</TXT></SEC>"
)

# note bracket directly adjacent to a body bracket must not merge
ADJ = "<SEC><NTE>keep [x]</NTE>[y] text</SEC>"


def test_note_groups_marked_and_ids_stable():
    groups, _, _ = scan_groups(BAL)
    assert [g.gid for g in groups] == ["BRK-0001", "BRK-0002"]
    assert [g.in_note for g in groups] == [True, False]
    body = groups[1]
    assert [o.text for o in body.options] == ["scroll", "screw"]


def test_unbalanced_note_bracket_does_not_leak():
    groups, _, _ = scan_groups(UNBAL)
    body = [g for g in groups if not g.in_note]
    assert len(body) == 1
    assert [o.text for o in body[0].options] == ["one", "two"]


def test_note_body_adjacency_never_merges():
    groups, _, _ = scan_groups(ADJ)
    assert len(groups) == 2
    assert groups[0].in_note and not groups[1].in_note


def test_text_stream_mask():
    text, offs, mask = text_stream("<SEC>a<NTE>b</NTE>c</SEC>")
    assert text == "abc"
    assert mask == [False, True, False]
    assert len(offs) == 3
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_scan_notes.py -v`
Expected: FAIL — `ValueError: too many values to unpack` (text_stream returns 2-tuple) and `AttributeError: 'Group' object has no attribute 'in_note'`.

- [ ] **Step 4: Implement**

In `specgen/secfile.py`, split `parse` (keep behavior identical):

```python
def parse(path: Path | str) -> SecFile:
    path = Path(path)
    return parse_source(path.read_bytes().decode(ENCODING), path)


def parse_source(source: str, path: Path | str = Path("<memory>")) -> SecFile:
    path = Path(path)
    prolog: list = []
    ...  # the ENTIRE existing body of parse() from `prolog: list = []` down,
         # unchanged, minus the two removed lines (path=Path / read_bytes)
```

In `specgen/scan.py`, replace `text_stream` and extend `Group`/`scan_groups`:

```python
@dataclass
class Group:
    gid: str
    kind: str
    options: list[Option]
    src_start: int
    src_end: int
    char_start: int
    char_end: int = -1
    safe: bool = True
    in_note: bool = False  # inside <NTE>: guidance text, never a decision


def text_stream(src: str) -> tuple[str, list[int], list[bool]]:
    """Return (chars, offsets, mask): text outside markup, source offset of
    each char, and mask[i]=True when the char is inside an <NTE> note."""
    chars: list[str] = []
    offs: list[int] = []
    mask: list[bool] = []
    nte_depth = 0
    i, n = 0, len(src)
    while i < n:
        if src[i] == "<":
            if src.startswith("<!--", i):
                i = src.find("-->", i) + 3
            elif src.startswith("<?", i):
                i = src.find("?>", i) + 2
            else:
                raw, i = _parse_tag(src, i)
                body = raw[1:-1]
                if body.startswith("/"):
                    if body[1:].strip() == "NTE":
                        nte_depth = max(0, nte_depth - 1)
                elif not body.rstrip().endswith("/"):
                    if body.split()[0].strip() == "NTE":
                        nte_depth += 1
        else:
            chars.append(src[i])
            offs.append(i)
            mask.append(nte_depth > 0)
            i += 1
    return "".join(chars), offs, mask
```

In `scan_groups`: unpack `text, offs, mask = text_stream(src)`; adjacency additionally requires `mask[k] == mask[group_char_start]`; construct groups with `in_note=mask[group_char_start]`.

```python
def scan_groups(src: str) -> tuple[list[Group], str, list[int]]:
    text, offs, mask = text_stream(src)
    groups: list[Group] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        group_char_start = i
        in_note = mask[i]
        options: list[Option] = []
        end = i
        while i < n and text[i] == "[":
            depth, j = 0, i
            while j < n:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n:
                options = []
                break
            inner = text[i + 1 : j]
            options.append(
                Option(text=inner, src_start=offs[i] + 1, src_end=offs[j])
            )
            end = j + 1
            k = end
            while k < n and text[k] in " \t":
                k += 1
            if (
                k < n
                and text[k] == "["
                and mask[k] == in_note
                and src[offs[end - 1] + 1 : offs[k]].strip(" \t") == ""
            ):
                i = k
            else:
                i = end
                break
        if options:
            g_start, g_end = offs[group_char_start], offs[end - 1] + 1
            safe = balanced(src[g_start:g_end]) and all(
                balanced(src[o.src_start : o.src_end]) for o in options
            )
            groups.append(
                Group(
                    gid=f"BRK-{len(groups) + 1:04d}",
                    kind=classify([o.text for o in options]),
                    options=options,
                    src_start=g_start,
                    src_end=g_end,
                    char_start=group_char_start,
                    char_end=end,
                    safe=safe,
                    in_note=in_note,
                )
            )
        else:
            i = group_char_start + 1
    return groups, text, offs
```

In `specgen/manifest.py`: in `build_manifest`, replace `in_note = any(s <= g.src_start < e for s, e in notes)` with `in_note = g.in_note`; change `_location_index` to return only `locs` (delete the `notes` list and its collection) and update the call site to `locs = _location_index(root)`.

In `specgen/generate.py`:
- Top of the bracket loop (right after `for g in sorted(...)`) add:

```python
        if g.in_note:
            continue  # designer-note text is never edited
```

- In the final rescan loop (`for fg in final_groups:`) add as its first line:

```python
        if fg.in_note:
            continue
```

- [ ] **Step 5: Run tests and the corpus sanity check**

Run: `python -m pytest tests/test_scan_notes.py -v`
Expected: 4 PASS.
Run: `python -m specgen roundtrip "masters/23 64 10.SEC"`
Expected: `OK: ... round-trips byte-identically` (scanner change can't affect this, verify anyway).
Run: `python -m specgen manifest "masters/23 64 10.SEC" -o "C:\Users\VICTOR~1\AppData\Local\Temp\claude\m.json"` and diff the `counts` block against `out/23 64 10.manifest.json` — `bracket_groups_total` and per-kind counts must be unchanged.

- [ ] **Step 6: Commit**

```
git add specgen/scan.py specgen/secfile.py specgen/manifest.py specgen/generate.py tests/
git commit -m "Scanner-level note masking: note brackets marked in_note, never merge or edit"
```

---

### Task 2: Markup-split adjacency

`[a]</SPT>[b]` renders as adjacent brackets in SpecsIntact (the tag is invisible) — merge such spans into one choice group. Structural tags (`<OLI>` etc.) still split.

**Files:**
- Modify: `specgen/scan.py` (adjacency test in `scan_groups`)
- Create: `tests/test_scan_adjacency.py`

**Interfaces:**
- Produces: module constant `_INVISIBLE_GAP_RE` in `scan.py`; behavior change only, no signature changes.

- [ ] **Step 1: Write the failing tests**

`tests/test_scan_adjacency.py`:

```python
from specgen.scan import scan_groups


def test_invisible_markup_merges():
    src = "<SEC>[alpha]</SPT>[beta]</SEC>"
    groups, _, _ = scan_groups(src)
    assert len(groups) == 1
    assert [o.text for o in groups[0].options] == ["alpha", "beta"]


def test_tai_gap_merges():
    src = '<SEC>[alpha]<TAI OPT="NAVY">[beta]</TAI></SEC>'
    groups, _, _ = scan_groups(src)
    assert len(groups) == 1


def test_structural_tag_still_splits():
    src = "<SEC>[alpha]<OLI>[beta]</OLI></SEC>"
    groups, _, _ = scan_groups(src)
    assert len(groups) == 2
```

(Delete the stray first `src =` line in the first test before committing — keep only the corpus-real shape.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_scan_adjacency.py -v`
Expected: first two FAIL (`len(groups) == 2`), third PASS.

- [ ] **Step 3: Implement**

In `specgen/scan.py` add next to `_BLANK_RE`:

```python
# Tags that are invisible in the rendered section: a gap made only of these
# (and spaces/tabs) leaves two bracket spans visually adjacent — one choice.
_INVISIBLE_GAP_RE = re.compile(
    r"^(?:[ \t]|</?(?:SPT|TAI|MET|ENG)(?:\s[^>]*)?>)+$"
)
```

In `scan_groups`, replace the adjacency raw-gap condition:

```python
            gap = src[offs[end - 1] + 1 : offs[k]] if k < n else ""
            if (
                k < n
                and text[k] == "["
                and mask[k] == in_note
                and (gap.strip(" \t") == "" or _INVISIBLE_GAP_RE.match(gap))
            ):
                i = k
```

Note: when the merged group's span now encloses an unbalanced tag slice (e.g. a lone `</SPT>`), the existing `balanced()` check correctly flags `safe=False`, so the generator will not splice it — it lands in `.unresolved.md`. That is the intended conservative behavior for v1.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scan_adjacency.py tests/test_scan_notes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add specgen/scan.py tests/test_scan_adjacency.py
git commit -m "Merge bracket spans separated only by render-invisible markup"
```

---

### Task 3: Submittal-classification decisions

`[; <SUB>G<TAI OPT="ARMY">, [_____]</TAI></SUB>]` becomes a typed `submittal-review` decision (keep/remove the Government-review flag + fill the reviewer office), labeled with its submittal item.

**Files:**
- Modify: `specgen/scan.py` (recognizer after group construction)
- Modify: `specgen/manifest.py` (label; kind counting)
- Modify: `specgen/generate.py` (office fill on keep)
- Modify: `specgen/answers.py` (`read_answers_json` office passthrough; xlsx kind fill + display)
- Create: `tests/test_submittal_review.py`

**Interfaces:**
- Produces: `Group.kind` may be `"submittal-review"`. Manifest decisions gain `"label": str` (submittal item name, empty for other kinds). Answer records may carry `"office": str`. `generate` fills the nested `[_____]` with `office` when the answer is `keep`.

- [ ] **Step 1: Write the failing tests**

`tests/test_submittal_review.py`:

```python
from pathlib import Path

from specgen import secfile
from specgen.answers import read_answers_json
from specgen.generate import generate
from specgen.scan import scan_groups

SUBREV = (
    "<SEC><SPT =1.2><TTL>SUBMITTALS</TTL>"
    "<SUB>SD-03 Product Data</SUB><BRK/>"
    "<SUB>Controls</SUB>"
    '[; <SUB>G<TAI OPT="ARMY">, [_____]</TAI></SUB>]<BRK/>'
    "</SPT></SEC>"
)


def test_recognizer():
    groups, _, _ = scan_groups(SUBREV)
    subrev = [g for g in groups if g.kind == "submittal-review"]
    assert len(subrev) == 1
    assert subrev[0].safe


def test_generate_keep_with_office(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SUBREV.encode(secfile.ENCODING))
    groups, _, _ = scan_groups(SUBREV)
    gid = next(g.gid for g in groups if g.kind == "submittal-review")
    out = tmp_path / "out.sec"
    generate(master, {}, {gid: {"answer": "keep", "office": "AE", "notes": ""}}, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "; <SUB>G" in result and ", AE" in result
    assert "[_____]" not in result


def test_json_office_passthrough(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        '{"answers": {"BRK-0001": {"answer": "keep", "office": "AE"}}}',
        encoding="utf-8",
    )
    _, answers = read_answers_json(p)
    assert answers["BRK-0001"]["office"] == "AE"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_submittal_review.py -v`
Expected: all 3 FAIL (kind is `optional`; `[_____]` survives; no `office` key).

- [ ] **Step 3: Implement**

`specgen/scan.py` — add near `_BLANK_RE`:

```python
# "[; <SUB>G, [_____]</SUB>]" (G or S, optional <TAI> wrapping): the
# submittal-classification idiom — keep/remove the reviewer flag and
# fill in the reviewing office.
_SUBREV_RE = re.compile(r"^;?\s*<SUB>\s*[GS]\b")
```

In `scan_groups`, right after the `groups.append(Group(...))` call, retype the group:

```python
            g = groups[-1]
            if g.kind == "optional" and len(g.options) == 1:
                raw_opt = src[g.options[0].src_start : g.options[0].src_end]
                if _SUBREV_RE.match(raw_opt.strip()):
                    g.kind = "submittal-review"
```

`specgen/manifest.py`:
- Kind counting (`kinds = {"choice": 0, ...}` block) becomes tolerant:

```python
    kinds: dict[str, int] = {}
    for d in decisions:
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
```

and the counts expansion becomes `**{f"kind_{k}": v for k, v in sorted(kinds.items())}`.
- Label: before the decisions loop, collect submittal-name spans; inside the loop set `label`:

```python
    sub_spans = [
        (s.src_end, _WS_RE.sub(" ", s.text()).strip()) for s in root.iter("SUB")
    ]
    sub_spans.sort()
```

inside the decision dict:

```python
                "label": (
                    next(
                        (t for e, t in reversed(sub_spans) if e <= g.src_start),
                        "",
                    )
                    if g.kind == "submittal-review"
                    else ""
                ),
```

`specgen/generate.py` — in the `low == "keep"` branch:

```python
        elif low == "keep":  # optional: keep text, drop brackets
            after = src[g.options[0].src_start : g.options[0].src_end]
            action = "kept (brackets removed)"
            if g.kind == "submittal-review" and entry.get("office"):
                after = re.sub(
                    r"\[[^][]*\]", lambda _m: entry["office"], after, count=1
                )
                action = f"kept; reviewer office = {entry['office']}"
```

Also relax the `keep`-guard at the top of the loop (`low == "keep" and g.kind != "optional"`) to `g.kind not in ("optional", "submittal-review")`.

`specgen/answers.py`:
- `read_answers_json`: after computing `ans, notes`, also read `office`:

```python
        office = str(v.get("office", "")).strip() if isinstance(v, dict) else ""
        if ans or notes:
            rec = {"answer": ans, "notes": notes}
            if office:
                rec["office"] = office
            answers[str(gid).strip()] = rec
```

- `_KIND_FILL` gains `"submittal-review": PatternFill("solid", fgColor="DDEBF7")`.
- In `write_workbook`, the options-display chain gains a branch before the generic `else`:

```python
        elif d["kind"] == "submittal-review":
            opts_display = (
                "keep = Government-reviewed (G); in the HTML page you can also "
                "set the reviewer office; delete = for-information-only"
            )
```

and the `keep_del` validation is applied for this kind too (`if d["kind"] in ("optional", "submittal-review"):`).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add specgen/scan.py specgen/manifest.py specgen/generate.py specgen/answers.py tests/test_submittal_review.py
git commit -m "Typed submittal-review decisions with reviewer-office fill"
```

---

### Task 4: Unit-system decision (SI vs IP)

One Project Profile answer resolves every `<MET>/<ENG>` pair: `generate` deletes the unchosen elements; the manifest exposes pair counts and char spans so the HTML can render the choice.

**Files:**
- Modify: `specgen/answers.py` (UNITS_KEY; workbook row; readers accept si/ip)
- Modify: `specgen/manifest.py` (counts + `unit_spans`)
- Modify: `specgen/generate.py` (element removal stage + redline entry)
- Create: `tests/test_units.py`

**Interfaces:**
- Produces: `answers.UNITS_KEY = "UNITS OF MEASURE (SI/IP)"`; profile values for it are `"si"` or `"ip"`. Manifest gains `counts.unit_pairs: int` and top-level `"unit_spans": [{"met": [cs, ce], "eng": [cs, ce]}]` (char-stream spans of element *content*; a missing partner is `null`). `generate` removes all `<ENG>` elements when `si`, all `<MET>` when `ip`.

- [ ] **Step 1: Write the failing tests**

`tests/test_units.py`:

```python
from specgen import secfile
from specgen.answers import UNITS_KEY, read_answers_json
from specgen.generate import generate
from specgen.manifest import build_manifest

UNITS = (
    "<SEC><TXT>capacity of<MET> 500 kW</MET><ENG> 142 tons</ENG> minimum, "
    "weight<MET> 23 kg</MET><ENG> 50 pounds</ENG>.</TXT></SEC>"
)


def test_manifest_unit_spans(tmp_path):
    p = tmp_path / "u.SEC"
    p.write_bytes(UNITS.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    assert m["counts"]["unit_pairs"] == 2
    s = m["unit_spans"][0]
    assert m["text"][s["met"][0] : s["met"][1]] == " 500 kW"
    assert m["text"][s["eng"][0] : s["eng"][1]] == " 142 tons"


def test_generate_keeps_si(tmp_path):
    p = tmp_path / "u.SEC"
    p.write_bytes(UNITS.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    generate(p, {UNITS_KEY: "si"}, {}, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "500 kW" in result and "142 tons" not in result
    assert "<ENG>" not in result and "</ENG>" not in result


def test_readers_accept_units(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        '{"profile": {"%s": "si", "ARMY": "remove"}}' % UNITS_KEY,
        encoding="utf-8",
    )
    profile, _ = read_answers_json(p)
    assert profile[UNITS_KEY] == "si"
    assert profile["ARMY"] == "remove"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_units.py -v`
Expected: all 3 FAIL (`KeyError: 'unit_pairs'`, ENG survives, profile filter drops `si`).

- [ ] **Step 3: Implement**

`specgen/answers.py`:

```python
# Special Profile-sheet key: SI vs inch-pound units — one answer resolves
# every <MET>/<ENG> pair in the section.
UNITS_KEY = "UNITS OF MEASURE (SI/IP)"
```

- In `read_answers_json` and `read_workbook`, widen the accepted profile values from `("keep", "remove")` to `("keep", "remove", "si", "ip")`.
- In `write_workbook`'s Profile sheet, after the tailoring rows and before the plural row:

```python
    units_dv = DataValidation(
        type="list", formula1='"SI,IP"', allow_blank=True, showErrorMessage=False
    )
    ps.add_data_validation(units_dv)
    if manifest["counts"].get("unit_pairs"):
        ps.append([UNITS_KEY, manifest["counts"]["unit_pairs"], "", ""])
        units_dv.add(ps.cell(row=prow, column=4))
        prow += 1
```

`specgen/manifest.py` — add `import bisect` at top; before the return, build spans:

```python
    def _content_span(el: Element) -> list[int] | None:
        if el.self_closing:
            return None
        a = bisect.bisect_left(_offs, el.src_start + len(el.open_raw))
        b = bisect.bisect_left(_offs, el.src_end - len(el.close_raw))
        return [a, b]

    unit_spans: list[dict] = []
    def _walk_units(el: Element) -> None:
        kids = [c for c in el.children if isinstance(c, Element)]
        i = 0
        while i < len(kids):
            c = kids[i]
            if c.name == "MET":
                eng = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].name == "ENG" else None
                unit_spans.append(
                    {"met": _content_span(c),
                     "eng": _content_span(eng) if eng is not None else None}
                )
                if eng is not None:
                    i += 2
                    continue
            elif c.name == "ENG":
                unit_spans.append({"met": None, "eng": _content_span(c)})
            else:
                _walk_units(c)
            i += 1
    _walk_units(root)
```

Add to counts: `"unit_pairs": len(unit_spans),` and to the returned dict: `"unit_spans": unit_spans,`. (Rename the existing `_offs` unpack so it's usable: `groups, stream, _offs = scan_groups(sec.source)` already binds it.)

`specgen/generate.py` — import `UNITS_KEY` from `.answers`; after the tailoring-removal stage and before the rescan:

```python
    # --- unit-system resolution (on the edited source) ---
    units = profile.get(UNITS_KEY, "")
    removed_units = 0
    if units in ("si", "ip"):
        drop = "ENG" if units == "si" else "MET"
        tmp = master.parent / (master.name + ".gen.tmp")
        tmp.write_bytes(src.encode(secfile.ENCODING))
        tree = secfile.parse(tmp)
        spans = sorted(
            ((el.src_start, el.src_end) for el in tree.root.iter(drop)),
            key=lambda s: -s[0],
        )
        for start, end in spans:
            src = src[:start] + src[end:]
            removed_units += 1
        tmp.unlink(missing_ok=True)
        if removed_units:
            redline.append(
                {
                    "id": "UNITS",
                    "kind": "units",
                    "action": f"kept {'SI' if units == 'si' else 'IP'} units; "
                    f"removed {removed_units} <{drop}> elements",
                    "answer": units,
                    "notes": "",
                    "before": "",
                    "after": "",
                }
            )
```

Add `"units_removed": removed_units,` to `summary`. In the `.redline.md` builder, exclude the units entry from `brk` (`c["kind"] not in ("tailoring", "units")`) and, next to the plural line, add:

```python
    units_c = [c for c in redline if c["kind"] == "units"]
    if units_c:
        md += [f"_{units_c[0]['action']}._", ""]
```

Note: `<MET>/<ENG>` inside bracket *options* were already spliced (or kept) by the bracket stage; the element removal here operates on whatever instances remain, which is correct in both cases.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add specgen/answers.py specgen/manifest.py specgen/generate.py tests/test_units.py
git commit -m "Project-level SI/IP units decision resolving all MET/ENG pairs"
```

---

### Task 5: Coverage audit — `specgen audit`

The completeness invariant: every decision signal is `surfaced`, `excluded:<rule>`, or `unknown` (→ non-zero exit). `html`/`generate` gate on it.

**Files:**
- Create: `specgen/audit.py`
- Modify: `specgen/cli.py` (new subcommand; gating in `cmd_html`/`cmd_generate` with `--force`)
- Create: `scripts/audit_corpus.py`
- Create: `tests/test_audit.py`

**Interfaces:**
- Produces: `audit.audit_source(src: str, root: Element) -> dict` with keys `signals: dict[str, dict[str, int]]` (signal type → bucket → count) and `unknowns: list[dict]` (`{"type", "offset", "context"}`). `audit.audit_file(path) -> dict` convenience. CLI `python -m specgen audit <file> [--json]`, exit 1 when `unknowns`.

- [ ] **Step 1: Write the failing tests**

`tests/test_audit.py`:

```python
from specgen import secfile
from specgen.audit import audit_source

CLEAN = (
    "<SEC><NTE>choose [x] wisely</NTE>"
    '<TAI OPT="ARMY"><TXT>army text</TXT></TAI>'
    "<TXT>Provide [scroll][screw] units rated<MET> 5 kW</MET><ENG> 2 tons</ENG> "
    "with [_____] starts per hour.</TXT></SEC>"
)

STRAY = "<SEC><TXT>orphan ] bracket</TXT></SEC>"


def test_clean_source_fully_attributed():
    sec = secfile.parse_source(CLEAN)
    report = audit_source(sec.source, sec.root)
    assert report["unknowns"] == []
    b = report["signals"]["bracket-group"]
    assert b["surfaced"] == 2 and b["excluded:note-text"] == 1
    assert report["signals"]["tailoring"]["surfaced"] == 1
    assert report["signals"]["units"]["surfaced"] == 2


def test_stray_bracket_is_unknown():
    sec = secfile.parse_source(STRAY)
    report = audit_source(sec.source, sec.root)
    assert len(report["unknowns"]) == 1
    assert report["unknowns"][0]["type"] == "stray-bracket"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'specgen.audit'`.

- [ ] **Step 3: Implement `specgen/audit.py`**

```python
"""Coverage audit: every decision signal in a section must be attributed.

Buckets: surfaced (appears in the manifest / HTML), excluded:<named-rule>
(note-text, contractor-form-blank, header-metadata), or unknown — in which
case the section may contain a decision the tooling would silently miss,
so audit exits non-zero and html/generate refuse to run without --force.
"""

from __future__ import annotations

import re

from .scan import context_excerpt, scan_groups, text_stream
from .secfile import Element

_UNDERSCORE_RE = re.compile(r"_{3,}")


def audit_source(src: str, root: Element) -> dict:
    groups, text, offs = scan_groups(src)
    _, _, mask = text_stream(src)
    signals: dict[str, dict[str, int]] = {}
    unknowns: list[dict] = []

    def tally(sig: str, bucket: str) -> None:
        signals.setdefault(sig, {})[bucket] = (
            signals.setdefault(sig, {}).get(bucket, 0) + 1
        )

    def unknown(sig: str, char_pos: int) -> None:
        tally(sig, "unknown")
        unknowns.append(
            {
                "type": sig,
                "offset": offs[char_pos] if char_pos < len(offs) else -1,
                "context": context_excerpt(text, char_pos, char_pos + 1),
            }
        )

    # 1. bracket groups
    covered = [False] * len(text)
    for g in groups:
        for c in range(g.char_start, g.char_end):
            covered[c] = True
        if g.in_note:
            tally("bracket-group", "excluded:note-text")
        elif g.kind == "submittal-review":
            tally("submittal-classification", "surfaced")
        else:
            tally("bracket-group", "surfaced")

    # 2. stray bracket characters outside any group
    for i, ch in enumerate(text):
        if ch in "[]" and not covered[i]:
            if mask[i]:
                tally("stray-bracket", "excluded:note-text")
            else:
                unknown("stray-bracket", i)

    # 3. bare underscore blanks outside brackets
    first_part = next(root.iter("PRT"), None)
    body_start = first_part.src_start if first_part is not None else 0
    for m in _UNDERSCORE_RE.finditer(text):
        if covered[m.start()]:
            continue  # inside a surfaced bracket group
        if mask[m.start()]:
            tally("bare-blank", "excluded:note-text")
        elif offs[m.start()] < body_start:
            tally("bare-blank", "excluded:header-metadata")
        else:
            tally("bare-blank", "excluded:contractor-form-blank")

    # 4. tailoring and units: surfaced via the Project Profile
    for _ in root.iter("TAI"):
        tally("tailoring", "surfaced")
    for name in ("MET", "ENG"):
        for _ in root.iter(name):
            tally("units", "surfaced")

    # 5. submittal classifications that did NOT get recognized
    for m in re.finditer(r"<SUB>\s*[GS]\s*[<,;\]]", src):
        # inside a recognized group?
        if not any(
            g.kind == "submittal-review" and g.src_start <= m.start() < g.src_end
            for g in groups
        ):
            tally("submittal-classification", "unknown")
            unknowns.append(
                {
                    "type": "unrecognized-submittal-classification",
                    "offset": m.start(),
                    "context": src[max(0, m.start() - 60) : m.start() + 60],
                }
            )
    return {"signals": signals, "unknowns": unknowns}


def audit_file(path) -> dict:
    from . import secfile

    sec = secfile.parse(path)
    return audit_source(sec.source, sec.root)
```

`specgen/cli.py` — add:

```python
def cmd_audit(args) -> int:
    from .audit import audit_file

    report = audit_file(args.file)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for sig, buckets in sorted(report["signals"].items()):
            row = " · ".join(f"{b}={n}" for b, n in sorted(buckets.items()))
            print(f"{sig:32s} {row}")
        for u in report["unknowns"]:
            print(f"UNKNOWN {u['type']} @ {u['offset']}: {u['context']}")
    if report["unknowns"]:
        print(f"FAIL: {len(report['unknowns'])} unattributed signal(s)")
        return 1
    print("OK: every decision signal attributed")
    return 0
```

Wire into `main()`'s command list as `("audit", cmd_audit)` with `sp.add_argument("--json", action="store_true")` for the audit parser, and add `sp.add_argument("--force", action="store_true")` for `html` and `generate`. At the top of `cmd_html` and `cmd_generate`:

```python
    from .audit import audit_file

    report = audit_file(args.file)
    if report["unknowns"]:
        for u in report["unknowns"]:
            print(f"UNKNOWN {u['type']} @ {u['offset']}: {u['context']}")
        if not args.force:
            print("Refusing: section has unattributed decision signals "
                  "(rerun with --force to proceed anyway)")
            return 1
        print("WARNING: proceeding despite unattributed signals (--force)")
```

`scripts/audit_corpus.py`:

```python
"""Regression gate: audit + round-trip every master in masters/Specifications."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specgen import secfile
from specgen.audit import audit_source

CORPUS = Path(__file__).resolve().parent.parent / "masters" / "Specifications"


def main() -> int:
    failures = 0
    for f in sorted(CORPUS.glob("*.SEC")):
        sec = secfile.parse(f)
        problems = []
        if not sec.roundtrips():
            problems.append("ROUNDTRIP-FAIL")
        report = audit_source(sec.source, sec.root)
        if report["unknowns"]:
            problems.append(f"{len(report['unknowns'])} unknown signal(s)")
        status = "OK " if not problems else "FAIL"
        print(f"{status} {f.name:24s} {'; '.join(problems)}")
        for u in report["unknowns"]:
            print(f"     UNKNOWN {u['type']} @ {u['offset']}: {u['context'][:100]}")
        failures += bool(problems)
    print(f"\n{failures} of {len(list(CORPUS.glob('*.SEC')))} sections failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, then the corpus**

Run: `python -m pytest tests/test_audit.py -v`
Expected: PASS.
Run: `python scripts/audit_corpus.py`
Expected: mostly OK. **Investigate every FAIL now**: each is either (a) a real signal type we missed — add a scanner rule + test, or (b) a legitimate new exclusion — add a named rule + test. Do not proceed with unexplained unknowns; this step is the point of the whole task. (Known candidates from the survey: the pipe-form `(|____|)` and `&lt;___&gt;` conventions quoted in QA-form text — expected to land in `excluded:note-text` or `contractor-form-blank`; verify.)

- [ ] **Step 5: Commit**

```
git add specgen/audit.py specgen/cli.py scripts/audit_corpus.py tests/test_audit.py
git commit -m "Coverage audit: every decision signal surfaced, excluded by rule, or fatal"
```

---

### Task 6: Generator `--revisions` output

Emit `.revisions.sec` with every change wrapped in SpecsIntact `<DEL>/<ADD>` markup, verified by two identities: resolve(revisions) == clean output; revert(revisions) == master.

**Files:**
- Modify: `specgen/generate.py` (parallel revisions source; wrap helpers; verification)
- Modify: `specgen/cli.py` (`--revisions` flag on generate)
- Create: `tests/test_revisions.py`

**Interfaces:**
- Produces: `generate(..., revisions: bool = False)`; when True writes `<out>.revisions.sec` next to `out_sec`. Module functions `resolve_revisions(source: str) -> str` and `revert_revisions(source: str) -> str` (also used by tests and later by Phase-C checks).

- [ ] **Step 1: Write the failing tests**

`tests/test_revisions.py`:

```python
from specgen import secfile
from specgen.answers import UNITS_KEY
from specgen.generate import generate, resolve_revisions, revert_revisions

SRC = (
    "<SEC><TXT>Provide [scroll][screw] compressors "
    "rated<MET> 5 kW</MET><ENG> 2 tons</ENG> with [_____] starts "
    "[and vibration isolation].</TXT>"
    '<TAI OPT="ARMY"><TXT2>army-only text</TXT2></TAI></SEC>'
)

ANSWERS = {
    "BRK-0001": {"answer": "1", "notes": ""},       # choose scroll
    "BRK-0002": {"answer": "6", "notes": ""},       # fill blank
    "BRK-0003": {"answer": "keep", "notes": ""},    # keep optional
}
PROFILE = {"ARMY": "remove", UNITS_KEY: "si"}


def test_revisions_identities(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    generate(master, PROFILE, ANSWERS, out, revisions=True)
    clean = out.read_bytes().decode(secfile.ENCODING)
    rev = (tmp_path / "out.revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert "<DEL>" in rev and "<ADD>" in rev
    assert resolve_revisions(rev) == clean
    assert revert_revisions(rev) == SRC


def test_clean_output_unchanged_by_flag(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    out1, out2 = tmp_path / "a.sec", tmp_path / "b.sec"
    generate(master, PROFILE, ANSWERS, out1, revisions=False)
    generate(master, PROFILE, ANSWERS, out2, revisions=True)
    assert out1.read_bytes() == out2.read_bytes()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_revisions.py -v`
Expected: FAIL — `ImportError` (no `resolve_revisions`), `TypeError` (no `revisions` kwarg).

- [ ] **Step 3: Implement in `specgen/generate.py`**

Transforms (module level):

```python
def _strip_revisions(source: str, drop: str, unwrap: str) -> str:
    """Serialize with <drop> elements removed and <unwrap> elements replaced
    by their children. Both are only ever wrapped around balanced spans."""
    sec = secfile.parse_source(source)

    def emit(node) -> str:
        if not isinstance(node, secfile.Element):
            return node.serialize()
        if node.name == drop:
            return ""
        if node.name == unwrap:
            return "".join(emit(c) for c in node.children)
        if node.self_closing:
            return node.open_raw
        inner = "".join(emit(c) for c in node.children)
        return f"{node.open_raw}{inner}{node.close_raw}"

    parts = [n.serialize() for n in sec.prolog]
    parts.append(emit(sec.root))
    parts.extend(n.serialize() for n in sec.epilog)
    return "".join(parts)


def resolve_revisions(source: str) -> str:
    """Accept all changes: drop <DEL> content, keep <ADD> content."""
    return _strip_revisions(source, drop="DEL", unwrap="ADD")


def revert_revisions(source: str) -> str:
    """Reject all changes: keep <DEL> content, drop <ADD> content."""
    return _strip_revisions(source, drop="ADD", unwrap="DEL")
```

Wrap helper for the bracket stage — precise per action so revert is exact:

```python
def _rev_wrap(g, src: str, low: str, after: str, picked, office: str) -> str:
    before = src[g.src_start : g.src_end]
    if low == "delete":
        return f"<DEL>{before}</DEL>"
    if low == "keep":
        content = src[g.options[0].src_start : g.options[0].src_end]
        if office:
            content = re.sub(
                r"\[[^][]*\]",
                lambda m: f"<DEL>{m.group(0)}</DEL><ADD>{office}</ADD>",
                content,
                count=1,
            )
        return f"<DEL>[</DEL>{content}<DEL>]</DEL>"
    if picked is not None:
        parts, keep = [], set(picked)
        for i, o in enumerate(g.options):
            body = src[o.src_start : o.src_end]
            if i in keep:
                parts.append(f"<DEL>[</DEL>{body}<DEL>]</DEL>")
            else:
                parts.append(f"<DEL>[{body}]</DEL>")
        # Inter-option gaps are DEL-wrapped so resolve() joins picked bodies
        # exactly like the clean output does. Gaps are whitespace-only here:
        # markup-gap groups are always safe=False and never reach the splicer.
        out, pos = [], g.src_start
        for i, o in enumerate(g.options):
            gap = src[pos : o.src_start - 1]  # up to the '['
            if gap:
                out.append(f"<DEL>{gap}</DEL>")
            out.append(parts[i])
            pos = o.src_end + 1  # past the ']'
        tail = src[pos : g.src_end]
        if tail:
            out.append(f"<DEL>{tail}</DEL>")
        return "".join(out)
    return f"<DEL>{before}</DEL><ADD>{after}</ADD>"  # custom / fill-in
```

In `generate()`:
- Signature: `def generate(master, profile, answers, out_sec, revisions: bool = False) -> dict:`
- After `src = ...parse...source`, add `rev = src`.
- In the bracket loop: at the top of the loop body add `picked_for_rev = None`; in the choice branch (`if picked is not None:`) add `picked_for_rev = picked`; and right before `src = src[: g.src_start] + after + src[g.src_end :]`:

```python
        if revisions:
            office = (
                entry.get("office", "") if g.kind == "submittal-review" else ""
            )
            wrapped = _rev_wrap(g, rev, low, after, picked_for_rev, office)
            rev = rev[: g.src_start] + wrapped + rev[g.src_end :]
```

(Reverse document order keeps offsets valid in `rev` exactly as in `src` — both strings are identical above every not-yet-spliced offset.)
- Tailoring stage: after each clean-source splice loop iteration set, mirror on `rev` by *wrapping* instead of removing. Add inside the `while True:` loop, operating on `rev` with its own parse (skip blocks already inside a DEL):

```python
            if revisions:
                rtmp = master.parent / (master.name + ".rev.tmp")
                rtmp.write_bytes(rev.encode(secfile.ENCODING))
                rtree = secfile.parse(rtmp)
                rspans = [
                    (t.src_start, t.src_end)
                    for t in rtree.root.iter("TAI")
                    if removable(t.attrs.get("OPT", ""))
                    and not any(a.name == "DEL" for a in t.ancestors())
                ]
                rspans = [
                    s for s in rspans
                    if not any(o[0] < s[0] and s[1] <= o[1] for o in rspans if o != s)
                ]
                for start, end in sorted(rspans, key=lambda s: -s[0]):
                    rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
                rtmp.unlink(missing_ok=True)
```

- Units stage: clean source splices out the dropped elements (Task 4 code); when `revisions`, mirror on `rev` right after the clean splice loop:

```python
        if revisions:
            rtmp = master.parent / (master.name + ".rev.tmp")
            rtmp.write_bytes(rev.encode(secfile.ENCODING))
            rtree = secfile.parse(rtmp)
            rspans = sorted(
                (
                    (el.src_start, el.src_end)
                    for el in rtree.root.iter(drop)
                    if not any(a.name == "DEL" for a in el.ancestors())
                ),
                key=lambda s: -s[0],
            )
            for start, end in rspans:
                rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
            rtmp.unlink(missing_ok=True)
```
- Verification, after the existing clean-file checks and before returning:

```python
    if revisions:
        original = secfile.parse(master).source
        if resolve_revisions(rev) != src:
            raise GenerateError("revisions do not resolve to the clean output")
        if revert_revisions(rev) != original:
            raise GenerateError("revisions do not revert to the master")
        rev_path = out_sec.with_suffix(".revisions.sec")
        rev_path.write_bytes(rev.encode(secfile.ENCODING))
        ET.parse(rev_path)  # well-formed
        summary["revisions_output"] = str(rev_path)
```

`specgen/cli.py` — `cmd_generate` passes it through:

```python
    summary = generate(args.file, profile, ans, args.out, revisions=args.revisions)
```

with `sp.add_argument("--revisions", action="store_true")` on the generate parser.

Known risk (accepted in the spec): the official XSD may not allow `<DEL>` wrapping block-level elements like `<TAI>`; Phase C (opening in SpecsIntact) is the arbiter. The resolve/revert identities guarantee the file is at least structurally sound and information-preserving.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.
Run the end-to-end pilot check:

```
python -m specgen generate "masters/23 64 10.SEC" --answers "out/23 64 10.answers.maxwell.json" -o out/generated/23_64_10.sec --revisions
```

Expected: summary JSON includes `revisions_output`; open `out/generated/23_64_10.revisions.sec` and spot-check a `<DEL>[scroll]</DEL>`-style wrap.

- [ ] **Step 5: Commit**

```
git add specgen/generate.py specgen/cli.py tests/test_revisions.py
git commit -m "generate --revisions: SpecsIntact ADD/DEL tracked-changes output with resolve/revert verification"
```

---

### Task 7: Live redline rendering in the HTML page

Answered decisions show `<s>old</s><ins>new</ins>` in the document view instead of silently replacing text; a header toggle switches Redline ⇄ Clean.

**Files:**
- Modify: `specgen/htmlpage.py` (CSS, header button, `updateMark`, state)
- Create: `tests/test_htmlpage.py`

**Interfaces:**
- Consumes: existing `DATA.decisions[*].char_start/char_end`, `eff()`, `resolvedText()`.
- Produces: page state gains `state.view: "redline" | "clean"` (persisted); mark rendering contract used by Task 8.

- [ ] **Step 1: Write the failing test** (string-level: the template is a single file; browser check is a manual step)

`tests/test_htmlpage.py`:

```python
from specgen import secfile
from specgen.htmlpage import write_html
from specgen.manifest import build_manifest

SRC = "<SEC><TXT>Provide [scroll][screw] compressors.</TXT></SEC>"


def _page(tmp_path):
    p = tmp_path / "t.SEC"
    p.write_bytes(SRC.encode(secfile.ENCODING))
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse(p)), out)
    return out.read_text(encoding="utf-8")


def test_redline_hooks_present(tmp_path):
    html = _page(tmp_path)
    assert 'id="btnView"' in html          # toggle button
    assert "state.view" in html            # persisted view mode
    assert "renderRedline" in html         # redline mark renderer
    assert "#doc mark s" in html           # strikethrough CSS
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_htmlpage.py -v`
Expected: FAIL on all four asserts.

- [ ] **Step 3: Implement in `specgen/htmlpage.py`**

CSS additions (after the `#doc mark.active` rule):

```css
#doc mark s { color: var(--del-ink); background: var(--del);
  text-decoration: line-through; font-weight: 400; border-radius: 3px; }
#doc mark ins { color: var(--done-ink); background: var(--done);
  text-decoration: underline; font-weight: 600; border-radius: 3px; }
#doc mark s.fold { cursor: pointer; font-style: italic; }
```

Header: add after the `btnNext` button:

```html
  <button id="btnView">Redline view: on</button>
```

JS — state gains the view flag (in the initial `state` literal): `let state = { profile: {}, answers: {}, view: "redline" };`. Replace the answered branch of `updateMark` with a call to a new renderer, and wire the toggle:

```js
function renderRedline(m, d, txt) {
  const orig = DATA.text.slice(d.char_start, d.char_end);
  if (state.view !== "redline") {
    if (txt === null) { m.classList.add("deleted"); m.textContent = "deleted"; }
    else { m.textContent = txt; }
    return;
  }
  const del = orig.length > 200
    ? `<s class="fold" data-full="1">${esc(orig.slice(0, 80))}… ⟨${orig.length} chars removed — click⟩</s>`
    : `<s>${esc(orig)}</s>`;
  m.innerHTML = txt === null ? del : del + `<ins>${esc(txt)}</ins>`;
  const f = m.querySelector("s.fold");
  if (f) f.onclick = ev => { ev.stopPropagation(); f.outerHTML = `<s>${esc(orig)}</s>`; };
}
```

In `updateMark`, the `else` (answered) branch becomes:

```js
  } else {
    const txt = resolvedText(d, e.a);
    cls.push("answered");
    m.className = cls.join(" ");
    m.title = "answered — click to change";
    renderRedline(m, d, txt);
    return;
  }
```

(keep the existing `m.className = cls.join(" ")` at the end for the unanswered path). Toggle wiring next to the other header handlers:

```js
document.getElementById("btnView").onclick = () => {
  state.view = state.view === "redline" ? "clean" : "redline";
  document.getElementById("btnView").textContent =
    "Redline view: " + (state.view === "redline" ? "on" : "off");
  save(); refresh();
};
```

and on load, after `renderProfile()`: set the button text from `state.view`.

- [ ] **Step 4: Run test + manual browser check**

Run: `python -m pytest tests/test_htmlpage.py -v` — PASS.
Run: `python -m specgen html "masters/23 64 10.SEC" -o out/23_64_10.decisions.html`, open the file in a browser, answer a choice, a blank, and an optional-delete; confirm red strikethrough + green additions appear, the fold expands on click, and the toggle restores clean view. Re-open the page: view mode and redlines persist.

- [ ] **Step 5: Commit**

```
git add specgen/htmlpage.py tests/test_htmlpage.py
git commit -m "Live redline document view with clean-view toggle"
```

---

### Task 8: HTML — profile-driven doc (tailoring/units), submittal panel, note guidance, export gate

**Files:**
- Modify: `specgen/manifest.py` (add `tailoring_spans`, per-decision `note_guidance`)
- Modify: `specgen/htmlpage.py` (nested doc renderer; profile rows for units; submittal-review panel; export confirm; note details)
- Extend: `tests/test_htmlpage.py`, `tests/test_submittal_review.py`

**Interfaces:**
- Consumes: `unit_spans` (Task 4), `submittal-review` kind + `label` (Task 3), `answers.UNITS_KEY` (Task 4).
- Produces: manifest keys `tailoring_spans: [{"opt": str, "span": [cs, ce]}]` (content char spans of every TAI block) and per-decision `"note_guidance": str`. Export JSON gains `"unanswered": [ids]` and `"complete": bool`; answer records gain `"office"` for submittal-review.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_htmlpage.py`:

```python
NOTED = (
    "<SEC><NTE><NPR>NOTE: Select scroll for small plants.</NPR></NTE>"
    '<TAI OPT="ARMY"><TXT>army text</TXT></TAI>'
    "<TXT>Provide [scroll][screw] rated<MET> 5 kW</MET><ENG> 2 tons</ENG>.</TXT></SEC>"
)


def test_manifest_spans_and_guidance(tmp_path):
    from specgen.manifest import build_manifest
    p = tmp_path / "n.SEC"
    p.write_bytes(NOTED.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    assert m["tailoring_spans"][0]["opt"] == "ARMY"
    a, b = m["tailoring_spans"][0]["span"]
    assert m["text"][a:b] == "army text"
    body = [d for d in m["decisions"] if not d["in_note"]]
    assert "Select scroll" in body[0]["note_guidance"]


def test_page_has_gate_units_and_notes(tmp_path):
    p = tmp_path / "n.SEC"
    p.write_bytes(NOTED.encode(secfile.ENCODING))
    out = tmp_path / "n.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "UNITS_KEY" in html and "unit_spans" in html
    assert "note_guidance" in html
    assert "unanswered: open" in html   # export gate payload
    assert "tailoring_spans" in html
```

(add `from specgen.manifest import build_manifest` at the top of the file if not present).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_htmlpage.py -v`
Expected: new tests FAIL (`KeyError: 'tailoring_spans'` etc.).

- [ ] **Step 3: Implement manifest side (`specgen/manifest.py`)**

Using `_content_span` from Task 4:

```python
    tailoring_spans = [
        {"opt": t.attrs.get("OPT", "?"), "span": _content_span(t)}
        for t in root.iter("TAI")
        if _content_span(t) is not None
    ]
```

Add `"tailoring_spans": tailoring_spans,` to the return. Note guidance — collect note ends once, then per decision:

```python
    note_ends = sorted(
        (nte.src_end, _WS_RE.sub(" ", nte.text()).strip()[:1500])
        for nte in root.iter("NTE")
    )
```

and inside the decisions loop:

```python
                "note_guidance": next(
                    (t for e, t in reversed(note_ends) if e <= g.src_start), ""
                ),
```

**Implement page side (`specgen/htmlpage.py`).** Key JS changes:

1. `write_html` also injects `__UNITS_KEY__` (import `UNITS_KEY` from `.answers`, mirror the PLURAL_KEY replace). Template: `const UNITS_KEY = __UNITS_KEY__;`

2. `renderProfile` items list gains units (before plural):

```js
  if ((DATA.unit_spans || []).length) items.push({ key: UNITS_KEY,
    meta: DATA.unit_spans.length + " unit pairs",
    labels: ["SI", "IP"], values: ["si", "ip"] });
```

and the row template uses `it.values ? it.values[j] : ["keep","remove"][j]` for `data-v`. Any profile change that touches UNITS_KEY or a tailoring key calls `buildDoc()` (rebuild, since struck spans change).

3. `buildDoc` becomes a nested-span renderer. Spans: decisions (priority 3), removed-tailoring content spans (2), dropped-side unit spans (1). Containment nests; partial overlap drops the lower priority span:

```js
function activeSpans() {
  const spans = ds.map(d => ({ s: d.char_start, e: d.char_end, pri: 3, d }));
  for (const t of DATA.tailoring_spans || []) {
    const names = t.opt.split(",").map(x => x.trim());
    if (names.every(nm => state.profile[nm] === "remove"))
      spans.push({ s: t.span[0], e: t.span[1], pri: 2, tai: t.opt });
  }
  const u = state.profile[UNITS_KEY];
  if (u === "si" || u === "ip")
    for (const pr of DATA.unit_spans || []) {
      const drop = u === "si" ? pr.eng : pr.met;
      if (drop) spans.push({ s: drop[0], e: drop[1], pri: 1, unit: true });
    }
  spans.sort((a, b) => a.s - b.s || b.e - a.e || b.pri - a.pri);
  // drop zero-length, contained-in-equal-or-lower-pri conflicts, partial overlaps
  const out = [], stack = [];
  for (const sp of spans) {
    while (stack.length && stack[stack.length - 1].e <= sp.s) stack.pop();
    const top = stack[stack.length - 1];
    if (top) {
      if (sp.e > top.e) continue;              // partial overlap: drop
      if (sp.pri >= top.pri) continue;         // decision inside decision etc.
      sp.parent = top;
    }
    out.push(sp); stack.push(sp);
  }
  return out;
}

function buildDoc() {
  const doc = document.getElementById("doc");
  const spans = activeSpans();
  const roots = spans.filter(sp => !sp.parent);
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
  for (const sp of roots) {
    html += esc(DATA.text.slice(pos, sp.s));
    html += emit(sp);
    pos = sp.e;
  }
  html += esc(DATA.text.slice(pos));
  doc.innerHTML = html;
  doc.querySelectorAll("mark[data-id]").forEach(m => m.onclick = () => select(m.dataset.id, false));
  doc.querySelectorAll("mark.taicut").forEach(m => m.onclick = () => {
    alert("Tailoring block '" + m.dataset.opt + "' is removed by the Project Profile. Set it back to 'keep' to restore the text.");
  });
  ds.forEach(updateMark);
}
```

CSS: `#doc s.unitcut { color: var(--del-ink); background: var(--del); text-decoration: line-through; }` and `#doc mark.taicut { cursor: pointer; }`. `refresh()` keeps calling `ds.forEach(updateMark)`; profile changes and the view toggle call `buildDoc()` instead. Note: marks inside removed tailoring vanish with the collapse (their `mk-` element does not exist) — `updateMark` already guards `if (!m) return;`. `updateProgress`'s `uniq` filter additionally excludes decisions inside removed tailoring spans:

```js
function inRemovedTai(d) {
  return (DATA.tailoring_spans || []).some(t =>
    t.span[0] <= d.char_start && d.char_end <= t.span[1] &&
    t.opt.split(",").map(x => x.trim()).every(nm => state.profile[nm] === "remove"));
}
```

used as `ds.filter(d => !d.duplicate_of && d.safe && !inRemovedTai(d))`, and in both `gotoNextUnanswered` loops (`!inRemovedTai(d)`).

Accepted v1 limitation: `updateMark` overwrites a mark's inner HTML, so a unit strike nested *inside* a decision mark disappears — the engineer sees both unit variants inside an unanswered bracket until they answer it. Correct output is unaffected (generate resolves brackets first, then units).

4. Submittal-review panel branch in `renderPanel` (before the generic branches):

```js
  } else if (d.kind === "submittal-review") {
    h += `<div class="loc">${esc(d.label || "")}</div>`;
    h += `<div class="hint">Government review flag for this submittal item.</div>`;
    h += `<div class="opts">
      <button data-val="keep" class="${e.a === "keep" ? "on" : ""}">keep — Government-reviewed (G)</button>
      <button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">remove — for information only</button></div>`;
    h += `<div class="freeform"><input type="text" data-office
      placeholder="reviewer office (e.g. AE) — optional"
      value="${esc(own.office || "")}"><button data-act="setoffice">Set</button></div>`;
  }
```

with wiring after the existing handlers:

```js
  const off = p.querySelector("[data-office]");
  const offBtn = p.querySelector("[data-act=setoffice]");
  if (offBtn) offBtn.onclick = () => {
    const cur = state.answers[d.id] || {};
    if (off.value.trim()) cur.office = off.value.trim(); else delete cur.office;
    if (cur.answer || cur.notes || cur.office) state.answers[d.id] = cur;
    else delete state.answers[d.id];
    save(); refresh();
  };
```

`resolvedText` gains: `if (d.kind === "submittal-review" && a === "keep") { const o = (state.answers[d.id] || {}).office; return o ? d.options[0].replace(/\[[^\]]*\]/, o) : d.options[0]; }` — place it before the `a === "keep"` line. Add CSS chip color: `.chip.kind-submittal-review { color: #2563eb; border-color: currentColor; }`.

5. Note guidance in `renderPanel`, after the location line:

```js
  if (d.note_guidance) h += `<details class="panel" style="padding:8px 10px">
    <summary style="cursor:pointer;font-size:12px;color:var(--muted)">Designer note</summary>
    <div style="font-size:12.5px;margin-top:6px">${esc(d.note_guidance)}</div></details>`;
```

6. Export gate — replace the `btnExport` handler body:

```js
document.getElementById("btnExport").onclick = () => {
  const uniq = ds.filter(d => !d.duplicate_of && d.safe && !inRemovedTai(d));
  const open = uniq.filter(d => !eff(d).a).map(d => d.id);
  const profAll = Object.keys(DATA.tailoring_options).length
    + (nPlural ? 1 : 0) + ((DATA.unit_spans || []).length ? 1 : 0);
  const profOpen = profAll - Object.keys(state.profile).length;
  if (open.length || profOpen > 0) {
    const list = open.slice(0, 15).join(", ") + (open.length > 15 ? " …" : "");
    if (!confirm(`${open.length} decision(s) and ${profOpen} profile setting(s) are still unanswered:\n${list}\n\nExport anyway? They will be flagged for engineer review, never defaulted.`))
      return;
  }
  const payload = { section: DATA.section, title: DATA.title,
    revision: DATA.revision, exported: new Date().toISOString(),
    complete: open.length === 0 && profOpen <= 0,
    unanswered: open,
    profile: state.profile, answers: state.answers };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)],
    { type: "application/json" }));
  a.download = DATA.section.replace(/^SECTION\s+/i, "") + ".answers.json";
  a.click();
};
```

(`read_answers_json` ignores the extra keys — no change needed there.)

- [ ] **Step 4: Run tests + manual browser check**

Run: `python -m pytest tests/ -v` — all PASS.
Regenerate `out/23_64_10.decisions.html`, open it, and verify: units row appears and striking works; setting `ARMY`→remove collapses its blocks to "▸ ARMY removed (N chars)"; a submittal-review decision shows the G panel with office input; a decision shows its designer note; Export with unanswered items shows the confirm and the JSON contains `unanswered`.

- [ ] **Step 5: Commit**

```
git add specgen/manifest.py specgen/htmlpage.py tests/
git commit -m "HTML: profile-driven redline doc, submittal-review panel, note guidance, export gate"
```

---

### Task 9: Project batch script + index page

One command builds a project folder: decision pages for the job's sections, generated output for any answers present, and an `index.html` with per-section progress.

**Files:**
- Create: `scripts/build_project.py`
- Create: `tests/test_build_project.py`

**Interfaces:**
- Consumes: `specgen` CLI modules directly (`build_manifest`, `write_html`, `read_answers`, `generate`).
- Produces: `python scripts/build_project.py <project_dir> <master.SEC> [<master.SEC> ...] [--revisions]` creating `<project_dir>/{decisions,answers,generated}/` and `<project_dir>/index.html`.

- [ ] **Step 1: Write the failing test**

`tests/test_build_project.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

from specgen import secfile

SRC = "<SEC><SCN>SECTION 99 00 00</SCN><STL>TEST</STL><TXT>[a][b] and [_____].</TXT></SEC>"


def test_build_project(tmp_path):
    master = tmp_path / "99 00 00.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "answers").mkdir()
    (proj / "answers" / "99 00 00.answers.json").write_text(
        json.dumps({"answers": {"BRK-0001": {"answer": "1"}}}), encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, "scripts/build_project.py", str(proj), str(master)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (proj / "decisions" / "99 00 00.decisions.html").exists()
    assert (proj / "generated" / "99 00 00.sec").exists()
    index = (proj / "index.html").read_text(encoding="utf-8")
    assert "99 00 00" in index and "1 unresolved" in index
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_build_project.py -v`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Implement `scripts/build_project.py`**

```python
"""Build a project decision folder from UFGS masters.

Usage: python scripts/build_project.py <project_dir> <master.SEC> [...] [--revisions]

Creates <project_dir>/decisions/<name>.decisions.html for every master, runs
generate for every master that has <project_dir>/answers/<name>.answers.json
(or .xlsx), and writes an index.html with per-section progress. Rerun any
time answers change — outputs are rebuilt idempotently.
"""

import argparse
import html as html_mod
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specgen import secfile
from specgen.answers import read_answers
from specgen.audit import audit_source
from specgen.generate import generate
from specgen.htmlpage import write_html
from specgen.manifest import build_manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("masters", nargs="+")
    ap.add_argument("--revisions", action="store_true")
    args = ap.parse_args()

    proj = Path(args.project_dir)
    for sub in ("decisions", "answers", "generated"):
        (proj / sub).mkdir(parents=True, exist_ok=True)

    rows = []
    failed = 0
    for mpath in args.masters:
        mpath = Path(mpath)
        name = mpath.stem
        sec = secfile.parse(mpath)
        report = audit_source(sec.source, sec.root)
        if report["unknowns"]:
            print(f"FAIL {name}: {len(report['unknowns'])} unattributed signals — skipped")
            failed += 1
            continue
        m = build_manifest(sec)
        write_html(m, proj / "decisions" / f"{name}.decisions.html")
        uniq = [
            d for d in m["decisions"]
            if not d["in_note"] and not d.get("plural")
            and not d.get("duplicate_of") and d["safe"]
        ]
        status, unresolved = "no answers yet", ""
        answers_file = next(
            (p for ext in (".answers.json", ".answers.xlsx")
             for p in [proj / "answers" / f"{name}{ext}"] if p.exists()),
            None,
        )
        if answers_file is not None:
            profile, ans = read_answers(answers_file)
            summary = generate(
                mpath, profile, ans, proj / "generated" / f"{name}.sec",
                revisions=args.revisions,
            )
            status = f"{summary['resolved']} resolved"
            unresolved = f"{summary['unresolved']} unresolved"
        rows.append(
            f"<tr><td><a href='decisions/{html_mod.escape(name)}.decisions.html'>"
            f"{html_mod.escape(m['section'])}</a></td>"
            f"<td>{html_mod.escape(m['title'])}</td><td>{len(uniq)} decisions</td>"
            f"<td>{status}</td><td>{unresolved}</td></tr>"
        )
        print(f"OK   {name}: {len(uniq)} decisions, {status} {unresolved}")

    (proj / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Project decisions</title>"
        "<style>body{font:15px system-ui;max-width:900px;margin:40px auto}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;"
        "padding:6px 10px;text-align:left}</style>"
        "<h1>Project decision pages</h1><table><tr><th>Section</th><th>Title</th>"
        "<th>Scope</th><th>Answers</th><th>Open</th></tr>"
        + "".join(rows) + "</table>",
        encoding="utf-8",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_build_project.py -v`
Expected: PASS. (If the `1 unresolved` assertion fails, print the index and adjust the expected count — the fixture has 2 groups, one answered.)

- [ ] **Step 5: Commit**

```
git add scripts/build_project.py tests/test_build_project.py
git commit -m "Project batch builder: decision pages, generated output, progress index"
```

---

### Task 10: Corpus regression tests + docs

**Files:**
- Create: `tests/test_corpus.py`
- Modify: `README.md` (audit command, --revisions, workflow section)

- [ ] **Step 1: Write the corpus test**

`tests/test_corpus.py`:

```python
from pathlib import Path

import pytest

from specgen import secfile
from specgen.audit import audit_source

CORPUS = Path(__file__).resolve().parent.parent / "masters" / "Specifications"

pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="corpus not present")


@pytest.mark.parametrize("path", sorted(CORPUS.glob("*.SEC")), ids=lambda p: p.stem)
def test_roundtrip_and_audit(path):
    sec = secfile.parse(path)
    assert sec.roundtrips(), "round-trip must stay byte-identical"
    report = audit_source(sec.source, sec.root)
    assert report["unknowns"] == [], report["unknowns"][:3]
```

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all PASS (55 corpus cases + unit tests). Any corpus failure at this point is a regression introduced by Tasks 1–9 — fix before proceeding.

- [ ] **Step 3: Update README.md**

In Usage, add:

```
python -m specgen audit     "masters/23 64 10.SEC"               # completeness gate
python -m specgen generate  ... --revisions   # also emit .revisions.sec (SI tracked changes)
python scripts/audit_corpus.py                # audit + round-trip all 55 masters
python scripts/build_project.py <dir> <masters...>   # per-project batch + index
```

In the answer-file workflow section, add one paragraph: the shared-drive layout (`decisions/`, `answers/`, `generated/`, `index.html`), that Export marks unanswered decisions explicitly, and that `.revisions.sec` opens in SpecsIntact with native red/green tracked changes. Update the Status bullet list: audit invariant enforced corpus-wide; units/submittal-review/markup-split signals surfaced.

- [ ] **Step 4: Final verification + commit**

Run: `python -m pytest tests/ -q` — all green.
Run: `python scripts/maxwell_demo.py` — the existing pilot demo still works end-to-end (IDs were kept stable; if any answer no longer matches, the cause must be understood before committing — the likely one is a group whose *kind* changed to submittal-review, where `keep` still applies).

```
git add tests/test_corpus.py README.md
git commit -m "Corpus regression gate and docs for audit/revisions/project workflow"
```

---

## Out of scope (deliberately)

- Free-text editing with tracked changes in the HTML (own spec later).
- Annotation/design-data pre-fill (Phase 2).
- SpecsIntact-in-the-loop verification (Phase C acceptance gate: open `.revisions.sec` in SI Editor, run Bracket Verification — manual for now).
- XSD validation of `<ADD>/<DEL>` placement (schema still unobtainable; `validate` command unchanged).
