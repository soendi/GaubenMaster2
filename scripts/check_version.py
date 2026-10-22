from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def read_version() -> str:
    text = (ROOT / "src" / "gaubenmaster" / "version.py").read_text(encoding="utf-8")
    match = PATTERN.search(text)
    if not match:
        raise SystemExit("Versionsnummer nicht gefunden.")
    return match.group(1)


def main() -> int:
    version = read_version()
    if not SEMVER.match(version):
        raise SystemExit(f"Ungueltige Version: {version}")
    if len(sys.argv) > 1:
        expected = sys.argv[1].strip()
        if expected.startswith("v"):
            expected = expected[1:]
        if expected != version:
            raise SystemExit(
                f"Tag {sys.argv[1]!r} passt nicht zur Anwendung {version!r}."
            )
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
