"""The repo is public: nothing from the user's real statements may be in it.

`privacy_denylist.txt` (gitignored, kept only on the user's machine) lists
real names, account numbers and notes seen in statements. Every file git
would publish is checked against it. Skipped where the list doesn't exist
(e.g. on GitHub's CI runners).
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DENYLIST = ROOT / "privacy_denylist.txt"


def published_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [ROOT / f for f in out if f and not f.endswith((".png", ".jpg", ".ico", ".pdf", ".jar", ".keystore"))]


@pytest.mark.skipif(not DENYLIST.exists(), reason="no local privacy_denylist.txt")
def test_no_real_statement_data_in_published_files():
    terms = [t.strip() for t in DENYLIST.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]
    # Words of a term may be split by a line break or Markdown ("To Zai\n   Yi*").
    gap = r"[\s*_]+"
    pattern = re.compile("|".join(gap.join(re.escape(w) for w in t.split()) for t in terms), re.IGNORECASE)
    hits = []
    for f in published_files():
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for m in pattern.finditer(text):
            hits.append(f"{f.relative_to(ROOT)}:{text[:m.start()].count(chr(10)) + 1}")
    assert not hits, "real statement data in files that would be published: " + ", ".join(hits[:20])


def test_private_files_are_gitignored():
    for name in ("config.toml", "privacy_denylist.txt", "NOTES.local.md", "statements/x.pdf", "output/x.xlsx"):
        ignored = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0
        assert ignored, f"{name} must be gitignored"
