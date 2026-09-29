# DealLens HTML workspace

The interface is a read-only local research workspace. It shows validated inbox
YAML and database records, but portfolio analytics draw only on `VERIFIED`
database records that pass the existing QA gate. The Britvic record currently
remains `DRAFT`, so the valuation sample is intentionally empty.

## Run

From the project root, install the package dependencies and start the server:

```bash
python -m pip install -e .
deallens-web
```

Open <http://127.0.0.1:8765>. `python -m deallens.web --port 9000` also works.
Use `--project` to point to a different research directory and `--db` to select
an existing DuckDB file. No database is created just to display the inbox.
There are no write endpoints or browser-side verification controls.

For a browser-only preview, open `src/deallens/frontend/index.html`. It uses a
bundled snapshot generated from the repository's validated research. Refresh
that snapshot after editing the research files:

```bash
python scripts/build_frontend_snapshot.py
python scripts/build_frontend_preview.py
```

The browser labels the bundled preview separately from live local data. Opening
the HTML directly does not refresh the snapshot or access the database.
`DealLens-preview.html` combines the HTML, CSS, JavaScript and snapshot into
one offline file for easy review.

## Files

- `src/deallens/frontend/index.html`: page structure and accessible navigation
- `src/deallens/frontend/styles.css`: responsive visual system
- `src/deallens/frontend/app.js`: views, search, filters, source links, export
- `src/deallens/frontend/data.js`: generated source-derived offline snapshot
- `src/deallens/web.py`: read-only HTTP API and static server

The deal view shows reported values alongside their source IDs and definitions.
It does not elevate a source link into a claim that its content has been
independently reviewed. Export saves the displayed research record as JSON.
