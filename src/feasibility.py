"""Step 1 - feasibility check for a research proposal.

Answers the questions a researcher asks before submitting a study:
how many patients meet the criteria, how many outcome events there are,
whether the planned model is supported by that many events, and how
complete the variables are. Writes reports/01_feasibility.md.
"""
from __future__ import annotations

from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import FIGURES, REPORTS, apply_criteria, candidate_stays, connect, he, load_protocol, md_table, rtl

MIN_EVENTS_PER_VARIABLE = 10   # common rule of thumb for logistic regression


def flow_figure(flow: list[dict], path) -> None:
    fig, ax = plt.subplots(figsize=(7, 1.25 * len(flow)))
    ax.axis("off")
    n = len(flow)
    for i, step in enumerate(flow):
        y = n - 1 - i
        ax.add_patch(plt.Rectangle((0.05, y + 0.15), 0.6, 0.7, fc="#e8eef7", ec="#1f3864", lw=1.2))
        ax.text(0.35, y + 0.6, he(step["step"]), ha="center", va="center", fontsize=9.5, weight="bold")
        ax.text(0.35, y + 0.35, he(f"{step['stays']} אשפוזים · {step['patients']} מטופלים"),
                ha="center", va="center", fontsize=9)
        if i > 0:
            ax.annotate("", xy=(0.35, y + 0.85), xytext=(0.35, y + 1.15),
                        arrowprops=dict(arrowstyle="->", color="#1f3864"))
            if step["excluded"]:
                ax.text(0.7, y + 1.0, he(f"הוצאו: {step['excluded']}"), va="center",
                        fontsize=8.5, color="#a33")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, n)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run() -> dict:
    protocol = load_protocol()
    with connect() as con:
        candidates = candidate_stays(con, protocol)
    cohort, flow = apply_criteria(candidates, protocol)

    thr = protocol["exposure"]["high_threshold"]
    n = len(cohort)
    events = int(cohort.in_hospital_death.sum())
    high = int((cohort.max_lactate_24h > thr).sum())
    n_params = 1 + len(protocol["covariates"])          # exposure + covariates
    epv = events / n_params if n_params else float("nan")

    completeness = pd.DataFrame({
        "משתנה": ["age", "sex", "max_lactate_24h", "max_creatinine_24h", "in_hospital_death", "dod (תוצאת 30 יום)"],
        "זמינים": [cohort.age.notna().sum(), cohort.sex.notna().sum(), cohort.max_lactate_24h.notna().sum(),
                   cohort.max_creatinine_24h.notna().sum(), cohort.in_hospital_death.notna().sum(), n],
    })
    completeness["% שלמות"] = (100 * completeness["זמינים"] / max(n, 1)).round(1)

    if n == 0 or events == 0:
        verdict = "לא ישים: אין מטופלים שעומדים בקריטריונים, או שאין אירועי תוצאה."
    elif epv < MIN_EVENTS_PER_VARIABLE:
        verdict = (f"ישים בהסתייגויות: יש רק {events} אירועים ל-{n_params} משתנים במודל, כלומר "
                   f"{epv:.1f} אירועים למשתנה (Events per variable, EPV), הרבה מתחת לסף המקובל של "
                   f"{MIN_EVENTS_PER_VARIABLE}. ההמלצה היא לצמצם את המודל (חשיפה + גיל), להשתמש בשיטה "
                   "מדויקת או ברגרסיה עם ענישה (Firth), או להריץ את המחקר על מאגר MIMIC-IV המלא.")
    else:
        verdict = (f"ישים: {events} אירועים מספיקים למודל עם {n_params} משתנים "
                   f"({epv:.1f} אירועים למשתנה, EPV).")

    FIGURES.mkdir(parents=True, exist_ok=True)
    flow_figure(flow, FIGURES / "cohort_flow.png")

    flow_df = pd.DataFrame(flow).rename(columns={"step": "שלב", "stays": "אשפוזים בטיפול נמרץ (ICU)",
                                                 "patients": "מטופלים", "excluded": "הוצאו בשלב זה"})
    report = f"""# בדיקת היתכנות (Feasibility) - {protocol['study_id']}

**המחקר:** {protocol['title']}
**מבקש הבדיקה:** {protocol['principal_investigator']}
**תאריך הבדיקה:** {date.today().isoformat()} · **מקור הנתונים:** MIMIC-IV Clinical Database Demo v2.2

## המלצה (Verdict)

**{verdict}**

## זרימת הקוהורט (Cohort flow)

{md_table(flow_df)}

![זרימת הקוהורט](figures/cohort_flow.png)

## חשיפה ותוצאה

| מדד | ערך |
|---|---|
| מטופלים שעומדים בקריטריונים | {n} |
| לקטט > {thr} mmol/L ב-24 השעות הראשונות | {high} ({100*high/max(n,1):.0f}%) |
| פטירות במהלך האשפוז (תוצאה ראשית) | {events} ({100*events/max(n,1):.0f}%) |
| משתנים מתוכננים במודל (חשיפה + משתנים מתקננים) | {n_params} |
| אירועים למשתנה (EPV) | {epv:.1f} (כלל אצבע: {MIN_EVENTS_PER_VARIABLE} לפחות) |

## שלמות המשתנים בקוהורט

{md_table(completeness)}

## הערות לחוקר

- ערכי הלקטט נלקחים מבדיקות גזים בדם (itemid {protocol['exposure']['lab_itemid']}). ערכים מחוץ לטווח
  {protocol['exposure']['plausible_range']} {protocol['exposure']['unit']} נפסלים כבלתי סבירים
  (בסך הכול נפסלו {int(candidates.n_lactate_rejected.sum())} תוצאות בכל האשפוזים).
- בדיקות המעבדה מותאמות לפי מטופל וחלון זמן, ולא לפי מספר אשפוז: בדיקות שנלקחו במיון לפני הקבלה
  לאשפוז הן לעיתים קרובות ללא מספר אשפוז, וצירוף לפיו היה משמיט אותן בשקט.
- נכלל רק האשפוז הראשון של כל מטופל בטיפול נמרץ, כך שכל מטופל מופיע פעם אחת והתצפיות בלתי תלויות.
"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "01_feasibility.md").write_text(rtl(report), encoding="utf-8")
    print(f"  feasibility: {n} eligible patients, {events} events, EPV {epv:.1f}")
    return {"n": n, "events": events, "epv": epv}


if __name__ == "__main__":
    run()
