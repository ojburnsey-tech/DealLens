# Transaction PDF reports

`deallens report build DL-00001 --output output/pdf/DL-00001.pdf` renders the stored research record as an A4 PDF. The Python API is `deallens.reports.build_report(deal, output: Path) -> Path`.

Install the project dependencies before running the command. The generator uses ReportLab; tests use pypdf. It calls the existing research analysis and QA services, so it does not maintain separate financial formulas. Decimal values are rounded only for display, monetary amounts use labelled base currency units, and percentages convert stored fractions to percentage displays.

The document includes Transaction Snapshot, Strategic Rationale, Offer Chronology, Valuation, Premium Analysis, Target Financial Performance, Precedent Transactions, Synergies, Financing, Leverage, Simplified Accretion/Dilution, Key Risks, Analyst View, and Sources & Assumptions. Financial observations identify their reported, calculated or assumption classification, financial period, and evidence references. Calculations retain their formula, basis, warnings and qualifications. Source endnotes retain publication dates, URLs, document sections, reported units and evidence notes.

The current Britvic working paper produces five pages. Page count is driven by available material: long narratives or evidence ledgers expand onto additional pages without truncation, while sparse records can be shorter. Every page identifies the deal, review status and page number. Draft reports remain clearly marked NOT VERIFIED; generating a report never verifies or changes its input record. Output replacement is atomic, preserving an existing PDF if rendering fails.

The generator does not invent precedent selection or the owner's final investment judgement. Those sections are explicitly unavailable because the current research schema does not yet store an approved comparable set or owner conclusion. Missing leverage and EPS inputs also remain unavailable. These are working research PDFs, not the five completed owner-authored case studies required for the final release.

Validation covers the real draft's 15 sections and five-page layout, source/period/unit labels, unverified status, long paragraph splitting, literal XML-like research text, A4 dimensions, footer numbering, text boundary checks, and failure cleanup. Rendered pages are inspected with Poppler during development. No copyrighted primary-source documents are embedded in the PDF.
