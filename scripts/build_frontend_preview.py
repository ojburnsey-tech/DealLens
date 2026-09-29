"""Build the standalone GitHub Pages entry point from the frontend assets."""

import argparse
import html as html_module
import os
from pathlib import Path
from urllib.parse import urlparse

from build_frontend_snapshot import snapshot_document


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "deallens" / "frontend"


def render_site(data, *, api_url=None):
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    css = (ASSETS / "styles.css").read_text(encoding="utf-8")
    app = (ASSETS / "app.js").read_text(encoding="utf-8")

    api_marker = '  <meta name="deallens-api" content="/api/data">\n'
    if html.count(api_marker) != 1:
        raise ValueError("expected exactly one API configuration marker")
    if api_url:
        parsed = urlparse(api_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError("DEALLENS_PUBLIC_API_URL must be an HTTPS URL without credentials, query or fragment")
        html = html.replace(api_marker, f'  <meta name="deallens-api" content="{html_module.escape(api_url, quote=True)}">\n')
    else:
        html = html.replace(api_marker, "")

    replacements = (
        ('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>"),
        ('  <script defer src="data.js"></script>\n', ""),
        ('  <script defer src="app.js"></script>\n', ""),
        ("</body>", f"<script>\n{data}\n</script>\n<script>\n{app}\n</script>\n</body>"),
    )
    for original, replacement in replacements:
        if html.count(original) != 1:
            raise ValueError(f"expected exactly one frontend marker: {original}")
        html = html.replace(original, replacement)
    return html


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build or check the standalone DealLens page")
    parser.add_argument("--check", action="store_true", help="fail if committed page or snapshot is stale")
    args = parser.parse_args(argv)
    data, payload = snapshot_document(ROOT)
    html = render_site(data, api_url=os.environ.get("DEALLENS_PUBLIC_API_URL"))

    output = ROOT / "index.html"
    snapshot = ASSETS / "data.js"
    if args.check:
        if not output.exists() or not snapshot.exists() or output.read_text(encoding="utf-8") != html or snapshot.read_text(encoding="utf-8") != data:
            parser.exit(1, "Frontend build is stale. Run python scripts/build_frontend_preview.py and commit the outputs.\n")
        print("Frontend build is current")
        return
    snapshot.write_text(data, encoding="utf-8")
    output.write_text(html, encoding="utf-8")
    print(f"Wrote {output}: {payload['summary']}")


if __name__ == "__main__":
    main()
