"""Build the standalone GitHub Pages entry point from the frontend assets."""

from pathlib import Path

from build_frontend_snapshot import main as build_snapshot


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "deallens" / "frontend"


def main():
    build_snapshot()
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    css = (ASSETS / "styles.css").read_text(encoding="utf-8")
    data = (ASSETS / "data.js").read_text(encoding="utf-8")
    app = (ASSETS / "app.js").read_text(encoding="utf-8")

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

    output = ROOT / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
