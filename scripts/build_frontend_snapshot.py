"""Render the public browser snapshot from validated repository research."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deallens.web import build_public_payload  # noqa: E402


def snapshot_document(project=ROOT):
    payload = build_public_payload(project)
    document = (
        "/* Source-derived public snapshot. Regenerate with scripts/build_frontend_preview.py. */\n"
        + "window.DEALLENS_SNAPSHOT = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        + ";\n"
    )
    return document, payload


def main():
    output = ROOT / "src" / "deallens" / "frontend" / "data.js"
    document, payload = snapshot_document()
    output.write_text(document, encoding="utf-8")
    print(f"Wrote {output}: {payload['summary']}")


if __name__ == "__main__":
    main()
