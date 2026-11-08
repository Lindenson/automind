"""The extraction areas (spec 003 R8): which attributes a spec area may claim, which versioned prompt reads each area,
and the answer schema of each area (`contracts.py`; the spec areas' claim schemas are built here per area)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field, create_model

from automind.acquisition.parsing.extraction.contracts import (
    DepreciationItems,
    Excerpted,
    IncentiveFacts,
    IssueItems,
    MaintenanceItems,
    ManufacturerFacts,
    ReviewItems,
    UsedPriceItems,
)
from automind.shared.vehicle import specs

AREA_ATTRS: dict[str, list[str]] = {
    "specs": [k for k, a in specs.ATTRS.items() if a.category == "specs"],
    "engineering": [k for k, a in specs.ATTRS.items() if a.category == "engineering"],
    "measured": [k for k, a in specs.ATTRS.items() if a.category == "measured"],
    "price": ["official_price_es"],
    "maintenance": ["service_interval_km", "service_interval_months"],
}
SPEC_AREAS = ("specs", "engineering", "measured", "price")
PROMPT_FOR_AREA = {
    "used_price": "extract_used_price",
    "depreciation": "extract_depreciation",
    "specs": "extract_specs",
    "engineering": "extract_specs",
    "measured": "extract_specs",
    "price": "extract_specs",
    "maintenance": "extract_maintenance",
    "reviews": "extract_reviews",
    "reliability": "extract_reliability",
    "used_issues": "extract_reliability",
    "manufacturer": "extract_manufacturer",
    "incentives": "extract_incentives",
}
ITEM_SCHEMAS: dict[str, type[BaseModel]] = {
    "maintenance": MaintenanceItems,
    "reviews": ReviewItems,
    "reliability": IssueItems,
    "used_issues": IssueItems,
    "manufacturer": ManufacturerFacts,
    "used_price": UsedPriceItems,
    "depreciation": DepreciationItems,
    "incentives": IncentiveFacts,
}


def schema_for(area: str) -> type[BaseModel]:
    """The extractor's answer schema for `area`; KeyError for an unknown area."""
    if area in SPEC_AREAS:
        return spec_claims_schema(area)
    return ITEM_SCHEMAS[area]


def spec_claims_schema(area: str) -> type[BaseModel]:
    """`SpecClaims_<area>`: claims whose `attribute` is one of the area's attribute names. The names are data, so the
    claim model is built at run time (its field types are values here, hence `dict[str, Any]`)."""
    claim_fields: dict[str, Any] = {
        "attribute": (cast(Any, Literal)[tuple(AREA_ATTRS[area])], ...),
        "raw_value": (str, Field(description="Value exactly as written, e.g. '245 CV', '1.430', '6,2'")),
        "unit": (str | None, Field(description="Unit as written, e.g. 'CV', 'kW', 'Nm', 'kg', 's', 'mm', 'EUR'")),
        "scope": (
            Literal["VARIANT", "GENERATION", "ENGINE"],
            Field(description="VARIANT if stated for this exact variant"),
        ),
    }
    claim = create_model(f"SpecClaim_{area}", __base__=Excerpted, **claim_fields)
    claims_fields: dict[str, Any] = {
        "is_about_variant": (bool, Field(description="False if the document is about a different car/generation")),
        "claims": (list.__class_getitem__(claim), ...),
    }
    return create_model(f"SpecClaims_{area}", **claims_fields)
