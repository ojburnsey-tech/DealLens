# DealLens web interface

Open the [DealLens site](https://ojburnsey-tech.github.io/DealLens/) to go straight
to the research workspace. GitHub Pages publishes the root `index.html`; the
page contains its CSS, JavaScript, and source-derived research data, so visitors
do not need to install Python or start a local server.

The site is read-only. Its data is generated from validated repository research
when the root page is rebuilt and committed. GitHub Pages does not execute the
Python research engine or connect to a live DuckDB database. The currently
included Britvic case is DRAFT; it remains visible in the ledger but does not
count as a verified portfolio observation.

This repository already publishes GitHub Pages from the `main` branch. Once
the root `index.html` is pushed, the existing Pages URL opens the interface
instead of displaying the README.

To regenerate the same page locally after changing research or interface files:

```bash
python -m pip install -e .
python scripts/build_frontend_preview.py
```

Commit the generated `index.html` with any research or interface updates to
publish them. Open it directly in a browser for a local preview. The source assets
live in `src/deallens/frontend/`; `src/deallens/web.py` remains available for
optional local API use. A source link in the ledger identifies the recorded
source; it does not imply independent review. Export downloads the displayed
research record as JSON.
