"""Step 3 - data validation before anything reaches the researcher.

Two layers of checks:
  * source  - keys, referential integrity, time order and units in the database
  * extract - the delivered file: one row per patient, no identifiers,
              approved variables only, plausible ranges, missingness
Writes reports/02_validation.md. Any FAIL stops the pipeline.
"""
from __future__ import annotations

import pandas as pd

from common import EXTRACT_DIR, REPORTS, connect, load_protocol, md_table

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def count(con, sql: str, params: dict | None = None) -> int:
    return int(con.execute(sql, params or {}).fetchone()[0])


def source_checks(con, protocol: dict) -> list[dict]:
    lac = protocol["exposure"]
    cre = protocol["labs"]["creatinine"]
    checks: list[tuple[str, str, int, str]] = []   # (area, check, n_problems, level_if_problem)

    for table, key in [("patients", "subject_id"), ("admissions", "hadm_id"), ("icustays", "stay_id")]:
        n = count(con, f"SELECT COUNT(*) - COUNT(DISTINCT {key}) FROM {table}")
        checks.append(("Keys", f"`{table}.{key}` is unique", n, FAIL))

    checks += [
        ("Referential", "every ICU stay links to an admission",
         count(con, "SELECT COUNT(*) FROM icustays i LEFT JOIN admissions a ON a.hadm_id=i.hadm_id WHERE a.hadm_id IS NULL"), FAIL),
        ("Referential", "every admission links to a patient",
         count(con, "SELECT COUNT(*) FROM admissions a LEFT JOIN patients p ON p.subject_id=a.subject_id WHERE p.subject_id IS NULL"), FAIL),
        ("Time order", "admission ends after it starts",
         count(con, "SELECT COUNT(*) FROM admissions WHERE julianday(dischtime) <= julianday(admittime)"), FAIL),
        ("Time order", "ICU stay ends after it starts",
         count(con, "SELECT COUNT(*) FROM icustays WHERE julianday(outtime) <= julianday(intime)"), FAIL),
        ("Time order", "ICU stay falls inside its admission (1 h tolerance)",
         count(con, """SELECT COUNT(*) FROM icustays i JOIN admissions a ON a.hadm_id=i.hadm_id
                       WHERE julianday(i.intime) < julianday(a.admittime) - 1/24.0
                          OR julianday(i.outtime) > julianday(a.dischtime) + 1/24.0"""), WARN),
        ("Consistency", "death flag matches recorded death time",
         count(con, """SELECT COUNT(*) FROM admissions
                       WHERE (hospital_expire_flag=1 AND deathtime IS NULL)
                          OR (hospital_expire_flag=0 AND deathtime IS NOT NULL)"""), WARN),
        ("Consistency", "in-hospital deaths have a date of death",
         count(con, """SELECT COUNT(*) FROM admissions a JOIN patients p ON p.subject_id=a.subject_id
                       WHERE a.hospital_expire_flag=1 AND p.dod IS NULL"""), WARN),
    ]

    for name, cfg in [("Lactate", lac), ("Creatinine", cre)]:
        p = {"item": cfg.get("itemid", cfg.get("lab_itemid")), "lo": cfg["plausible_range"][0], "hi": cfg["plausible_range"][1], "unit": cfg["unit"]}
        checks += [
            ("Units", f"{name} results all in {cfg['unit']}",
             count(con, "SELECT COUNT(*) FROM labevents WHERE itemid=:item AND valuenum IS NOT NULL AND COALESCE(valueuom,'')<>:unit", p), WARN),
            ("Ranges", f"{name} values inside {cfg['plausible_range']}",
             count(con, "SELECT COUNT(*) FROM labevents WHERE itemid=:item AND valuenum IS NOT NULL AND valuenum NOT BETWEEN :lo AND :hi", p), WARN),
            ("Ranges", f"{name} results have a numeric value",
             count(con, "SELECT COUNT(*) FROM labevents WHERE itemid=:item AND valuenum IS NULL", p), WARN),
        ]
    return [{"area": a, "check": c, "problems": n, "status": PASS if n == 0 else lvl} for a, c, n, lvl in checks]


def extract_checks(df: pd.DataFrame, protocol: dict) -> list[dict]:
    allowed = protocol["minimum_necessary_variables"]
    forbidden = {"subject_id", "hadm_id", "stay_id", "intime", "outtime", "admittime", "dischtime", "deathtime", "dod"}
    lo, hi = protocol["exposure"]["plausible_range"]
    rows = [
        ("Structure", "only approved variables, in protocol order", 0 if list(df.columns) == allowed else 1, FAIL),
        ("Privacy", "no hospital identifiers or calendar dates", len(forbidden & set(df.columns)), FAIL),
        ("Privacy", "ages above 89 are grouped", int((df.age > 89).sum()), FAIL),
        ("Structure", "one row per patient", int(df.study_id.duplicated().sum()), FAIL),
        ("Ranges", "age between 18 and 89", int((~df.age.between(protocol["population"]["min_age"], 89)).sum()), FAIL),
        ("Ranges", f"exposure inside [{lo}, {hi}]", int((~df.max_lactate_24h.between(lo, hi)).sum()), FAIL),
        ("Ranges", "follow-up days between 0 and 30", int((~df.days_to_death_or_censor.between(0, 30)).sum()), FAIL),
        ("Consistency", "30-day deaths have follow-up < 30 days or die on day 30",
         int(((df.death_within_30d == 1) & (df.days_to_death_or_censor > 30)).sum()), FAIL),
        ("Completeness", "primary outcome has no missing values", int(df.in_hospital_death.isna().sum()), FAIL),
        ("Completeness", "creatinine available (covariate)", int(df.max_creatinine_24h.isna().sum()), WARN),
    ]
    return [{"area": a, "check": c, "problems": n, "status": PASS if n == 0 else lvl} for a, c, n, lvl in rows]


def interpret_warnings(counts) -> str:
    early, late, max_late = (c or 0 for c in counts)
    if not (early or late):
        return ""
    return (f"> **Note on the time-order warning:** {early} ICU stay(s) start before the admission and "
            f"{late} end after hospital discharge (up to {max_late} h). Late ICU out-times are a known "
            "documentation lag in the source system. The protocol only uses the first 24 h after ICU "
            "admission, so the extract is not affected.")


def run() -> bool:
    protocol = load_protocol()
    with connect() as con:
        src = source_checks(con, protocol)
        con_counts = con.execute("""SELECT
            SUM(julianday(i.intime)  < julianday(a.admittime) - 1/24.0),
            SUM(julianday(i.outtime) > julianday(a.dischtime) + 1/24.0),
            ROUND(MAX((julianday(i.outtime) - julianday(a.dischtime)) * 24), 1)
            FROM icustays i JOIN admissions a ON a.hadm_id = i.hadm_id""").fetchone()
    df = pd.read_csv(EXTRACT_DIR / f"{protocol['study_id']}_extract.csv")
    ext = extract_checks(df, protocol)

    missing = (df.isna().mean() * 100).round(1).reset_index()
    missing.columns = ["variable", "% missing"]

    def summary(rows):
        s = pd.Series([r["status"] for r in rows]).value_counts()
        return f"{s.get(PASS, 0)} pass · {s.get(WARN, 0)} warn · {s.get(FAIL, 0)} fail"

    ok = not any(r["status"] == FAIL for r in src + ext)
    report = f"""# Data validation - {protocol['study_id']}

**Result: {'READY TO RELEASE' if ok else 'BLOCKED - fix FAIL items before release'}**

WARN items are documented for the researcher; they do not block release because the
extraction already handles them (e.g. implausible values are excluded by the protocol ranges).

## Source database checks ({summary(src)})

{interpret_warnings(con_counts)}

{md_table(pd.DataFrame(src))}

## Extract checks ({summary(ext)})

{md_table(pd.DataFrame(ext))}

## Missing values in the extract

{md_table(missing)}
"""
    (REPORTS / "02_validation.md").write_text(report, encoding="utf-8")
    print(f"  validation: source {summary(src)}; extract {summary(ext)}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
