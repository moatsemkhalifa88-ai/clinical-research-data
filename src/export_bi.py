"""Step 5 - export a small star schema for the Power BI dashboard.

Power BI should not re-implement the business rules, so every band and label
is decided here, once, and the dashboard only aggregates. Outputs (bi/data/):

  fact_patient.csv       one row per study patient (from the de-identified extract)
  dim_lactate_band.csv   lactate bands with sort order and clinical meaning
  dim_age_band.csv       age bands with sort order
  dim_care_unit.csv      ICU care units, full and short name
  cohort_flow.csv        inclusion steps (feasibility) for the funnel
  validation_checks.csv  every validation check and its result (data-quality page)

Only the de-identified extract and aggregate counts leave the data desk;
the dashboard never touches hospital identifiers or dates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import EXTRACT_DIR, ROOT, apply_criteria, candidate_stays, connect, load_protocol
from validate import extract_checks, source_checks

BI_DIR = ROOT / "bi" / "data"
ENC = "utf-8-sig"  # BOM so Power BI reads the ≤ and – signs correctly

LACTATE_BANDS = [  # (upper bound, label, meaning)
    (2.0, "≤ 2", "Normal"),
    (4.0, "2–4", "Raised"),
    (np.inf, "> 4", "Severe"),
]
AGE_BANDS = [(39, "18–39"), (59, "40–59"), (74, "60–74"), (200, "75+")]
ADMISSION_GROUPS = {
    "EW EMER.": "Emergency", "DIRECT EMER.": "Emergency", "URGENT": "Urgent",
    "ELECTIVE": "Elective", "SURGICAL SAME DAY ADMISSION": "Elective", "OBSERVATION ADMIT": "Observation",
}


def _band(value: float, bands: list[tuple]) -> str:
    for upper, label, *_ in bands:
        if value <= upper:
            return label
    raise ValueError(value)


def _short_unit(name: str) -> str:
    # "Surgical Intensive Care Unit (SICU)" -> "SICU"
    return name[name.rfind("(") + 1:-1] if name.endswith(")") else name


def run() -> None:
    protocol = load_protocol()
    thr = protocol["exposure"]["high_threshold"]
    BI_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(EXTRACT_DIR / f"{protocol['study_id']}_extract.csv")
    fact = pd.DataFrame({
        "study_id": df.study_id,
        "age": df.age,
        "age_band": df.age.map(lambda a: _band(a, AGE_BANDS)),
        "sex": df.sex.map({"F": "Female", "M": "Male"}),
        "admission_group": df.admission_type.map(ADMISSION_GROUPS).fillna("Other"),
        "care_unit": df.first_careunit.map(_short_unit),
        "icu_los_days": df.icu_los_days,
        "max_lactate_24h": df.max_lactate_24h,
        "lactate_band": df.max_lactate_24h.map(lambda v: _band(v, LACTATE_BANDS)),
        "high_lactate": (df.max_lactate_24h > thr).astype(int),
        "n_lactate_24h": df.n_lactate_24h,
        "max_creatinine_24h": df.max_creatinine_24h,
        "in_hospital_death": df.in_hospital_death,
        "death_within_30d": df.death_within_30d,
        "days_to_death_or_censor": df.days_to_death_or_censor,
    })
    fact.to_csv(BI_DIR / "fact_patient.csv", index=False, encoding=ENC)

    lower = [0.0] + [b[0] for b in LACTATE_BANDS[:-1]]
    pd.DataFrame({
        "lactate_band": [b[1] for b in LACTATE_BANDS],
        "sort_order": range(1, len(LACTATE_BANDS) + 1),
        "meaning": [b[2] for b in LACTATE_BANDS],
        "range_mmol_l": [f"{lo:g}–{hi:g}" if np.isfinite(hi) else f"> {lo:g}" for lo, (hi, *_) in zip(lower, LACTATE_BANDS)],
    }).to_csv(BI_DIR / "dim_lactate_band.csv", index=False, encoding=ENC)

    pd.DataFrame({"age_band": [b[1] for b in AGE_BANDS], "sort_order": range(1, len(AGE_BANDS) + 1)}
                 ).to_csv(BI_DIR / "dim_age_band.csv", index=False, encoding=ENC)

    units = sorted(df.first_careunit.unique())
    pd.DataFrame({"care_unit": [_short_unit(u) for u in units], "care_unit_name": units}
                 ).to_csv(BI_DIR / "dim_care_unit.csv", index=False, encoding=ENC)

    with connect() as con:
        _, flow = apply_criteria(candidate_stays(con, protocol), protocol)
        src = source_checks(con, protocol)
    pd.DataFrame([{"step_order": i, "step": f["step"], "icu_stays": f["stays"],
                   "patients": f["patients"], "excluded": f["excluded"]} for i, f in enumerate(flow, 1)]
                 ).to_csv(BI_DIR / "cohort_flow.csv", index=False, encoding=ENC)

    checks = ([{"layer": "Source database", **c} for c in src] +
              [{"layer": "Delivered extract", **c} for c in extract_checks(df, protocol)])
    pd.DataFrame(checks).rename(columns={"check": "check_name"}).assign(check_name=lambda d: d.check_name.str.replace("`", "")).to_csv(BI_DIR / "validation_checks.csv", index=False, encoding=ENC)

    print(f"  bi export: {len(fact)} patients, {len(flow)} flow steps, {len(checks)} checks -> bi/data/")


if __name__ == "__main__":
    run()
