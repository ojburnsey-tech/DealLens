"""PDF boundaries, provenance, missing data and escaping regression checks."""
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from deallens.reports import build_report
from deallens.research import load_research

ROOT = Path(__file__).resolve().parents[1]


def test_real_draft_report_has_all_sections_and_source_units(tmp_path):
    deal = load_research(ROOT / 'research/inbox/DL-00001.yml')
    original = deal.model_dump_json()
    path = build_report(deal, tmp_path / 'deal.pdf')
    reader = PdfReader(path)
    assert 3 <= len(reader.pages) <= 5
    text = '\n'.join(page.extract_text() for page in reader.pages)
    for title in ['Transaction Snapshot', 'Strategic Rationale', 'Offer Chronology', 'Valuation',
                  'Premium Analysis', 'Target Financial Performance', 'Precedent Transactions',
                  'Synergies', 'Financing', 'Leverage', 'Simplified Accretion/Dilution',
                  'Key Risks', 'Analyst View', 'Sources & Assumptions']:
        assert title in text
    for expected in ['NOT VERIFIED', 'GBP 13.15 per share', '35.57%', 'REPORTED', 'CALCULATED',
                     'ILLUSTRATIVE', 'reported unit:', '2024-07-08', 'Unavailable',
                     'purchase-price accounting', 'MANUAL_VERIFICATION_REQUIRED', 'Formula:']:
        assert expected in text
    assert 'Fact(value=' not in text
    assert "Decimal('" not in text
    assert deal.model_dump_json() == original
    for n, page in enumerate(reader.pages, 1):
        assert f'Page {n}' in page.extract_text()
        assert float(page.mediabox.width) == pytest.approx(A4[0], abs=.01)
        assert float(page.mediabox.height) == pytest.approx(A4[1], abs=.01)


def test_report_wraps_long_narrative_and_escapes_markup(tmp_path):
    deal = load_research(ROOT / 'research/inbox/DL-00001.yml')
    literal = '<b>Research & risk</b> '
    deal = deal.model_copy(update={'risks': [literal + 'Long research narrative. ' * 1200 + ' END-RISK']})
    path = build_report(deal, tmp_path / 'long.pdf')
    reader = PdfReader(path)
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert '<b>Research & risk</b>' in text
    assert 'END-RISK' in text
    assert 'Sources & Assumptions' in text
    assert len(reader.pages) > 5  # Never truncate research merely to meet a page target.
    for page in reader.pages:
        def position_check(text, cm, tm, font, size):
            if text.strip():
                # ReportLab paragraphs use translation matrices; check the visible origin.
                y = cm[5] + tm[5]
                assert y >= 30, (text, y)
                assert y <= A4[1] - 25, (text, y)
        page.extract_text(visitor_text=position_check)


def test_output_suffix_and_atomic_failure_preserve_existing_file(tmp_path, monkeypatch):
    deal = load_research(ROOT / 'research/inbox/DL-00001.yml')
    with pytest.raises(ValueError, match='suffix'):
        build_report(deal, tmp_path / 'not-a-pdf.txt')
    output = tmp_path / 'previous.pdf'
    output.write_bytes(b'previous report')
    def fail(*args, **kwargs):
        raise RuntimeError('render failed')
    monkeypatch.setattr('deallens.reports.SimpleDocTemplate.build', fail)
    with pytest.raises(RuntimeError, match='render failed'):
        build_report(deal, output)
    assert output.read_bytes() == b'previous report'
    assert list(tmp_path.glob('.deallens-report-*')) == []
