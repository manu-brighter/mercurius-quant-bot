"""yfinance is research-only: no module under src/mercurius may import it.

(Research usage lives in notebooks/, which is never imported by the package.)
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mercurius"

FORBIDDEN = re.compile(r"^\s*(import|from)\s+(yfinance|notebooks)\b", re.MULTILINE)


def test_no_yfinance_in_package():
    offenders = [
        str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if FORBIDDEN.search(p.read_text())
    ]
    assert not offenders, f"forbidden imports in live code: {offenders}"
