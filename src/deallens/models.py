"""Shared immutable financial observations and research provenance models."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Text = Annotated[str, Field(min_length=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Period(Model):
    start: date
    end: date
    basis: Literal["FY", "YTD", "LTM", "FORECAST", "RUN_RATE"]

    @model_validator(mode="after")
    def chronological(self):
        if self.end < self.start:
            raise ValueError("period end precedes start")
        return self


class Fact(Model):
    """One observation. Values stay in reported units; amount normalises on demand.

    A fraction is used for rates (0.25 = 25%). Monetary scales are explicit and
    never inferred from the size of a number. No implicit currency conversion.
    """
    value: Decimal | None
    unit: Literal["currency", "currency/share", "shares", "fraction", "ratio", "months"]
    currency: str | None = None
    scale: Decimal = Decimal(1)
    definition: Text
    period: Period | None = None
    as_of: date | None = None
    evidence: tuple[str, ...] = ()
    classification: Literal["REPORTED", "CALCULATED", "ASSUMPTION"] = "REPORTED"
    ambiguity: str | None = None
    derivation: "Result | None" = None

    @field_validator("value", "scale", mode="before")
    @classmethod
    def no_booleans(cls, value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a financial number")
        return value

    @model_validator(mode="after")
    def valid_units(self):
        if not self.scale.is_finite() or self.scale <= 0:
            raise ValueError("scale must be finite and positive")
        if self.value is not None and not self.value.is_finite():
            raise ValueError("value must be finite")
        monetary = self.unit in ("currency", "currency/share")
        if monetary and (not self.currency or len(self.currency) != 3 or not self.currency.isupper()):
            raise ValueError("monetary facts require a three-letter uppercase currency")
        if not monetary and self.currency is not None:
            raise ValueError("non-monetary facts cannot have a currency")
        if self.unit in ("fraction", "ratio", "months") and self.scale != 1:
            raise ValueError("rates, ratios and months require scale 1")
        if self.derivation is not None:
            source = self.derivation
            if (self.classification != "CALCULATED" or self.amount != source.result or
                    self.unit != source.unit or self.currency != source.currency or self.period != source.period):
                raise ValueError("calculated fact must match derivation value, unit, currency, period and classification")
            inherited = {e for _, fact in walk_facts(source.inputs) for e in fact.evidence}
            if set(self.evidence) != inherited:
                raise ValueError("derived evidence must match participating calculation inputs")
        return self

    @property
    def amount(self) -> Decimal | None:
        return None if self.value is None else self.value * self.scale


class Source(Model):
    source_id: Text
    title: Text
    url: HttpUrl
    publication_date: date
    source_type: Literal["ANNOUNCEMENT", "SCHEME", "ANNUAL_REPORT", "INTERIM_REPORT", "ISSUER", "REGULATOR"]


class Evidence(Model):
    evidence_id: Text
    source_id: Text
    section: Text
    reported_unit: Text
    note: Text


class Result(Model):
    """Full inputs are retained, including their evidence and definitions."""
    result: Decimal | None
    unit: str
    currency: str | None = None
    formula: str
    basis: str
    inputs: dict[str, Any]
    warnings: tuple[str, ...] = ()
    period: Period | None = None
    illustrative: bool = False
    qualifications: tuple[str, ...] = ()

    @field_validator("inputs", mode="before")
    @classmethod
    def restore_observations(cls, value):
        """Restore nested facts after JSON so further derivations retain evidence."""
        def restore(item):
            if isinstance(item, dict):
                if {"value", "unit", "definition"}.issubset(item):
                    return Fact.model_validate(item)
                if {"result", "unit", "formula", "basis", "inputs"}.issubset(item):
                    return Result.model_validate(item)
                return {key: restore(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [restore(child) for child in item]
            return item
        return restore(value)



Fact.model_rebuild()

def walk_facts(value, path=""):
    """Yield stable dotted paths for every observation in a research object."""
    if isinstance(value, Fact):
        yield path, value
    elif isinstance(value, BaseModel):
        for key in type(value).model_fields:
            yield from walk_facts(getattr(value, key), f"{path}.{key}".strip("."))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk_facts(item, f"{path}.{key}".strip("."))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from walk_facts(item, f"{path}.{index}".strip("."))
