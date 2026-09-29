"""Regenerate the browser-only snapshot from the validated local research files."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deallens.web import build_payload  # noqa: E402


def main():
    output = ROOT / "src" / "deallens" / "frontend" / "data.js"
    payload = build_payload(ROOT)
    output.write_text(
        "/* Source-derived local preview. Regenerate with scripts/build_frontend_snapshot.py. */\n"
        + "window.DEALLENS_SNAPSHOT = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}: {payload['summary']}")


if __name__ == "__main__":
    main()
