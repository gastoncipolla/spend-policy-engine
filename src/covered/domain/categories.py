"""Closed catalog of expense categories (SPEC §2).

Unknown categories are validation errors everywhere: the catalog is an enum, so
Pydantic rejects anything that is not listed here.
"""

from enum import StrEnum


class Category(StrEnum):
    """Expense category code. The value is the wire/storage representation."""

    MEALS = "meals"
    GROUND_TRANSPORT = "ground_transport"
    LODGING = "lodging"
    AIRFARE = "airfare"
    SOFTWARE = "software"
    TRAINING = "training"
    ENTERTAINMENT = "entertainment"
    ALCOHOL = "alcohol"
    OTHER = "other"


CATEGORY_NAMES: dict[Category, str] = {
    Category.MEALS: "Meals",
    Category.GROUND_TRANSPORT: "Ground transport",
    Category.LODGING: "Lodging",
    Category.AIRFARE: "Airfare",
    Category.SOFTWARE: "Software",
    Category.TRAINING: "Training",
    Category.ENTERTAINMENT: "Entertainment",
    Category.ALCOHOL: "Alcohol",
    Category.OTHER: "Other",
}
"""Human-readable name for each category code."""
