"""Notebook I/O and chart presentation; finance lives in the service layer."""
from pathlib import Path
from typing import Any

from .analytics import category_counts, data_quality_summary, metric_summary, portfolio_summary
from .research import load_research


def research_root() -> Path:
    """Find the checkout without assuming the notebook working directory."""
    candidates = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]]
    for path in candidates:
        if (path / 'pyproject.toml').is_file() and (path / 'research').is_dir():
            return path
    raise ValueError('Run notebooks from the DealLens checkout; no research directory found')


def load_inventory(root: Path | None = None) -> list:
    root = root or research_root()
    # If a reviewed export exists, it supersedes the same draft ID in the inbox.
    records = {}
    for folder in ('inbox', 'verified'):
        seen = set()
        for path in sorted((root / 'research' / folder).glob('*.yml')):
            deal = load_research(path)
            if deal.identity.deal_id in seen:
                raise ValueError(f'duplicate research ID in {folder}')
            seen.add(deal.identity.deal_id)
            records[deal.identity.deal_id] = deal
    return list(records.values())


def metric_charts(report: dict[str, Any]) -> list:
    """One chart per comparable cohort; title includes metric/unit/n/basis."""
    import matplotlib.pyplot as plt
    figures = []
    for cohort in report['cohorts']:
        fig, ax = plt.subplots(figsize=(9, 4), layout='constrained')
        items = cohort['observations']
        ax.bar([x.deal_id for x in items], [float(x.value) for x in items], color='#48667a')
        unit = cohort['unit'] + (f" {cohort['currency']}" if cohort['currency'] else '')
        ax.set_ylabel(unit)
        ax.set_xlabel('Deal ID')
        ax.set_title(f"{cohort['metric']} | {unit} | n={cohort['n']}\n{cohort['basis']}", fontsize=10, wrap=True)
        ax.tick_params(axis='x', rotation=45)
        ax.spines[['top', 'right']].set_visible(False)
        figures.append(fig)
    if not figures:
        print(f"{report['metric']}: no eligible observations (n=0); no chart or zero-valued estimate produced.")
    return figures


def outcome_chart(report: dict[str, Any]):
    import matplotlib.pyplot as plt
    if not report['n']:
        print('Deal outcomes | unit=deals | n=0 | VERIFIED and publishable: no observations.')
        return None
    fig, ax = plt.subplots(figsize=(9, 4), layout='constrained')
    ax.bar([x['category'] for x in report['categories']], [x['n'] for x in report['categories']], color='#48667a')
    ax.set_title(f"Deal outcomes | unit=deals | n={report['n']} | VERIFIED and publishable")
    ax.set_ylabel('Deals')
    ax.spines[['top', 'right']].set_visible(False)
    return fig


__all__ = ['load_inventory', 'data_quality_summary', 'portfolio_summary', 'metric_summary',
           'category_counts', 'metric_charts', 'outcome_chart']
