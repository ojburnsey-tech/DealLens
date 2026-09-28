"""Source-footnoted A4 research reports; finance remains in the service layer."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .models import Fact, Model, Result, walk_facts
from .qa import qa_deal
from .research import ResearchDeal, analyse


def _text(value: object) -> str:
    """Escape all research text before passing it to ReportLab's XML parser."""
    return escape(str(value)).replace('\n', '<br/>')


def _number(value: Decimal | None, unit: str, currency: str | None = None) -> str:
    if value is None:
        return 'Unavailable'
    if unit == 'fraction':
        return f'{value * 100:,.2f}%'
    if unit == 'ratio':
        return f'{value:,.2f}x'
    suffix = {'currency': '', 'currency/share': ' per share', 'shares': ' shares',
              'months': ' months'}.get(unit, f' {unit}')
    return f'{currency + " " if currency else ""}{value:,.2f}{suffix}'


def build_report(deal: ResearchDeal, output: Path) -> Path:
    """Atomically write an A4 analyst report without modifying the research record.

    Sections flow continuously, expanding when research needs additional space.
    DRAFT and REVIEWED reports remain explicitly unverified. Precedents and owner
    conclusions are unavailable unless separately researched; neither is inferred.
    """
    output = Path(output)
    if output.suffix.lower() != '.pdf':
        raise ValueError('report output must have a .pdf suffix')
    calculations = analyse(deal)
    qa = qa_deal(deal)
    styles = {
        'title': ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=23, leading=27,
                                textColor=colors.HexColor('#17334a'), spaceAfter=13),
        'section': ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=12, leading=15,
                                  textColor=colors.HexColor('#17334a'), spaceBefore=12,
                                  spaceAfter=6, keepWithNext=True),
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9, leading=12,
                               spaceAfter=3, alignment=TA_LEFT, splitLongWords=True),
        'small': ParagraphStyle('small', fontName='Helvetica', fontSize=7.5, leading=10,
                                textColor=colors.HexColor('#425466'), spaceAfter=2,
                                splitLongWords=True),
    }
    story: list[Any] = []
    evidence = {item.evidence_id: item for item in deal.field_evidence}
    source_numbers = {item.source_id: n for n, item in enumerate(deal.sources, 1)}

    def paragraph(text: object, style: str = 'body') -> None:
        story.append(Paragraph(_text(text), styles[style]))

    def section(title: str) -> None:
        paragraph(title, 'section')

    def references(ids: tuple[str, ...] | list[str]) -> str:
        return ' '.join(f'[{source_numbers[evidence[key].source_id]} / {key}]' for key in ids)

    def fact_line(label: str, fact: Fact | None) -> None:
        if fact is None:
            paragraph(f'{label}: Unavailable')
            return
        period = (f' | {fact.period.basis} {fact.period.start} to {fact.period.end}'
                  if fact.period else '')
        paragraph(f'{label}: {_number(fact.amount, fact.unit, fact.currency)} | '
                  f'{fact.classification}{period} {references(fact.evidence)}')
        details = fact.definition
        if fact.as_of:
            details += f' | Reference date: {fact.as_of}'
        if fact.ambiguity:
            details += f' | Ambiguity: {fact.ambiguity}'
        paragraph(details, 'small')
        if fact.derivation:
            paragraph(f'Formula: {fact.derivation.formula}; basis: {fact.derivation.basis}', 'small')
            for warning in (*fact.derivation.warnings, *fact.derivation.qualifications):
                paragraph(f'Qualification: {warning}', 'small')

    def result_lines(label: str, value: Any, currency: str | None = None) -> None:
        if isinstance(value, Result):
            refs = sorted({key for _, fact in walk_facts(value.inputs) for key in fact.evidence})
            period = (f' | {value.period.basis} {value.period.start} to {value.period.end}'
                      if value.period else '')
            paragraph(f'{label}: {_number(value.result, value.unit, value.currency)} | CALCULATED'
                      f'{" | ILLUSTRATIVE" if value.illustrative else ""}{period} {references(refs)}')
            paragraph(f'Formula: {value.formula} | Basis: {value.basis}', 'small')
            for warning in (*value.warnings, *value.qualifications):
                paragraph(f'Qualification: {warning}', 'small')
        elif isinstance(value, Fact):
            fact_line(label, value)
        elif isinstance(value, Model):
            details = []
            for key in type(value).model_fields:
                child = getattr(value, key)
                if isinstance(child, (Fact, Result)):
                    result_lines(f'{label} / {key.replace("_", " ")}', child)
                elif child is not None:
                    details.append(f'{key.replace("_", " ")}: {child}')
            if details:
                paragraph("; ".join(details), "small")
        elif isinstance(value, Mapping):
            currencies = {fact.currency for _, fact in walk_facts(value) if fact.currency}
            local_currency = next(iter(currencies)) if len(currencies) == 1 else currency
            for key, child in value.items():
                result_lines(f'{label} / {str(key).replace("_", " ")}', child, local_currency)
        elif isinstance(value, (list, tuple)):
            for n, child in enumerate(value, 1):
                result_lines(f'{label} {n}', child, currency)
        elif isinstance(value, Decimal):
            unit = ('shares' if 'shares' in label else
                    'fraction' if 'relative difference' in label else 'currency')
            paragraph(f'{label}: {_number(value, unit, currency if unit == "currency" else None)}'
                      ' | CALCULATED', 'small')
        elif value is None:
            paragraph(f'{label}: Unavailable', 'small')
        else:
            paragraph(f'{label}: {value}', 'small')

    def calculation(key: str, label: str) -> None:
        if key not in calculations:
            paragraph(f'{label}: Unavailable - required research inputs have not been established.')
        else:
            result_lines(label, calculations[key])

    def narrative(items: list[str]) -> None:
        for item in items or ['Unavailable - no analyst research supplied.']:
            paragraph(item)

    paragraph('DealLens', 'title')
    paragraph(deal.identity.name, 'section')
    paragraph(f'{deal.identity.deal_id} | {deal.review_status} | '
              f'{"Manual verification recorded" if deal.review_status == "VERIFIED" else "NOT VERIFIED - research working paper"}')
    section('Transaction Snapshot')
    for label, value in [('Bidder', deal.bidder.name), ('Target', deal.target.name),
                         ('Announcement', deal.identity.announcement_date),
                         ('Status', deal.identity.transaction_status),
                         ('Completion', deal.identity.completion_date or 'Unavailable'),
                         ('Sector', deal.profile.sector or 'Unavailable'),
                         ('Target country', deal.target.country)]:
        paragraph(f'{label}: {value}')
    section('Strategic Rationale')
    narrative(deal.strategic_rationale)
    section('Offer Chronology')
    for offer in deal.offer_terms:
        fact_line(f'{offer.date} | {offer.stage} offer ({offer.offer_id})', offer.price)
        paragraph(f'Offer basis: {offer.basis}', 'small')
    if not deal.offer_terms:
        paragraph('Unavailable')
    paragraph(f'Selected offer: {deal.selected_offer_id or "Unavailable"}', 'small')
    section('Key Risks')
    narrative(deal.risks)

    section('Valuation')
    valuation = deal.transaction_valuation
    fact_line('Reported equity value', valuation.reported_equity_value)
    fact_line('Reported enterprise value', valuation.reported_enterprise_value)
    fact_line('Reported transaction value (separate definition)', valuation.reported_transaction_value)
    paragraph(f'Preferred EV basis: {valuation.preferred_ev_basis}', 'small')
    for key in ('equity', 'ev', 'ev_revenue', 'ev_ebitda', 'ev_ebit', 'equity_net_income'):
        if key in calculations:
            calculation(key, key.replace('_', ' '))
    section('Premium Analysis')
    for ref in deal.unaffected_price:
        fact_line(f'{ref.reference_id} | {ref.reference_basis} | {ref.reference_date}', ref.price)
        paragraph(f'Analyst reference selection: {ref.selection_notes}', 'small')
    calculation('premiums', 'Premium')
    section('Precedent Transactions')
    paragraph('Unavailable - no human-selected precedent set supplied. '
              'Comparable selection remains an analyst judgement.')

    section('Target Financial Performance')
    for name in ('revenue', 'ebitda', 'ebit', 'net_income'):
        series = getattr(deal.target_financials, name)
        fact_line(name.replace('_', ' ').title(), series.selected)
        if f'ltm_{name}' in calculations:
            for input_name in ('latest_fy', 'current_ytd', 'prior_ytd'):
                fact = getattr(series, input_name)
                if fact is not None:
                    period = (f'{fact.period.basis} {fact.period.start} to {fact.period.end}'
                              if fact.period else 'period unavailable')
                    paragraph(f'{input_name}: {_number(fact.amount, fact.unit, fact.currency)} | '
                              f'{period} | {fact.classification} {references(fact.evidence)}', 'small')
            calculation(f'ltm_{name}', f'LTM reconstruction: {name}')
    for name in ('cash', 'debt', 'net_debt'):
        fact_line(name.replace('_', ' ').title(), getattr(deal.target_financials, name))
    section('Synergies')
    for synergy in deal.synergies:
        paragraph(f'{synergy.kind}: {synergy.basis}; eligible: {synergy.eligible}; '
                  f'realisation: {synergy.realisation_months if synergy.realisation_months is not None else "Unavailable"} months', 'small')
        for path, fact in walk_facts(synergy):
            fact_line(f'{synergy.kind} / {path}', fact)
    calculation('synergies', 'Synergy analysis - illustrative')
    section('Financing')
    paragraph((deal.financing.description or 'Unavailable') + ' ' + references(deal.financing.evidence))
    for path, fact in walk_facts(deal.financing):
        fact_line(path.replace('_', ' '), fact)

    section('Leverage')
    if deal.leverage_inputs:
        for path, fact in walk_facts(deal.leverage_inputs):
            fact_line(path.replace('_', ' '), fact)
    calculation('leverage', 'Acquisition leverage')
    section('Simplified Accretion/Dilution')
    paragraph('Simplified EPS model. Excludes detailed purchase-price accounting '
              'unless those adjustments are separately supplied.')
    calculation('accretion', 'Simplified EPS accretion/dilution')
    section('Analyst View')
    paragraph('Unavailable - the owner\'s final interpretation has not been supplied. '
              'No investment conclusion is generated automatically.')
    section('Sources & Assumptions')
    paragraph('Values are shown in their labelled currency and base unit. Display rounding '
              'does not alter stored calculations. Missing values remain unavailable; '
              'illustrative calculations are scenarios, not forecasts.', 'small')
    for note in deal.review_notes.notes:
        paragraph(f'Review note: {note}', 'small')
    for flag in qa["flags"]:
        paragraph(f'QA {flag.severity} / {flag.code}: {flag.message}', 'small')
    for source in deal.sources:
        paragraph(f'[{source_numbers[source.source_id]}] {source.title} | '
                  f'{source.publication_date} | {source.source_type}\n{source.url}', 'small')
        for item in deal.field_evidence:
            if item.source_id == source.source_id:
                paragraph(f'{item.evidence_id}: {item.section}; reported unit: '
                          f'{item.reported_unit}; {item.note}', 'small')
    if not deal.sources:
        paragraph('Source evidence: Unavailable')

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#d7dfe5'))
        canvas.line(19 * mm, 18 * mm, A4[0] - 19 * mm, 18 * mm)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#425466'))
        canvas.drawString(19 * mm, 13 * mm, f'DealLens | {deal.identity.deal_id} | {deal.review_status}')
        canvas.drawRightString(A4[0] - 19 * mm, 13 * mm, f'Page {doc.page}')
        canvas.restoreState()

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.deallens-report-', suffix='.pdf', dir=output.parent)
    os.close(descriptor)
    try:
        document = SimpleDocTemplate(temporary, pagesize=A4, rightMargin=19 * mm,
                                     leftMargin=19 * mm, topMargin=18 * mm, bottomMargin=24 * mm,
                                     title=f'DealLens {deal.identity.deal_id}', author='DealLens')
        story.append(Spacer(1, 1))
        document.build(story, onFirstPage=footer, onLaterPages=footer)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output
