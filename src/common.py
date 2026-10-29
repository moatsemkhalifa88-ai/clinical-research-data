"""Shared helpers: protocol loading, database connection, candidate query."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "mimic_demo.db"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
EXTRACT_DIR = ROOT / "data" / "extract"
RESTRICTED_DIR = ROOT / "data" / "restricted"
DEFAULT_PROTOCOL = ROOT / "protocol" / "lactate_mortality.yaml"


def load_protocol(path: Path = DEFAULT_PROTOCOL) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found - run `python run_pipeline.py load` first")
    return sqlite3.connect(db_path)


def sql_params(protocol: dict) -> dict:
    pop, exp, creat = protocol["population"], protocol["exposure"], protocol["labs"]["creatinine"]
    return {
        "min_age": pop["min_age"],
        "min_los_hours": pop["min_icu_los_hours"],
        "hours_before": pop["lab_window_hours_before_icu"],
        "hours_after": pop["lab_window_hours_after_icu"],
        "lactate_itemid": exp["lab_itemid"],
        "lactate_min": exp["plausible_range"][0],
        "lactate_max": exp["plausible_range"][1],
        "creatinine_itemid": creat["itemid"],
        "creatinine_min": creat["plausible_range"][0],
        "creatinine_max": creat["plausible_range"][1],
    }


def candidate_stays(con: sqlite3.Connection, protocol: dict) -> pd.DataFrame:
    query = (ROOT / "sql" / "candidate_stays.sql").read_text(encoding="utf-8")
    df = pd.read_sql_query(query, con, params=sql_params(protocol))
    for col in ["intime", "outtime", "admittime", "dischtime", "deathtime", "dod"]:
        df[col] = pd.to_datetime(df[col])
    return df


# Sequential inclusion steps, in the order a flow diagram shows them
CRITERIA = [
    ("c_adult", "Age >= {min_age}"),
    ("c_first_stay", "First ICU stay of the patient"),
    ("c_los", "ICU length of stay >= {min_icu_los_hours} h"),
    ("c_lactate_measured", "Lactate measured (-{lab_window_hours_before_icu} h to +{lab_window_hours_after_icu} h)"),
]


def apply_criteria(df: pd.DataFrame, protocol: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Apply inclusion criteria one at a time and record the flow."""
    pop = protocol["population"]
    labels = {"min_age": pop["min_age"], "min_icu_los_hours": pop["min_icu_los_hours"],
              "lab_window_hours_before_icu": pop["lab_window_hours_before_icu"],
              "lab_window_hours_after_icu": pop["lab_window_hours_after_icu"]}
    flow = [{"step": "All ICU stays in the database", "stays": len(df),
             "patients": df.subject_id.nunique(), "excluded": 0}]
    current = df
    for col, label in CRITERIA:
        kept = current[current[col] == 1]
        flow.append({"step": label.format(**labels), "stays": len(kept),
                     "patients": kept.subject_id.nunique(), "excluded": len(current) - len(kept)})
        current = kept
    return current.copy(), flow


def md_table(df: pd.DataFrame) -> str:
    """Markdown table without the tabulate dependency."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)
