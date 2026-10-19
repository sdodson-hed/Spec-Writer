from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_sec_files_are_never_eol_converted():
    lines = (ROOT / ".gitattributes").read_text().splitlines()
    assert "*.SEC -text" in lines
    assert "*.sec -text" in lines
