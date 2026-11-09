"""Step 3 - data validation before anything reaches the researcher.

Two layers of checks:
  * source  - keys, referential integrity, time order and units in the database
  * extract - the delivered file: one row per patient, no identifiers,
              approved variables only, plausible ranges, missingness
Writes reports/02_validation.md. Any FAIL stops the pipeline.
"""
from __future__ import annotations

import pandas as pd

from common import EXTRACT_DIR, REPORTS, connect, load_protocol, md_table, rtl

# Status codes stay in English: the Power BI measures filter on them.
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Column headers for the Hebrew report (the dict keys themselves are used by export_bi)
REPORT_COLUMNS = {"area": "תחום", "check": "בדיקה", "problems": "שורות עם בעיה", "status": "תוצאה"}


def count(con, sql: str, params: dict | None = None) -> int:
    return int(con.execute(sql, params or {}).fetchone()[0])


def source_checks(con, protocol: dict) -> list[dict]:
    lac = protocol["exposure"]
    cre = protocol["labs"]["creatinine"]
    checks: list[tuple[str, str, int, str]] = []   # (area, check, n_problems, level_if_problem)

    for table, key in [("patients", "subject_id"), ("admissions", "hadm_id"), ("icustays", "stay_id")]:
        n = count(con, f"SELECT COUNT(*) - COUNT(DISTINCT {key}) FROM {table}")
        checks.append(("מפתחות", f"`{table}.{key}` ייחודי", n, FAIL))

    checks += [
        ("שלמות קישורים", "כל שהייה בטיפול נמרץ מקושרת לאשפוז",
         count(con, "SELECT COUNT(*) FROM icustays i LEFT JOIN admissions a ON a.hadm_id=i.hadm_id WHERE a.hadm_id IS NULL"), FAIL),
        ("שלמות קישורים", "כל אשפוז מקושר למטופל",
         count(con, "SELECT COUNT(*) FROM admissions a LEFT JOIN patients p ON p.subject_id=a.subject_id WHERE p.subject_id IS NULL"), FAIL),
        ("סדר זמנים", "האשפוז מסתיים אחרי שהוא מתחיל",
         count(con, "SELECT COUNT(*) FROM admissions WHERE julianday(dischtime) <= julianday(admittime)"), FAIL),
        ("סדר זמנים", "השהייה בטיפול נמרץ מסתיימת אחרי שהיא מתחילה",
         count(con, "SELECT COUNT(*) FROM icustays WHERE julianday(outtime) <= julianday(intime)"), FAIL),
        ("סדר זמנים", "השהייה בטיפול נמרץ בתוך תקופת האשפוז (סטייה של עד שעה)",
         count(con, """SELECT COUNT(*) FROM icustays i JOIN admissions a ON a.hadm_id=i.hadm_id
                       WHERE julianday(i.intime) < julianday(a.admittime) - 1/24.0
                          OR julianday(i.outtime) > julianday(a.dischtime) + 1/24.0"""), WARN),
        ("עקביות", "דגל הפטירה תואם לזמן הפטירה הרשום",
         count(con, """SELECT COUNT(*) FROM admissions
                       WHERE (hospital_expire_flag=1 AND deathtime IS NULL)
                          OR (hospital_expire_flag=0 AND deathtime IS NOT NULL)"""), WARN),
        ("עקביות", "לכל פטירה באשפוז יש תאריך פטירה",
         count(con, """SELECT COUNT(*) FROM admissions a JOIN patients p ON p.subject_id=a.subject_id
                       WHERE a.hospital_expire_flag=1 AND p.dod IS NULL"""), WARN),
    ]

    for name, cfg in [("לקטט", lac), ("קריאטינין", cre)]:
        p = {"item": cfg.get("itemid", cfg.get("lab_itemid")), "lo": cfg["plausible_range"][0], "hi": cfg["plausible_range"][1], "unit": cfg["unit"]}
        checks += [
            ("יחידות", f"כל תוצאות ה{name} ביחידות {cfg['unit']}",
             count(con, "SELECT COUNT(*) FROM labevents WHERE itemid=:item AND valuenum IS NOT NULL AND COALESCE(valueuom,'')<>:unit", p), WARN),
            ("טווחים", f"ערכי ה{name} בטווח {cfg['plausible_range']}",
             count(con, "SELECT COUNT(*) FROM labevents WHERE itemid=:item AND valuenum IS NOT NULL AND valuenum NOT BETWEEN :lo AND :hi", p), WARN),
            ("טווחים", f"לכל תוצאות ה{name} יש ערך מספרי",
             count(con, "SELECT COUNT(*) FROM labevents WHERE itemid=:item AND valuenum IS NULL", p), WARN),
        ]
    return [{"area": a, "check": c, "problems": n, "status": PASS if n == 0 else lvl} for a, c, n, lvl in checks]


def extract_checks(df: pd.DataFrame, protocol: dict) -> list[dict]:
    allowed = protocol["minimum_necessary_variables"]
    forbidden = {"subject_id", "hadm_id", "stay_id", "intime", "outtime", "admittime", "dischtime", "deathtime", "dod"}
    lo, hi = protocol["exposure"]["plausible_range"]
    rows = [
        ("מבנה", "רק משתנים מאושרים, לפי סדר הפרוטוקול", 0 if list(df.columns) == allowed else 1, FAIL),
        ("פרטיות", "אין מזהי בית חולים ואין תאריכים קלנדריים", len(forbidden & set(df.columns)), FAIL),
        ("פרטיות", "גילאים מעל 89 מקובצים", int((df.age > 89).sum()), FAIL),
        ("מבנה", "שורה אחת לכל מטופל", int(df.study_id.duplicated().sum()), FAIL),
        ("טווחים", "גיל בין 18 ל-89", int((~df.age.between(protocol["population"]["min_age"], 89)).sum()), FAIL),
        ("טווחים", f"החשיפה בטווח [{lo}, {hi}]", int((~df.max_lactate_24h.between(lo, hi)).sum()), FAIL),
        ("טווחים", "ימי מעקב בין 0 ל-30", int((~df.days_to_death_or_censor.between(0, 30)).sum()), FAIL),
        ("עקביות", "לפטירות תוך 30 יום יש מעקב של 30 יום לכל היותר",
         int(((df.death_within_30d == 1) & (df.days_to_death_or_censor > 30)).sum()), FAIL),
        ("שלמות", "אין ערכים חסרים בתוצאה הראשית", int(df.in_hospital_death.isna().sum()), FAIL),
        ("שלמות", "קריאטינין זמין (משתנה מתקנן)", int(df.max_creatinine_24h.isna().sum()), WARN),
    ]
    return [{"area": a, "check": c, "problems": n, "status": PASS if n == 0 else lvl} for a, c, n, lvl in rows]


def interpret_warnings(counts) -> str:
    early, late, max_late = (c or 0 for c in counts)
    if not (early or late):
        return ""
    return (f"> **הערה לגבי האזהרה בסדר הזמנים:** {early} שהיות בטיפול נמרץ (ICU) מתחילות לפני האשפוז, "
            f"ו-{late} מסתיימות אחרי השחרור מבית החולים (עד {max_late} שעות). זמני יציאה מאוחרים מטיפול "
            "נמרץ הם עיכוב תיעוד מוכר במערכת המקור. הפרוטוקול משתמש רק ב-24 השעות הראשונות אחרי הקבלה "
            "לטיפול נמרץ, ולכן הקובץ שנמסר לא מושפע.")


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
    missing.columns = ["משתנה", "% חסרים"]

    def summary(rows, hebrew=False):
        s = pd.Series([r["status"] for r in rows]).value_counts()
        if hebrew:
            return f"{s.get(PASS, 0)} עברו · {s.get(WARN, 0)} אזהרות · {s.get(FAIL, 0)} נכשלו"
        return f"{s.get(PASS, 0)} pass · {s.get(WARN, 0)} warn · {s.get(FAIL, 0)} fail"

    def table(rows):
        return md_table(pd.DataFrame(rows).rename(columns=REPORT_COLUMNS))

    ok = not any(r["status"] == FAIL for r in src + ext)
    result = ("מוכן למסירה (READY TO RELEASE)" if ok
              else "חסום (BLOCKED): יש לתקן את כל הפריטים בסטטוס FAIL לפני המסירה")
    report = f"""# בדיקת תקינות נתונים (Data validation) - {protocol['study_id']}

**תוצאה: {result}**

פריטים בסטטוס WARN (אזהרה) מתועדים לחוקר, אבל לא חוסמים את המסירה, כי שלב החילוץ כבר מטפל בהם
(למשל, ערכים בלתי סבירים מוחרגים לפי הטווחים שבפרוטוקול). כל פריט בסטטוס FAIL (כשל) חוסם את המסירה.

## בדיקות על מאגר המקור ({summary(src, hebrew=True)})

{interpret_warnings(con_counts)}

{table(src)}

## בדיקות על קובץ החילוץ (Extract) ({summary(ext, hebrew=True)})

{table(ext)}

## ערכים חסרים בקובץ החילוץ

{md_table(missing)}
"""
    (REPORTS / "02_validation.md").write_text(rtl(report), encoding="utf-8")
    print(f"  validation: source {summary(src)}; extract {summary(ext)}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
