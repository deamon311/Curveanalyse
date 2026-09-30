from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from energy_analysis.config import AnalysisSettings
from energy_analysis.ingest import (
    apply_timestamp_convention,
    combine_imports,
    read_energy_file,
)
from energy_analysis.metrics import (
    add_analysis_flags,
    annual_summary,
    comparable_years,
    profile_metrics,
)
from energy_analysis.models import ImportedFile
from energy_analysis.recommendations import build_recommendations


def canonical(
    timestamps: list[str],
    import_kw: list[float] | None = None,
    export_kw: list[float] | None = None,
    source: str = "source.xlsx",
) -> pd.DataFrame:
    timestamps_series = pd.to_datetime(timestamps)
    import_values = import_kw or [0.0] * len(timestamps_series)
    export_values = export_kw or [0.0] * len(timestamps_series)
    return pd.DataFrame(
        {
            "timestamp": timestamps_series,
            "import_kw": import_values,
            "export_kw": export_values,
            "import_kwh": np.asarray(import_values, dtype=float) * 0.25,
            "export_kwh": np.asarray(export_values, dtype=float) * 0.25,
            "interval_h": 0.25,
            "import_valid": True,
            "export_valid": True,
            "valid_measurement": True,
            "source_file": source,
            "sheet_name": "Mesures",
            "source_row": range(1, len(timestamps_series) + 1),
            "input_unit": "kW moyen par intervalle",
        }
    )


def item(data: pd.DataFrame, name: str = "source.xlsx") -> ImportedFile:
    return ImportedFile(
        data=data,
        source_name=name,
        sheet_name="Mesures",
        nominal_interval_h=0.25,
    )


def test_excel_reader_calculates_quarter_hour_energy_and_preserves_missing_values(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "curve.xlsx"
    source = pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01 00:15", periods=4, freq="15min"),
            "Soutirage (kW)": [1.0, 1.0, "Manquant", 1.0],
            "Surplus solaire (kW)": [0.0, 0.0, "Manquant", 0.0],
        }
    )
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        source.to_excel(writer, index=False, startrow=5)

    imported = read_energy_file(file_path)

    assert imported.nominal_interval_h == 0.25
    assert imported.invalid_numeric_values == 2
    assert imported.data["valid_measurement"].sum() == 3
    assert imported.data["import_kwh"].sum() == 0.75
    assert pd.isna(imported.data.loc[2, "import_kwh"])


def test_gaps_do_not_create_artificial_energy_and_dst_is_not_a_business_gap() -> None:
    data = canonical(
        [
            "2025-03-30 01:30",
            "2025-03-30 01:45",
            "2025-03-30 03:00",
            "2025-03-30 03:15",
            "2025-04-01 03:15",
        ],
        import_kw=[4, 4, 4, 4, 4],
    )
    combined, quality = combine_imports([item(data)])

    assert combined["import_kwh"].sum() == 5.0
    assert quality.daylight_saving_forward_events == 1
    assert quality.estimated_missing_intervals > 0


def test_duplicate_timestamps_are_not_counted_twice() -> None:
    first = canonical(["2025-01-01 00:15"], import_kw=[4.0], source="a.xlsx")
    second = canonical(["2025-01-01 00:15"], import_kw=[4.0], source="b.xlsx")

    combined, quality = combine_imports([item(first, "a.xlsx"), item(second, "b.xlsx")])

    assert len(combined) == 1
    assert combined["import_kwh"].sum() == 1.0
    assert quality.identical_duplicates == 1


def test_end_of_interval_convention_closes_the_correct_year() -> None:
    data = canonical(
        ["2025-01-01 00:15", "2026-01-01 00:00"],
        import_kw=[1.0, 1.0],
    )
    prepared = apply_timestamp_convention(data, "end")
    summary = annual_summary(prepared)

    assert summary["year"].tolist() == [2025]
    assert summary.loc[0, "import_kwh"] == 0.5


def test_comparison_uses_only_valid_common_calendar_quarters() -> None:
    old = canonical(
        ["2025-01-01 00:15", "2025-01-01 00:30"],
        import_kw=[4.0, 8.0],
        source="2025.xlsx",
    )
    new = canonical(
        ["2026-01-01 00:15", "2026-01-01 00:30"],
        import_kw=[6.0, 10.0],
        source="2026.xlsx",
    )
    all_data = pd.concat([old, new], ignore_index=True)
    prepared = add_analysis_flags(
        apply_timestamp_convention(all_data, "end"), AnalysisSettings()
    )

    comparison, info = comparable_years(prepared, 2026, 2025)

    assert info is not None
    assert info["measurements"] == 2
    assert comparison.loc[comparison["year"] == 2025, "import_kwh"].iloc[0] == 3.0
    assert comparison.loc[comparison["year"] == 2026, "import_kwh"].iloc[0] == 4.0


def test_profile_recommendations_prioritise_pilotage_before_battery() -> None:
    timestamps: list[str] = []
    imports: list[float] = []
    exports: list[float] = []
    for day in ("2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04"):
        for hour in range(24):
            for minute in (0, 15, 30, 45):
                timestamps.append(f"{day} {hour:02d}:{minute:02d}")
                imports.append(3.0 if hour < 6 else 0.2)
                exports.append(4.0 if 10 <= hour < 16 else 0.0)
    data = canonical(timestamps, imports, exports)
    prepared = add_analysis_flags(apply_timestamp_convention(data, "start"), AnalysisSettings())
    metrics = profile_metrics(prepared, AnalysisSettings())
    _, quality = combine_imports([item(data)])

    recommendations = build_recommendations(metrics, quality, AnalysisSettings())
    titles = [recommendation["title"] for recommendation in recommendations]

    assert any("Déplacer" in title for title in titles)
    assert any("stockage" in title.lower() or "batterie" in title.lower() for title in titles)
    assert next(index for index, title in enumerate(titles) if "Déplacer" in title) < next(
        index
        for index, title in enumerate(titles)
        if "stockage" in title.lower() or "batterie" in title.lower()
    )
