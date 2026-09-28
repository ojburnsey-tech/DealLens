from datetime import date
from decimal import Decimal

import pytest

from deallens.models import Fact, Period
from deallens.research import Company, Identity, ResearchDeal


def fact(value, unit="currency", *, definition="adjusted earnings", currency="GBP", scale=1,
         period=None, as_of=None, evidence=()):
    return Fact(value=None if value is None else Decimal(str(value)), unit=unit,
                currency=currency if unit.startswith("currency") else None,
                scale=Decimal(str(scale)), definition=definition, period=period, as_of=as_of, evidence=evidence)


@pytest.fixture
def fy():
    return Period(start=date(2023, 1, 1), end=date(2023, 12, 31), basis="FY")


@pytest.fixture
def draft():
    return ResearchDeal(identity=Identity(deal_id="DL-00001", name="Buyer / Target", announcement_date=date(2024, 7, 1)),
                        bidder=Company(name="Buyer", country="GB"), target=Company(name="Target", country="GB"))
