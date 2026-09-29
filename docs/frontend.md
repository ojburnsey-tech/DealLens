# DealLens web interface

Open the [DealLens site](https://ojburnsey-tech.github.io/DealLens/) to go straight
to the research workspace. GitHub Pages publishes the root `index.html`; the
page contains its CSS, JavaScript, and source-derived research data, so visitors
do not need to install Python or start a local server.

The site is read-only. Its bundled data is generated from validated repository
inbox research and, when present, an audited release under `public/release/`.
The public build never reads a local DuckDB file. GitHub Pages does not execute
the Python research engine or connect to a live database. The currently
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
live in `src/deallens/frontend/`. The repository workflow checks that the
committed page and snapshot still match the research and source files; you can
run the same check locally with `python scripts/build_frontend_preview.py --check`.

For live data during local development, run `deallens-web` from the project
root and open <http://127.0.0.1:8765>. The server reads an existing DuckDB
database and validated inbox files through `/api/data`. It does not create a
database merely to display the page. If the API fails, the interface shows an
error instead of silently substituting the bundled snapshot.

A GitHub Pages page can use a separately hosted HTTPS API by setting
`DEALLENS_PUBLIC_API_URL` when building `index.html`. Set
`DEALLENS_PUBLIC_ORIGIN=https://ojburnsey-tech.github.io` on that API host so
the browser accepts its response. For public hosting, set
`DEALLENS_PUBLIC_RELEASE` to an existing audited release directory; the API
then serves that release and the repository inbox rather than a local DuckDB.
No external API is configured in the current published page.

A source link in the ledger identifies the recorded source; it does not imply
independent review. The download button saves a case summary as JSON; it is
not a full research database export.
