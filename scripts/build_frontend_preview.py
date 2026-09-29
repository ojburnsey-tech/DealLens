"""Combine the four frontend assets into an HTML file that opens offline."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "deallens" / "frontend"


def main():
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    css = (ASSETS / "styles.css").read_text(encoding="utf-8")
    data = (ASSETS / "data.js").read_text(encoding="utf-8")
    app = (ASSETS / "app.js").read_text(encoding="utf-8")

    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace('  <script defer src="data.js"></script>\n', "")
    html = html.replace('  <script defer src="app.js"></script>\n', "")
    html = html.replace("</body>", f"<script>\n{data}\n</script>\n<script>\n{app}\n</script>\n</body>")

    output = ROOT / "DealLens-preview.html"
    output.write_text(html, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
