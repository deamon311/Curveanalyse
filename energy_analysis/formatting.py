"""Formatage cohérent des chiffres affichés au client."""

from __future__ import annotations

import math

MONTH_NAMES = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}


def swiss_number(value: float | int | None, decimals: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    rendered = f"{float(value):,.{decimals}f}"
    return rendered.replace(",", "’").replace(".", ",")


def kwh(value: float | int | None, decimals: int = 0) -> str:
    return f"{swiss_number(value, decimals)} kWh"


def kw(value: float | int | None, decimals: int = 2) -> str:
    return f"{swiss_number(value, decimals)} kW"


def chf(value: float | int | None, decimals: int = 0) -> str:
    return f"CHF {swiss_number(value, decimals)}"


def pct(value: float | int | None, decimals: int = 1, sign: bool = False) -> str:
    prefix = "+" if sign and value is not None and value > 0 else ""
    return f"{prefix}{swiss_number(value, decimals)} %"


def hours(value: float | int | None, decimals: int = 0) -> str:
    return f"{swiss_number(value, decimals)} h"


def time_label(minutes: int) -> str:
    minutes = int(minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
