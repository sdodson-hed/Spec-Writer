# Hygiene + Stable Anchors Implementation Plan (work order steps 1 and 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make specgen's answer files survive line-ending differences and quarterly UFGS releases, and let it parse every master in the current WBDG release (01 42 00 included), without weakening byte-identical round-trip or the never-default rule.

**Architecture:** Step 1 (branch `hygiene`) touches only the edges: `.gitattributes`, the fingerprint payload, a tolerant mode in the tokenizer, and the corpus script. Step 2 (branch `anchors`) adds `specgen/anchors.py`, which derives `<path>#<kind>:<hash8>[~n]` from the same scan and the same PRT/SPT location index the manifest already uses. Anchors are added to the manifest, the workbook, and the HTML export. A new resolver in `answers.py` turns anchor-keyed (or legacy `BRK-NNNN`) answers into the `gid`-keyed dict that `generate` already consumes, so the splice logic in `generate.py` does not change.

**Tech Stack:** Python 3.10+, stdlib + openpyxl + lxml (existing), pytest. Vanilla JS in the `_TEMPLATE` string of `specgen/htmlpage.py`.

**Spec:** `docs/superpowers/specs/2026-10-13-design-data-annotations-design.md`, sections 1 and 2. Read it first.

## Baseline (measured 2026-10-13, before any change)

- `python -m pytest -q`: **125 passed, 5 skipped**. The 129/1 figure in the brief assumes Node on PATH. On this machine Node is absent, so 4 Node-backed JS tests skip (`test_edit_core.py` x2, `test_edit_offsets.py`, `test_layout.py`), plus `test_corpus.py` (no `masters/Specifications`). 125 + 4 = 129, so nothing regressed.
- WBDG release (zips dated 2026-08-26, UMRL July 2026), Divisions 01 03 05 07 08 09 21 22 23 26 28 31 33, extracted to `C:\Users\SamDodson\ufgs\2026-08-wbdg\extracted` (outside the repo): **431 masters, 430 round-trip and audit clean**. The one failure is `01 42 00.sec`: `SecParseError: Mismatched </URL> (open: OAD)`. The source reads `Internet: <URL HREF="https://standard.no/en"/>http://www.nsf.org</URL>`. All 431 files are CRLF.
- Repo masters are stored LF in the index. This machine's git has `core.autocrlf=true` (system gitconfig from GitHub Desktop), so the working copies are CRLF here and LF on any machine without autocrlf. Today the same answers file fingerprints differently depending on who checked out the repo.
- Release drift, repo copy (UMRL April 2026) vs WBDG (UMRL July 2026), same scanner:

| Section | Groups Apr / Jul | Identical option text | `BRK` id now points elsewhere | Fingerprint equal |
|---|---|---|---|---|
| 03 30 00 | 244 / 244 | 236 | 135 | no |
| 23 64 10 | 149 / 149 | 149 | 0 | no |
| 23 64 26 | 105 / 105 | 104 | 1 | no |
| 26 20 00 | 214 / 213 | 208 | 75 | no |

- Prototype of the section 2 anchor scheme on the same pairs (throwaway script, not committed): 03 30 00 carries **236 of 244** to July (8 lost); 23 64 10 149 of 149; 23 64 26 104 of 105; 26 20 00 208 of 214. Anchors computed on CRLF and LF copies are identical for all four. The spec's acceptance target is reachable with the scheme as written.

### Spec corrections found during baseline

1. The spec says 23 64 10 "has no content change" between releases. It does: the UMRL date in the header, one note URL (`UFC 1-300-02` became `UFS 1-300-02`), the whole reference article reflowed from wrapped lines onto one line, and two cross-reference titles. None of these touch a bracket group (149 of 149 identical).
2. Because of that reflow, normalizing CRLF in option text is not enough to make the 23 64 10 fingerprints match. `scan_fingerprint` also hashes `char_start`/`char_end`, which move whenever any text before a group changes length. Task 2 drops positions from the payload. See "Decisions for review".

## Decisions for review (answer before Task 2 starts)

- **D1. Fingerprint drops character positions.** The new payload is `(gid, kind, normalized option texts)` for every group in document order. Any shift in what a `BRK` id points at still changes it, because every group's id, kind and text is in the list. What it no longer catches is a pure move: identical groups, in identical order, under different headings. Anchors (step 2) catch that through the path. Old answer files stay loadable because `generate` also accepts the legacy fingerprint.
- **D2. Source defects are reported, not failed.** In tolerant mode a stray close tag becomes a `Misc` node and a `defects` entry. `specgen audit` prints `DEFECT` lines and exits **2** (unknowns still exit 1, and outrank defects). `scripts/audit_corpus.py` prints `DEFECT` for those files, counts them separately, and exits non-zero only for round-trip failures or unknowns. `tests/test_corpus.py` allows defects only in an explicit allowlist (`{"01 42 00"}`), so a new defect in a future release fails CI until someone looks at it.
- **D3. `generate` verification in tolerant mode.** The output must have exactly the same defects (same tag, same raw text) as the master. A generator that introduces a new stray tag still fails verification.

## Global constraints

- `.SEC` files are windows-1252 (`secfile.ENCODING`). Never decode as UTF-8.
- Byte-identical round-trip is not negotiable. Tolerant mode keeps every token's raw text, including the stray tag, so `serialize() == source` still holds. The corpus run checks it on raw bytes, never on normalized text.
- Unanswered decisions are never defaulted. An answer whose anchor no longer resolves is reported in `.unresolved.md` and applied to nothing. Legacy `BRK` answers with a mismatched fingerprint are still refused (unless `--force`), because a `BRK` id cannot be safely re-pointed.
- Never edit `masters/` by hand. Fixtures under `tests/fixtures/` are byte copies made with `Copy-Item`, never opened in an editor.
- Strict parsing stays the default for `secfile.parse`. Only `generate`, `audit_file`, `scripts/audit_corpus.py` and `tests/test_corpus.py` opt in to `tolerant=True`.
- New manifest keys and answer-record fields are additive. Old manifests, old workbooks and old answers JSON keep loading.
- No new runtime dependencies.
- Environment on this machine: Python 3.15 venv at `C:\Users\SamDodson\.venvs\specgen` (pytest, lxml, openpyxl); git is not on PATH, use `C:\Users\SamDodson\AppData\Local\GitHubDesktop\app-3.6.7\resources\app\git\cmd\git.exe`. Commands below write `python` and `git` for short.
- WBDG corpus for the gate: `$env:SPECGEN_CORPUS = "C:\Users\SamDodson\ufgs\2026-08-wbdg\extracted"`.
- Before every commit: `python -m pytest -q` and `python scripts/audit_corpus.py` (after Task 4, against `SPECGEN_CORPUS`). Paste the corpus summary line into the PR description.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

# Step 1: Hygiene (branch `hygiene`, one PR)

### Task 1: `.gitattributes` for masters

**Files:**
- Create: `.gitattributes`
- Create: `tests/test_hygiene.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hygiene.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_sec_files_are_never_eol_converted():
    lines = (ROOT / ".gitattributes").read_text().splitlines()
    assert "*.SEC -text" in lines
    assert "*.sec -text" in lines
```

- [ ] **Step 2: Run, expect FAIL** (`FileNotFoundError: .gitattributes`)

Run: `python -m pytest tests/test_hygiene.py -v`

- [ ] **Step 3: Implement**

`.gitattributes`:

```
# UFGS masters ship CRLF. Git must store and check out their bytes as-is,
# or answers fingerprints and round-trip checks differ between machines.
*.SEC -text
*.sec -text
```

- [ ] **Step 4: Run the test (PASS) and check git's view**

Run: `git ls-files --eol masters`
Expected: the four `.SEC` rows now show `attr/-text`. They still show `i/lf w/crlf`, so git reports them modified. That is expected and is fixed by the re-copy, not by editing.

- [ ] **Step 5: Commit `.gitattributes` and the test only. Then STOP and tell Sam:** "`.gitattributes` is in. Please re-copy `03 30 00`, `23 64 10`, `23 64 26` and `26 20 00` from the shared drive into `masters/` (CRLF as shipped). I'll commit them as a separate commit once they're in place." After the re-copy, verify `git ls-files --eol masters` shows `i/crlf w/crlf` once committed, run the suite and `python scripts/audit_corpus.py`, then commit with message `Re-copy masters with CRLF (no content edits)`.

### Task 2: Line-ending- and position-insensitive fingerprint

**Files:**
- Modify: `specgen/scan.py` (`scan_fingerprint`, new `legacy_scan_fingerprint`)
- Modify: `specgen/generate.py:205-221` (accept legacy)
- Test: `tests/test_fingerprint.py` (extend)

**Interfaces:**
- `scan_fingerprint(groups) -> str` now hashes `(gid, kind, [normalized option text])`. Normalized = `re.sub(r"\s+", " ", text).strip()`.
- `legacy_scan_fingerprint(groups) -> str` is the old function body, unchanged, kept so existing answer files still load.
- `generate()` summary `answers_fingerprint` gains the value `"match (legacy)"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_fingerprint.py`)

```python
from specgen.scan import legacy_scan_fingerprint

CRLF = "<SEC><TXT>Provide [scroll\r\n][screw] compressors.</TXT>\r\n</SEC>"
LF = "<SEC><TXT>Provide [scroll\n][screw] compressors.</TXT>\n</SEC>"
REFLOW = "<SEC><TXT>Longer text before. Provide [scroll\n][screw] compressors.</TXT>\n</SEC>"


def test_fingerprint_ignores_line_endings():
    assert scan_fingerprint(scan_groups(CRLF)[0]) == scan_fingerprint(scan_groups(LF)[0])


def test_fingerprint_ignores_text_outside_brackets():
    # 23 64 10 Apr->Jul 2026: reference article reflowed, no bracket changed
    assert scan_fingerprint(scan_groups(LF)[0]) == scan_fingerprint(scan_groups(REFLOW)[0])


def test_fingerprint_still_tracks_option_text_and_ids():
    other = LF.replace("screw", "rotary screw")
    assert scan_fingerprint(scan_groups(LF)[0]) != scan_fingerprint(scan_groups(other)[0])
    # SRC2 inserts a group before: BRK-0001 now means something else
    assert scan_fingerprint(scan_groups(SRC)[0]) != scan_fingerprint(scan_groups(SRC2)[0])


def test_generate_accepts_legacy_fingerprint(tmp_path):
    legacy = legacy_scan_fingerprint(scan_groups(SRC)[0])
    assert legacy != scan_fingerprint(scan_groups(SRC)[0])
    assert _gen(tmp_path, legacy)["answers_fingerprint"] == "match (legacy)"
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: legacy_scan_fingerprint`)

- [ ] **Step 3: Implement**

In `specgen/scan.py`, rename the current `scan_fingerprint` to `legacy_scan_fingerprint` (body and docstring unchanged except a first line "Pre-2026-10 fingerprint: kept so older answer files still verify."). Add:

```python
def scan_fingerprint(groups: list[Group]) -> str:
    """Stable hash of the decision surface: ids, kinds and option texts in
    document order. Any change that shifts what an answer id means changes
    it (issue #23). Whitespace is normalized and positions are left out, so
    CRLF vs LF copies, and edits to text outside brackets, do not."""
    payload = [
        (g.gid, g.kind, [_WS_RE.sub(" ", o.text).strip() for o in g.options])
        for g in groups
    ]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:16]
```

In `specgen/generate.py`, import `legacy_scan_fingerprint` and replace the gate:

```python
    groups0 = scan_groups(src)[0]
    expected = scan_fingerprint(groups0)
    legacy = legacy_scan_fingerprint(groups0)
    fp_status = "unstamped"
    if fingerprint:
        if fingerprint not in (expected, legacy) and not force_stale:
            raise GenerateError(...)  # message unchanged
        fp_status = (
            "match" if fingerprint == expected
            else "match (legacy)" if fingerprint == legacy
            else "MISMATCH (forced)"
        )
```

- [ ] **Step 4: Run `python -m pytest tests/test_fingerprint.py -v`, expect all PASS.** The existing `test_fingerprint_tracks_decision_surface` must still pass unchanged.

- [ ] **Step 5: Full suite + corpus, commit** `Fingerprint: normalize whitespace, drop positions; accept legacy`

### Task 3: Tolerant parse mode

**Files:**
- Modify: `specgen/secfile.py` (`parse`, `parse_source`, `SecFile.defects`)
- Modify: `specgen/audit.py` (`audit_source` defects, `audit_file(tolerant=True)`)
- Modify: `specgen/cli.py` (`cmd_audit` exit 2; `cmd_html`/`cmd_generate` print defects as warnings)
- Modify: `specgen/generate.py` (every `secfile.parse(...)` call gets `tolerant=True`; verification compares defects)
- Test: `tests/test_tolerant_parse.py` (new)

**Interfaces:**
- `secfile.parse(path, tolerant=False)`, `secfile.parse_source(source, path=..., tolerant=False)`.
- `SecFile.defects: list[dict]`, each `{"type": "stray-close-tag", "tag": "URL", "raw": "</URL>", "offset": int, "open": "OAD"}`.
- `audit_source(src, root, defects=())` returns `{"signals", "unknowns", "defects"}`; each defect gains `context`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tolerant_parse.py`:

```python
import pytest

from specgen import secfile
from specgen.audit import audit_source
from specgen.generate import generate
from specgen.secfile import Misc, SecParseError

# 01 42 00 (WBDG, UMRL July 2026), NORSOK entry, reduced
NORSOK = (
    '<SEC><PRT><TTL>PART 1 GENERAL</TTL><OAD>Internet: '
    '<URL HREF="https://standard.no/en"/>http://www.nsf.org</URL><BRK/>\r\n'
    "</OAD><TXT>Provide [one][two].</TXT></PRT></SEC>"
)


def test_strict_mode_still_rejects():
    with pytest.raises(SecParseError, match="Mismatched </URL>"):
        secfile.parse_source(NORSOK)


def test_tolerant_mode_keeps_bytes_and_records_defect():
    sec = secfile.parse_source(NORSOK, tolerant=True)
    assert sec.roundtrips()
    assert sec.serialize() == NORSOK
    [d] = sec.defects
    assert (d["type"], d["tag"], d["raw"], d["open"]) == ("stray-close-tag", "URL", "</URL>", "OAD")
    assert NORSOK[d["offset"]:].startswith("</URL>")
    stray = [c for c in sec.root.iter("OAD")][0].children
    assert any(isinstance(c, Misc) and c.raw == "</URL>" for c in stray)


def test_tolerant_mode_does_not_hide_real_nesting_errors():
    # </TXT> matches an element deeper in the stack: that is a structural
    # error, not a stray tag, and must still raise
    bad = "<SEC><TXT><B>x</TXT></B></SEC>"
    with pytest.raises(SecParseError):
        secfile.parse_source(bad, tolerant=True)


def test_audit_reports_defect_not_pass():
    sec = secfile.parse_source(NORSOK, tolerant=True)
    rep = audit_source(sec.source, sec.root, sec.defects)
    assert rep["unknowns"] == []
    assert len(rep["defects"]) == 1 and "standard.no" in rep["defects"][0]["context"]


def test_generate_runs_on_defective_master(tmp_path):
    m = tmp_path / "01 42 00.SEC"
    m.write_bytes(NORSOK.encode(secfile.ENCODING))
    s = generate(m, {}, {"BRK-0001": {"answer": "2"}}, tmp_path / "o.sec")
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    assert "Provide two." in out and "</URL>" in out
    assert s["source_defects"] == 1
```

Also add to `tests/test_audit.py` a CLI test: `main(["audit", str(path)])` returns 2 for a file with only a defect, 1 for a file with an unknown (unknown outranks defect).

- [ ] **Step 2: Run, expect FAIL** (`TypeError: parse_source() got an unexpected keyword argument 'tolerant'`)

- [ ] **Step 3: Implement**

`secfile.py`:

```python
@dataclass
class SecFile:
    path: Path
    source: str
    prolog: list
    root: Element
    epilog: list
    defects: list = field(default_factory=list)  # tolerant-mode source defects


def parse(path: Path | str, tolerant: bool = False) -> SecFile:
    path = Path(path)
    return parse_source(path.read_bytes().decode(ENCODING), path, tolerant=tolerant)
```

In `parse_source(source, path=Path("<memory>"), tolerant=False)`, add `defects: list[dict] = []` and change the close-tag branch:

```python
            if is_end:
                if not stack or stack[-1].name != name:
                    got = stack[-1].name if stack else None
                    # Tolerant: a close tag that matches NOTHING open is a
                    # stray (UFGS 01 42 00 NORSOK entry). Keep its raw text
                    # as a Misc node so round-trip stays byte-identical, and
                    # record it. A tag matching a deeper element is a real
                    # nesting error and still raises.
                    if tolerant and all(e.name != name for e in stack):
                        emit(Misc(raw))
                        defects.append({"type": "stray-close-tag", "tag": name,
                                        "raw": raw, "offset": tag_start, "open": got})
                        continue
                    raise SecParseError(f"Mismatched </{name}> (open: {got})")
```

Pass `defects=defects` into the returned `SecFile`.

`audit.py`: `audit_source(src, root, defects=())` copies each defect into `report["defects"]` with `context = src[max(0, off-80):off+40]` (whitespace collapsed). `audit_file(path, tolerant=True)` passes `sec.defects`.

`cli.py` `cmd_audit`: print `DEFECT {type} {raw} @ {offset}: {context}` per defect; return 1 if unknowns, else 2 if defects (`print("SOURCE DEFECT: ... not a clean pass")`), else 0. `cmd_html`/`cmd_generate`: print defects as `WARNING: source defect ...` and continue.

`generate.py`: every `secfile.parse(...)` gets `tolerant=True`. Keep `master_defects = secfile.parse(master, tolerant=True).defects` at the top. In verification after `parsed = secfile.parse(tmp, tolerant=True)`:

```python
    if [d["raw"] for d in parsed.defects] != [d["raw"] for d in master_defects]:
        raise GenerateError("internal error: output has source defects the master does not")
```

`ET.parse(tmp)` would reject the stray tag, so in verification replace it with a well-formedness check on the output with each recorded defect's raw text blanked at its offset (offsets from `parsed.defects`). Add `"source_defects": len(master_defects)` to the summary. Same treatment for the revisions file check.

- [ ] **Step 4: Run new tests (PASS), full suite, corpus.**

- [ ] **Step 5: Commit** `Tolerant parse: stray close tags become Misc + audit defect`

### Task 4: Corpus script and corpus test take a directory

**Files:**
- Modify: `scripts/audit_corpus.py`
- Modify: `tests/test_corpus.py`
- Test: `tests/test_audit_corpus_script.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
from pathlib import Path

from tests.test_tolerant_parse import NORSOK

ROOT = Path(__file__).resolve().parent.parent
GOOD = "<SEC><PRT><TTL>PART 1</TTL><TXT>Provide [a][b].</TXT></PRT></SEC>"


def _run(*args, env=None):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_corpus.py"), *args],
                          capture_output=True, text=True, env=env)


def test_corpus_dir_argument_and_lowercase_ext(tmp_path):
    (tmp_path / "DIV01").mkdir()
    (tmp_path / "DIV01" / "01 42 00.sec").write_bytes(NORSOK.encode("windows-1252"))
    (tmp_path / "23 64 10.SEC").write_bytes(GOOD.encode("windows-1252"))
    r = _run(str(tmp_path))
    assert r.returncode == 0, r.stdout
    assert "DEFECT 01 42 00.sec" in r.stdout
    assert "2 sections: 2 round-trip, 1 audit clean, 1 source defect, 0 failing" in r.stdout


def test_env_var(tmp_path, monkeypatch):
    (tmp_path / "x.SEC").write_bytes(b"<SEC><TXT>[unbalanced</TXT></SEC>")
    import os
    r = _run(env={**os.environ, "SPECGEN_CORPUS": str(tmp_path)})
    assert r.returncode == 1 and "1 failing" in r.stdout
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

`scripts/audit_corpus.py`: corpus = `argv[1]` if given, else `SPECGEN_CORPUS`, else `masters/Specifications`. Files = `sorted(p for p in corpus.rglob("*") if p.suffix.lower() == ".sec")` (WBDG ships lowercase `.sec` in per-division folders). Parse tolerant; a `SecParseError` counts as failing with the message. Status per file: `OK`, `DEFECT` (round-trips, no unknowns, has defects), `FAIL`. Summary line exactly:

```
{n} sections: {rt} round-trip, {clean} audit clean, {d} source defect(s), {f} failing
```

(`source defect` singular when 1.) Exit 1 if any failing.

`tests/test_corpus.py`: same corpus resolution (env var or `masters/Specifications`), same case-insensitive `rglob`, parse tolerant, assert round-trip, assert no unknowns, and assert `not sec.defects or path.stem in KNOWN_DEFECTS` with `KNOWN_DEFECTS = {"01 42 00"}`.

- [ ] **Step 4: Run tests, then the gate**

Run: `$env:SPECGEN_CORPUS = "C:\Users\SamDodson\ufgs\2026-08-wbdg\extracted"; python scripts/audit_corpus.py`
Expected: `431 sections: 431 round-trip, 430 audit clean, 1 source defect, 0 failing`
Run: `python -m pytest -q` with the env var still set (the corpus test now runs 431 cases instead of skipping).

- [ ] **Step 5: Commit** `audit_corpus: corpus dir arg / SPECGEN_CORPUS, defects counted`

- [ ] **Step 6: Open the PR** `Hygiene: .gitattributes, normalized fingerprint, tolerant parse, corpus dir`. Description includes the corpus summary line, the test count, and a note that masters were re-copied (not edited). Wait for merge before Step 2's branch.

---

# Step 2: Stable anchors (branch `anchors` from merged `main`, one PR)

### Task 5: `specgen/anchors.py`

**Files:**
- Create: `specgen/anchors.py`
- Modify: `specgen/manifest.py` (rename `_location_index` to `location_index`, keep `_location_index = location_index` alias)
- Test: `tests/test_anchors.py` (new)

**Interfaces:**
- `norm_text(t) -> str`: collapse whitespace, strip.
- `norm_title(t) -> str`: drop `[` and `]`, collapse whitespace, uppercase, `/` escaped as `%2F` (it is the path separator).
- `option_hash(texts) -> str`: first 8 hex of SHA-1 over `"\x1f".join(norm_text(t) for t in texts)`, UTF-8.
- `group_path(locs, offset) -> str`: PRT/SPT chain containing `offset`, outermost first. A PRT contributes its number (`PART 2`, matching the spec's example); an SPT contributes `norm_title`. Before the first PRT: `(HEADER)`.
- `assign_anchors(groups, locs) -> dict[str, str]`: gid to anchor, `kind` = `plural` when `is_plural(g)`, else `g.kind`. `~n` appended from the second occurrence of the same base, in document order.
- `section_anchors(sec) -> dict[str, str]`: convenience that scans and indexes.
- `spt` anchors are defined by the spec but have no decisions until step 3. Not implemented here.

- [ ] **Step 1: Write the failing tests**

`tests/test_anchors.py`:

```python
from specgen import secfile
from specgen.anchors import norm_title, option_hash, section_anchors

SRC = (
    "<SEC><HDR><TXT>Header [_____]</TXT></HDR>"
    "<PRT><TTL>PART 1 GENERAL</TTL><SPT><TTL>SUMMARY</TTL><TXT>x</TXT></SPT></PRT>"
    "<PRT><TTL>PART 2 PRODUCTS</TTL>"
    "<SPT><TTL>SCROLL[, RECIPROCATING] TYPE CHILLERS</TTL>"
    "<TXT>Provide [scroll][screw] compressors.</TXT>"
    "<TXT>Refrigerant [_____].</TXT>"
    "<TXT>Again [scroll][screw].</TXT></SPT>"
    "<SPT><TTL>CHILLED/HOT WATER</TTL><TXT>Unit[s] here.</TXT></SPT>"
    "</PRT></SEC>"
)


def _anchors(src):
    return section_anchors(secfile.parse_source(src))


def test_hash_values_are_pinned():
    # changing normalization silently orphans every saved answer: pin it
    assert option_hash(["scroll", "screw"]) == "e37dc8c8"
    assert option_hash(["  scroll\r\n", "screw "]) == "e37dc8c8"
    assert option_hash(["_____"]) == "2477bc03"


def test_anchor_shapes():
    a = _anchors(SRC)
    p = "PART 2/SCROLL, RECIPROCATING TYPE CHILLERS"
    assert a["BRK-0001"].startswith("(HEADER)#blank:")
    assert a["BRK-0002"] == f"{p}#optional:" + option_hash([", RECIPROCATING"])
    assert a["BRK-0003"] == f"{p}#choice:e37dc8c8"
    assert a["BRK-0004"] == f"{p}#blank:2477bc03"
    assert a["BRK-0005"] == f"{p}#choice:e37dc8c8~2"
    assert a["BRK-0006"] == "PART 2/CHILLED%2FHOT WATER#plural:" + option_hash(["s"])


def test_crlf_and_lf_give_identical_anchors():
    crlf = SRC.replace("</TXT>", "</TXT>\r\n")
    assert _anchors(crlf) == _anchors(crlf.replace("\r\n", "\n"))


def test_stable_when_unrelated_group_inserted_earlier():
    before = _anchors(SRC)
    after = _anchors(SRC.replace("<TXT>x</TXT>", "<TXT>x [new][option]</TXT>"))
    assert set(before.values()) <= set(after.values())
    assert before["BRK-0003"] == after["BRK-0004"]  # id moved, anchor did not


def test_norm_title():
    assert norm_title(" chilled/hot  [water] ") == "CHILLED%2FHOT WATER"
```

Add one corpus-scale test (skips without the env var), which checks that `section_anchors` yields one unique anchor per group on every master, and that CRLF and LF copies give the same anchors.

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: specgen.anchors`)

- [ ] **Step 3: Implement** `specgen/anchors.py`:

```python
"""Stable decision anchors (spec 2026-10-13, section 2).

anchor = <path>#<kind>:<hash8>[~n]

BRK-NNNN ids are positional, so one inserted bracket group renumbers every
group after it. An anchor names a decision by where it sits (the PRT/SPT
title chain) and what it says (a hash of its normalized option texts), so
it survives quarterly UFGS releases and CRLF/LF differences whenever that
decision's text and location are unchanged.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from .scan import Group, is_plural, scan_groups

_WS_RE = re.compile(r"\s+")


def norm_text(t: str) -> str:
    return _WS_RE.sub(" ", t).strip()


def norm_title(t: str) -> str:
    t = t.replace("[", "").replace("]", "")
    return _WS_RE.sub(" ", t).strip().upper().replace("/", "%2F")


def option_hash(texts: list[str]) -> str:
    joined = "\x1f".join(norm_text(t) for t in texts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]


def group_path(locs, offset: int) -> str:
    parts = [
        s.num if s.depth == 0 else norm_title(s.title)
        for s in locs
        if s.start <= offset < s.end
    ]
    return "/".join(parts) or "(HEADER)"


def assign_anchors(groups: list[Group], locs) -> dict[str, str]:
    seen: Counter[str] = Counter()
    out: dict[str, str] = {}
    for g in groups:
        kind = "plural" if is_plural(g) else g.kind
        base = (
            f"{group_path(locs, g.src_start)}#{kind}:"
            f"{option_hash([o.text for o in g.options])}"
        )
        seen[base] += 1
        out[g.gid] = base if seen[base] == 1 else f"{base}~{seen[base]}"
    return out


def section_anchors(sec) -> dict[str, str]:
    from .manifest import location_index

    return assign_anchors(scan_groups(sec.source)[0], location_index(sec.root))
```

- [ ] **Step 4: Run, PASS; full suite; corpus. Commit** `anchors: path#kind:hash8[~n] for bracket decisions`

### Task 6: Anchors in the manifest, workbook and HTML export

**Files:**
- Modify: `specgen/manifest.py` (each decision gets `"anchor"`)
- Modify: `specgen/answers.py` (workbook `Anchor` column; `read_workbook` keys by anchor when present; `read_answers_json` keeps `options` and `id` fields)
- Modify: `specgen/htmlpage.py` (export keyed by anchor; import maps anchors back to ids)
- Test: `tests/test_answers_anchors.py` (new), extend `tests/test_htmlpage.py`

**Interfaces:**
- Answers JSON v2 (HTML export): top-level `"schema": "specgen.answers/2"`; each bracket answer key is the anchor; value `{"answer", "notes", ["office"], "id": "BRK-0012", "options": [...]}`. `id` and `options` are for display and for the orphan report. `ME@` records are unchanged.
- Workbook: new last column `Anchor` on the Answers sheet. `read_workbook` returns anchor keys when the column exists and the cell is filled, `BRK` keys otherwise (old workbooks).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_answers_anchors.py
import json

from specgen import secfile
from specgen.answers import read_answers_json, read_workbook, write_workbook
from specgen.manifest import build_manifest

SRC = ("<SEC><PRT><TTL>PART 2 PRODUCTS</TTL><SPT><TTL>CHILLERS</TTL>"
       "<TXT>Provide [scroll][screw] compressors.</TXT></SPT></PRT></SEC>")
ANCHOR = "PART 1/CHILLERS#choice:e37dc8c8"


def _m():
    return build_manifest(secfile.parse_source(SRC))


def test_manifest_carries_anchor():
    assert _m()["decisions"][0]["anchor"] == ANCHOR


def test_workbook_round_trips_anchor_keys(tmp_path):
    x = tmp_path / "a.xlsx"
    write_workbook(_m(), x)
    from openpyxl import load_workbook
    wb = load_workbook(x)
    ws = wb["Answers"]
    head = [c.value for c in ws[1]]
    ws.cell(row=2, column=head.index("Answer") + 1, value="1")
    wb.save(x)
    _, answers, _ = read_workbook(x)
    assert answers == {ANCHOR: {"answer": "1", "notes": ""}}


def test_json_v2_keeps_display_fields(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"schema": "specgen.answers/2", "answers": {
        ANCHOR: {"answer": "1", "id": "BRK-0001", "options": ["scroll", "screw"]}}}))
    _, answers, _ = read_answers_json(p)
    assert answers[ANCHOR]["options"] == ["scroll", "screw"]
    assert answers[ANCHOR]["id"] == "BRK-0001"
```

Note `PART 1` above: the fixture has a single PRT, so it is numbered 1 even though its title says "PART 2". Numbers come from position, as SpecsIntact's Navigate panel does.

In `tests/test_htmlpage.py`, assert the template contains `schema: "specgen.answers/2"`, `d.anchor`, and the import-side `byAnchor` mapping, and that the embedded manifest JSON contains `"anchor": "`.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

`manifest.py` `build_manifest`: `anchors = assign_anchors(groups, locs)` and add `"anchor": anchors[g.gid]` to each decision dict.

`answers.py`: `write_workbook` appends `"Anchor"` to `headers` and `d.get("anchor", "")` to each row (width 40, grey font). `read_workbook`: `anc_i = head.get("anchor")`; key = the anchor cell when present and non-empty, else the ID. `read_answers_json`: for dict values, carry `id` (str) and `options` (list of str) when present.

`htmlpage.py` export handler, replacing `answers: { ...state.answers, ...state.edits }`:

```js
  const byId = Object.fromEntries(ds.map(d => [d.id, d]));
  const keyed = {};
  for (const [id, rec] of Object.entries(state.answers)) {
    const d = byId[id];
    if (d && d.anchor) keyed[d.anchor] = { ...rec, id, options: d.options };
    else keyed[id] = rec;
  }
```

and add `schema: "specgen.answers/2"` to `payload`, with `answers: { ...keyed, ...state.edits }`. The `unanswered` list stays as `BRK` ids (display only).

Import handler: build `const byAnchor = Object.fromEntries(ds.map(d => [d.anchor, d.id]));`. For each non-`ME@` key, `const id = k.includes("#") ? byAnchor[k] : k;`. When `id` is undefined, count it and do not store it. After loading, if the count is non-zero, `alert(`${n} answer(s) belong to decisions that are not in this master (the master changed). They were not applied.`)`. Strip `id`/`options` before storing in `state.answers` so localStorage stays as before.

- [ ] **Step 4: Run tests, full suite, corpus. Manually open one generated page** (`python -m specgen html "masters/23 64 10.SEC" -o out/t.html`), answer two decisions, export, check the JSON keys are anchors, clear, import it back, confirm both answers return. Record this in the PR.

- [ ] **Step 5: Commit** `Anchors in manifest, workbook and HTML export/import`

### Task 7: Anchor-keyed loading in `generate`

**Files:**
- Modify: `specgen/answers.py` (new `resolve_answer_keys`)
- Modify: `specgen/generate.py` (call it; orphans into `unresolved`; `strict` parameter)
- Modify: `specgen/cli.py` (`generate --strict`; print the orphan warning)
- Test: `tests/test_resolve_answers.py` (new)

**Interfaces:**

```python
def resolve_answer_keys(
    answers: dict[str, dict],
    groups: list[Group],
    anchors: dict[str, str],          # gid -> anchor
    fingerprint: str | None,
    *, force_stale: bool = False, strict: bool = False,
) -> tuple[dict[str, dict], list[dict], str]:
    """-> (answers keyed by gid, orphans, fingerprint status)"""
```

Rules, in order:

1. `ME@` keys pass through unchanged.
2. Anchor keys (contain `#`): resolve to the gid with that anchor. No match means an orphan: `{"id": <anchor>, "kind": "orphan", "options": rec.get("options", []), "answer": rec["answer"], "note": "master changed: decision not found (was <rec id>)"}`. Never applied.
3. `BRK` keys: allowed when the file is unstamped (today's behavior, warning) or the fingerprint matches current or legacy. Otherwise `GenerateError` (existing message) unless `force_stale`. This is the spec's "old answers files keyed on BRK-NNNN still load when their fingerprint matches".
4. Two keys resolving to the same gid: `GenerateError("two answers for BRK-0012: <key1>, <key2>")`.
5. Status: `"anchors"` when every bracket key was an anchor (the fingerprint then becomes informational), else the Task 2 statuses.
6. `strict=True`: any orphan, or a stamped fingerprint that matches neither current nor legacy, raises `GenerateError`. This is the spec's `--strict`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from specgen import secfile
from specgen.anchors import section_anchors
from specgen.answers import resolve_answer_keys
from specgen.generate import GenerateError, generate
from specgen.scan import scan_fingerprint, scan_groups

APR = ("<SEC><PRT><TTL>PART 2</TTL><SPT><TTL>CHILLERS</TTL>"
       "<TXT>Provide [scroll][screw] compressors.</TXT>"
       "<TXT>Refrigerant [R-410A][R-454B].</TXT></SPT></PRT></SEC>")
# July: a new group before both, and the refrigerant options changed
JUL = APR.replace("<TXT>Provide", "<TXT>New [x][y].</TXT><TXT>Provide").replace(
    "[R-410A][R-454B]", "[R-454B][R-32]")


def _ctx(src):
    sec = secfile.parse_source(src)
    groups = scan_groups(src)[0]
    return groups, section_anchors(sec)


def _apr_answers():
    g, a = _ctx(APR)
    return {a["BRK-0001"]: {"answer": "1", "id": "BRK-0001", "options": ["scroll", "screw"]},
            a["BRK-0002"]: {"answer": "2", "id": "BRK-0002", "options": ["R-410A", "R-454B"]}}


def test_anchor_answers_follow_the_decision_across_releases():
    groups, anchors = _ctx(JUL)
    by_gid, orphans, status = resolve_answer_keys(_apr_answers(), groups, anchors, None)
    assert by_gid == {"BRK-0002": {"answer": "1", "id": "BRK-0001", "options": ["scroll", "screw"]}}
    assert [o["options"] for o in orphans] == [["R-410A", "R-454B"]]
    assert "master changed" in orphans[0]["note"]
    assert status == "anchors"


def test_orphan_is_never_applied_and_never_defaulted(tmp_path):
    m = tmp_path / "jul.SEC"
    m.write_bytes(JUL.encode(secfile.ENCODING))
    s = generate(m, {}, _apr_answers(), tmp_path / "o.sec")
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    assert "Provide scroll compressors." in out
    assert "[R-454B][R-32]" in out          # still bracketed
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    assert "master changed: decision not found" in md and "R-410A | R-454B" in md
    assert s["answers_orphaned"] == 1 and s["answers_carried"] == 1


def test_strict_refuses_orphans(tmp_path):
    m = tmp_path / "jul.SEC"
    m.write_bytes(JUL.encode(secfile.ENCODING))
    with pytest.raises(GenerateError, match="1 answer"):
        generate(m, {}, _apr_answers(), tmp_path / "o.sec", strict=True)


def test_legacy_brk_keys_need_matching_fingerprint():
    groups, anchors = _ctx(JUL)
    stale = scan_fingerprint(scan_groups(APR)[0])
    with pytest.raises(GenerateError, match="different scan"):
        resolve_answer_keys({"BRK-0001": {"answer": "1"}}, groups, anchors, stale)
    ok = scan_fingerprint(groups)
    by_gid, _, status = resolve_answer_keys({"BRK-0001": {"answer": "1"}}, groups, anchors, ok)
    assert by_gid == {"BRK-0001": {"answer": "1"}} and status == "match"


def test_same_decision_answered_twice_is_an_error():
    groups, anchors = _ctx(APR)
    fp = scan_fingerprint(groups)
    with pytest.raises(GenerateError, match="two answers for BRK-0001"):
        resolve_answer_keys({"BRK-0001": {"answer": "1"}, anchors["BRK-0001"]: {"answer": "2"}},
                            groups, anchors, fp)
```

Plus a CLI test: `generate --strict` exits non-zero on the July master with April anchors; without `--strict` it prints `WARNING: 1 answer(s) did not resolve (master changed)` and exits 0.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** `resolve_answer_keys` in `answers.py` (imports `GenerateError` lazily from `generate` to avoid a cycle, or move `GenerateError` into a small `specgen/errors.py` re-exported from `generate`; prefer the latter). In `generate()`, replace the fingerprint block and the `unknown`-ids check's input:

```python
    sec0 = secfile.parse(master, tolerant=True)
    src = sec0.source
    groups0 = scan_groups(src)[0]
    answers, orphans, fp_status = resolve_answer_keys(
        answers, groups0, section_anchors(sec0), fingerprint,
        force_stale=force_stale, strict=strict,
    )
```

The existing `unknown = sorted(set(bracket_answers) - set(by_id))` check stays and now only sees gids. After the bracket loop, `unresolved.extend(orphans)` (before `unresolved_edits`). Summary adds `"answers_carried"` (bracket answers that resolved) and `"answers_orphaned"`. In `.unresolved.md`, orphan entries render with their old options and the note, using the existing loop (kind `orphan` is not `blank`, so options print).

`cli.py`: `generate` gains `--strict`; after `generate` returns, if `answers_orphaned` print the warning line. The no-fingerprint warning prints only when the file has `BRK` keys.

- [ ] **Step 4: Run tests, full suite, corpus. Commit** `generate: anchor-keyed answers, orphans reported, --strict`

### Task 8: Release fixture and acceptance test (03 30 00 April vs July 2026)

**Files:**
- Create: `tests/fixtures/ufgs/03 30 00 (2026-04).SEC` (byte copy of `masters/03 30 00.SEC` after the Task 1 re-copy)
- Create: `tests/fixtures/ufgs/03 30 00 (2026-07).SEC` (byte copy of the WBDG `DIV03/.../03 30 00.sec`)
- Test: `tests/test_release_anchors.py` (new)

- [ ] **Step 1: Copy the fixtures with `Copy-Item` (never through an editor). Verify `git ls-files --eol tests/fixtures` shows `-text` and CRLF in the worktree.**

- [ ] **Step 2: Write the test**

```python
import re
from pathlib import Path

from specgen import secfile
from specgen.anchors import section_anchors
from specgen.answers import resolve_answer_keys
from specgen.generate import generate
from specgen.scan import scan_groups

FIX = Path(__file__).parent / "fixtures" / "ufgs"
APR, JUL = FIX / "03 30 00 (2026-04).SEC", FIX / "03 30 00 (2026-07).SEC"
WS = re.compile(r"\s+")


def _answer_everything(path):
    sec = secfile.parse(path)
    groups = scan_groups(sec.source)[0]
    anchors = section_anchors(sec)
    ans = {}
    for g in groups:
        if g.in_note:
            continue
        a = {"choice": "1", "blank": "X", "optional": "keep",
             "submittal-review": "keep"}[g.kind]
        ans[anchors[g.gid]] = {"answer": a, "id": g.gid,
                               "options": [WS.sub(" ", o.text).strip() for o in g.options]}
    return ans


def test_fixtures_are_crlf_and_round_trip():
    for p in (APR, JUL):
        assert b"\r\n" in p.read_bytes()
        assert secfile.parse(p).roundtrips()


def test_april_answers_carry_to_july():
    ans = _answer_everything(APR)
    sec = secfile.parse(JUL)
    groups = scan_groups(sec.source)[0]
    assert len(ans) == 244                # 03 30 00 has no bracket groups inside notes
    by_gid, orphans, status = resolve_answer_keys(ans, groups, section_anchors(sec), None)
    assert (len(by_gid), len(orphans), status) == (236, 8, "anchors")
    by_id = {g.gid: g for g in groups}
    for gid, rec in by_gid.items():       # every carried answer lands on identical text
        assert [WS.sub(" ", o.text).strip() for o in by_id[gid].options] == rec["options"]


def test_generate_on_july_with_april_answers(tmp_path):
    s = generate(JUL, {}, _answer_everything(APR), tmp_path / "o.sec")
    assert (s["answers_carried"], s["answers_orphaned"]) == (236, 8)
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    assert md.count("master changed: decision not found") == 8
```

The numbers are measured (prototype, 2026-10-13): 244 groups, none in notes, 236 carried, 8 orphaned. They are pinned on purpose. If the implementation gives different numbers, find out why before touching the test.

- [ ] **Step 3: Run, PASS. Full suite, corpus. Commit** `Release fixture: 03 30 00 April vs July 2026, anchors carry 236/244`

### Task 9: Docs and PR

- [ ] Update `README.md`: answers JSON v2 (anchor keys), `generate --strict`, the tolerant-parse defect report, `scripts/audit_corpus.py <dir>` / `SPECGEN_CORPUS`, and the corpus status line (431 WBDG masters). Fix the stale "56 masters" status.
- [ ] Full suite + corpus with `SPECGEN_CORPUS` set. Open the PR `Stable anchors: answers survive UFGS releases and line endings`. Description: corpus summary line, test count, the 03 30 00 carry-over numbers, the four-section carry-over table from the baseline, and the manual HTML export/import check from Task 6.

---

## Out of scope here (step 3 onward)

- `spt` decisions, structural removal, submittal/reference cleanup.
- Design-data file, annotation loader, `prefill`, provenance.
- `ME@` manual edits stay offset-keyed with their existing `before`-text check. They do not get anchors in this work.
