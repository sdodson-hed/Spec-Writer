"""Regression gate: round-trip + audit every master in a corpus.

Usage: python scripts/audit_corpus.py [corpus_dir]

The corpus is the argument, else $SPECGEN_CORPUS, else masters/Specifications.
Searches recursively for .SEC/.sec (WBDG ships lowercase, one folder per
division). Parses in tolerant mode: a master with a source defect (a stray
close tag, or a byte windows-1252 leaves undefined) prints DEFECT and is
counted separately, not as a clean pass.
Exits 1 on any round-trip failure, unattributed signal, parse error, or an
empty corpus.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from specgen import secfile  # noqa: E402
from specgen.audit import audit_source, printable  # noqa: E402

DEFAULT = ROOT / "masters" / "Specifications"


def corpus_dir(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1])
    return Path(os.environ.get("SPECGEN_CORPUS") or DEFAULT)


def corpus_files(corpus: Path) -> list[Path]:
    if not corpus.is_dir():
        return []
    return sorted(p for p in corpus.rglob("*") if p.suffix.lower() == ".sec")


def main(argv: list[str]) -> int:
    corpus = corpus_dir(argv)
    files = corpus_files(corpus)
    if not files:
        print(f"FAIL: no .SEC files under {corpus}")
        return 1
    n_rt = n_clean = n_defect = n_fail = 0
    for f in files:
        try:
            sec = secfile.parse(f, tolerant=True)
        except secfile.SecParseError as e:
            print(f"FAIL {f.name:24s} parse error: {e}")
            n_fail += 1
            continue
        problems = []
        if sec.roundtrips():
            n_rt += 1
        else:
            problems.append("ROUNDTRIP-FAIL")
        report = audit_source(sec.source, sec.root, sec.defects)
        if report["unknowns"]:
            problems.append(f"{len(report['unknowns'])} unknown signal(s)")
        if problems:
            print(f"FAIL {f.name:24s} {'; '.join(problems)}")
            for u in report["unknowns"]:
                print(f"     UNKNOWN {u['type']} @ {u['offset']}: {u['context'][:100]}")
            n_fail += 1
        elif report["defects"]:
            print(f"DEFECT {f.name}")
            for d in report["defects"]:
                raw = d["raw"] if d["raw"].isprintable() else repr(d["raw"])
                print(f"     {d['type']} {raw} @ {d['offset']}: {printable(d['context'][:100])}")
            n_defect += 1
        else:
            print(f"OK   {f.name}")
            n_clean += 1
    defect_word = "source defect" if n_defect == 1 else "source defects"
    print(
        f"\n{len(files)} sections: {n_rt} round-trip, {n_clean} audit clean, "
        f"{n_defect} {defect_word}, {n_fail} failing"
    )
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
