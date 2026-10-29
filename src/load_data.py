"""Step 0 - load the MIMIC-IV demo ZIP into a local SQLite research database.

Reads the tables straight from the ZIP (no unzipping), keeps them as-is and
adds indexes on the join keys. SQLite ships with Python, so there is nothing
to install or administer.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "mimic_demo.db"

# (module, table) pairs needed by the protocol
TABLES = [
    ("hosp", "patients"),
    ("hosp", "admissions"),
    ("hosp", "d_labitems"),
    ("hosp", "labevents"),
    ("hosp", "diagnoses_icd"),
    ("icu", "icustays"),
]

INDEXES = {
    "patients": ["subject_id"],
    "admissions": ["subject_id", "hadm_id"],
    "icustays": ["subject_id", "hadm_id", "stay_id"],
    "labevents": ["subject_id", "itemid"],
    "diagnoses_icd": ["hadm_id"],
}

LABEVENT_COLS = ["labevent_id", "subject_id", "hadm_id", "itemid", "charttime",
                 "value", "valuenum", "valueuom", "ref_range_lower", "ref_range_upper", "flag"]


def find_zip() -> Path:
    zips = sorted(RAW_DIR.glob("*.zip"))
    if not zips:
        raise FileNotFoundError(
            f"No ZIP in {RAW_DIR}. Download the MIMIC-IV Clinical Database Demo from "
            "https://physionet.org/content/mimic-iv-demo/2.2/ and put the ZIP there.")
    return zips[-1]


def member_for(zf: zipfile.ZipFile, module: str, table: str) -> str:
    for name in zf.namelist():
        parts = name.replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[-2] == module and parts[-1] in (f"{table}.csv.gz", f"{table}.csv"):
            return name
    raise KeyError(f"{module}/{table} not found in ZIP")


def load(db_path: Path = DB_PATH) -> Path:
    zip_path = find_zip()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    with zipfile.ZipFile(zip_path) as zf:
        for module, table in TABLES:
            name = member_for(zf, module, table)
            with zf.open(name) as fh:
                compression = "gzip" if name.endswith(".gz") else None
                usecols = LABEVENT_COLS if table == "labevents" else None
                df = pd.read_csv(fh, compression=compression, usecols=usecols, low_memory=False)
            df.to_sql(table, con, index=False)
            print(f"  loaded {module}/{table:<14} {len(df):>8,} rows")
    for table, cols in INDEXES.items():
        for col in cols:
            con.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{col} ON {table}({col})")
    con.commit()
    con.close()
    return db_path


if __name__ == "__main__":
    print(f"Database written to {load()}")
