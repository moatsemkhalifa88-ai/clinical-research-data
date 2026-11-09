"""Step 4 - analysis on the de-identified extract, the way the researcher would run it.

Reads ONLY the delivered extract (never the database), so the results can be
reproduced by anyone who receives the file.
  * Table 1 by exposure group, with Mann-Whitney / Fisher tests
  * mortality by lactate band with Wilson 95% CIs
  * logistic regression for in-hospital death (ML and Firth)
  * Kaplan-Meier 30-day survival with a log-rank test
Writes reports/03_analysis.md and figures.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from common import EXTRACT_DIR, FIGURES, FIGURES_EN, REPORTS, he, load_protocol, md_table, protocol_text, rtl
from stats_utils import kaplan_meier, logistic, logrank, wilson

NAVY, RED, GREY = "#1f3864", "#c0392b", "#7f8c8d"
# Plain Hebrew; wrap with he() only when the text goes into a matplotlib figure
LABELS = {"high_lactate": "לקטט מעל הסף", "lactate_per_mmol": "לקטט (לכל 1 mmol/L)",
          "age_per_10y": "גיל (לכל 10 שנים)", "female": "מין נקבה"}
METHODS = {"Maximum likelihood": "נראות מרבית", "Firth penalised": "Firth"}

# Figure text per language. Hebrew figures are the default (reports/figures/);
# English copies go to reports/figures/en/ for README.en.md.
FIG_TEXT = {
    "he": {
        "bands_x": "הלקטט הגבוה ביותר ב-24 השעות הראשונות בטיפול נמרץ (mmol/L)",
        "bands_y": "תמותה באשפוז (%)",
        "bands_title": "תמותה באשפוז לפי רמת הלקטט המוקדמת (רווח סמך 95% לפי Wilson)",
        "km_low": "לקטט ≤ {thr} (n={n})", "km_high": "לקטט > {thr} (n={n})",
        "km_x": "ימים מהקבלה לטיפול נמרץ", "km_y": "הישרדות (%)",
        "km_title": "הישרדות 30 יום לפי רמת הלקטט המוקדמת (log-rank p = {p})",
        "forest_x": "יחס סיכויים (OR) לפטירה באשפוז (סקאלה לוגריתמית, רווח סמך 95%)",
        "forest_title": "מודל מתוקנן ({method}) · {n} מטופלים · {events} אירועים",
        "labels": LABELS, "methods": METHODS,
    },
    "en": {
        "bands_x": "Highest lactate in first 24 h of ICU (mmol/L)",
        "bands_y": "In-hospital mortality (%)",
        "bands_title": "In-hospital mortality by early lactate (95% Wilson CI)",
        "km_low": "Lactate <= {thr} (n={n})", "km_high": "Lactate > {thr} (n={n})",
        "km_x": "Days from ICU admission", "km_y": "Survival (%)",
        "km_title": "30-day survival by early lactate (log-rank p = {p})",
        "forest_x": "Odds ratio for in-hospital death (log scale, 95% CI)",
        "forest_title": "Adjusted model ({method}, n={n}, events={events})",
        "labels": {"high_lactate": "Lactate > threshold", "lactate_per_mmol": "Lactate (per 1 mmol/L)",
                   "age_per_10y": "Age (per 10 years)", "female": "Female sex"},
        "methods": {"Maximum likelihood": "Maximum likelihood", "Firth penalised": "Firth penalised"},
    },
}


def figure_paths(name: str) -> dict:
    return {"he": FIGURES / name, "en": FIGURES_EN / name}


def fig_text(lang: str, key: str, **kw) -> str:
    """Figure string in the given language, ready for matplotlib."""
    text = FIG_TEXT[lang][key].format(**kw)
    return he(text) if lang == "he" else text


def fmt_median(s: pd.Series) -> str:
    s = s.dropna()
    return f"{s.median():.1f} [{s.quantile(.25):.1f}-{s.quantile(.75):.1f}]" if len(s) else "-"


def fmt_pct(s: pd.Series) -> str:
    return f"{int(s.sum())} ({100*s.mean():.0f}%)"


def fmt_p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def table_one(df: pd.DataFrame, thr: float) -> pd.DataFrame:
    g = df.high_lactate
    lo, hi = df[g == 0], df[g == 1]
    rows = []

    def cont(label, col):
        p = stats.mannwhitneyu(lo[col].dropna(), hi[col].dropna()).pvalue if lo[col].notna().any() and hi[col].notna().any() else np.nan
        rows.append([label, fmt_median(df[col]), fmt_median(lo[col]), fmt_median(hi[col]), fmt_p(p)])

    def binary(label, mask):
        tab = [[int(mask[g == 0].sum()), int((~mask[g == 0]).sum())], [int(mask[g == 1].sum()), int((~mask[g == 1]).sum())]]
        p = stats.fisher_exact(tab).pvalue
        rows.append([label, fmt_pct(mask), fmt_pct(mask[g == 0]), fmt_pct(mask[g == 1]), fmt_p(p)])

    rows.append(["מטופלים, n", str(len(df)), str(len(lo)), str(len(hi)), ""])
    cont("גיל, חציון [טווח בין-רבעוני, IQR]", "age")
    binary("נשים, n (%)", df.sex.eq("F"))
    binary("קבלה דחופה (Emergency), n (%)", df.admission_type.str.contains("EMER", na=False))
    cont("לקטט מרבי ב-24 שעות, mmol/L", "max_lactate_24h")
    cont("קריאטינין מרבי ב-24 שעות, mg/dL", "max_creatinine_24h")
    cont("משך שהייה בטיפול נמרץ (ICU), ימים", "icu_los_days")
    binary("פטירה באשפוז, n (%)", df.in_hospital_death.eq(1))
    binary("פטירה תוך 30 יום, n (%)", df.death_within_30d.eq(1))
    return pd.DataFrame(rows, columns=["מאפיין", "כלל המטופלים", f"לקטט ≤ {thr}", f"לקטט > {thr}", "p"])


BAND_COL = "טווח לקטט (mmol/L)"


def fig_lactate_bands(df: pd.DataFrame, paths: dict) -> pd.DataFrame:
    bands = pd.cut(df.max_lactate_24h, [0, 2, 4, np.inf], labels=["≤ 2", "2-4", "> 4"])
    rows = []
    for band in bands.cat.categories:
        sub = df[bands == band]
        k, n = int(sub.in_hospital_death.sum()), len(sub)
        lo, hi = wilson(k, n)
        rows.append({BAND_COL: band, "מטופלים": n, "פטירות": k,
                     "תמותה": f"{100*k/n:.0f}%" if n else "-",
                     "רווח סמך 95%": f"{100*lo:.0f}-{100*hi:.0f}%" if n else "-", "_p": k / n if n else np.nan,
                     "_lo": lo, "_hi": hi, "_n": n})
    t = pd.DataFrame(rows)
    x = np.arange(len(t))
    for lang, path in paths.items():
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(x, 100 * t._p, color=[NAVY, "#e67e22", RED], width=0.6)
        ax.errorbar(x, 100 * t._p, yerr=[100 * (t._p - t._lo), 100 * (t._hi - t._p)], fmt="none", ecolor="black", capsize=5, lw=1)
        for i, r in t.iterrows():
            ax.text(i, 2, f"n={r._n}", ha="center", color="white", fontsize=9, weight="bold")
        ax.set_xticks(x, t[BAND_COL])
        ax.set_xlabel(fig_text(lang, "bands_x"))
        ax.set_ylabel(fig_text(lang, "bands_y"))
        ax.set_title(fig_text(lang, "bands_title"))
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    return t[[c for c in t.columns if not c.startswith("_")]]


def fig_km(df: pd.DataFrame, thr: float, paths: dict) -> tuple[float, float]:
    chi2, p = logrank(df.days_to_death_or_censor, df.death_within_30d, df.high_lactate)
    for lang, path in paths.items():
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        for grp, colour, key in [(0, NAVY, "km_low"), (1, RED, "km_high")]:
            sub = df[df.high_lactate == grp]
            km = kaplan_meier(sub.days_to_death_or_censor, sub.death_within_30d)
            km = pd.concat([km, pd.DataFrame([{**km.iloc[-1].to_dict(), "time": 30.0}])])
            ax.step(km.time, 100 * km.survival, where="post", color=colour, lw=2,
                    label=fig_text(lang, key, thr=thr, n=len(sub)))
            ax.fill_between(km.time, 100 * km.ci_low, 100 * km.ci_high, step="post", color=colour, alpha=0.12)
        ax.set_xlim(0, 30); ax.set_ylim(0, 102)
        ax.set_xlabel(fig_text(lang, "km_x")); ax.set_ylabel(fig_text(lang, "km_y"))
        ax.set_title(fig_text(lang, "km_title", p=fmt_p(p)))
        ax.legend(loc="lower left", frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    return chi2, p


def fig_forest(res, paths: dict) -> None:
    t = res.table[res.table.term != "(intercept)"].iloc[::-1]
    y = np.arange(len(t))
    for lang, path in paths.items():
        txt = FIG_TEXT[lang]
        fig, ax = plt.subplots(figsize=(6.5, 0.6 * len(t) + 1.2))
        ax.errorbar(t.OR, y, xerr=[t.OR - t["CI low"], t["CI high"] - t.OR], fmt="o", color=NAVY, capsize=4)
        ax.axvline(1, color=GREY, ls="--", lw=1)
        ticks = [txt["labels"][term] for term in t.term]
        ax.set_xscale("log"); ax.set_yticks(y, [he(s) for s in ticks] if lang == "he" else ticks)
        ax.set_xlabel(fig_text(lang, "forest_x"))
        ax.set_title(fig_text(lang, "forest_title", method=txt["methods"][res.method], n=res.n, events=res.events),
                     fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def or_table(res) -> pd.DataFrame:
    t = res.table[res.table.term != "(intercept)"].copy()
    return pd.DataFrame({"משתנה": t.term.map(LABELS), "יחס סיכויים (OR)": t.OR.map("{:.2f}".format),
                         "רווח סמך 95%": [f"{a:.2f}-{b:.2f}" for a, b in zip(t["CI low"], t["CI high"])],
                         "p": t.p.map(fmt_p)})


def run() -> dict:
    protocol = load_protocol()
    thr = protocol["exposure"]["high_threshold"]
    df = pd.read_csv(EXTRACT_DIR / f"{protocol['study_id']}_extract.csv")
    df["high_lactate"] = (df.max_lactate_24h > thr).astype(int)
    df["female"] = df.sex.eq("F").astype(int)
    df["age_per_10y"] = df.age / 10
    df["lactate_per_mmol"] = df.max_lactate_24h
    FIGURES_EN.mkdir(parents=True, exist_ok=True)

    t1 = table_one(df, thr)
    bands = fig_lactate_bands(df, figure_paths("mortality_by_lactate.png"))
    chi2, p_lr = fig_km(df, thr, figure_paths("km_30day.png"))

    unadj = logistic(df, "in_hospital_death", ["high_lactate"])
    full_terms = ["high_lactate", "age_per_10y", "female"]
    adj_ml = logistic(df, "in_hospital_death", full_terms)
    adj_firth = logistic(df, "in_hospital_death", full_terms, firth=True)
    cont_firth = logistic(df, "in_hospital_death", ["lactate_per_mmol", "age_per_10y", "female"], firth=True)
    fig_forest(adj_firth, figure_paths("forest_adjusted.png"))

    events = int(df.in_hospital_death.sum())
    or_main = adj_firth.table.set_index("term").loc["high_lactate"]
    or_cont = cont_firth.table.set_index("term").loc["lactate_per_mmol"]

    significance = "מובהק סטטיסטית ברמה של 0.05" if p_lr < 0.05 else "לא מובהק סטטיסטית ברמה של 0.05"
    report = f"""# ניתוח סטטיסטי (Analysis) - {protocol['study_id']}

**שאלת המחקר:** {protocol_text(protocol, 'question')}

**נתונים:** קובץ חילוץ לאחר הסרת מזהים (De-identified extract) `{protocol['study_id']}_extract.csv`
({len(df)} מטופלים, {events} פטירות באשפוז).

## ממצאים עיקריים

- למטופלים עם לקטט > {thr} mmol/L היה יחס סיכויים (Odds ratio, OR) מתוקנן לפטירה באשפוז של
  **{or_main.OR:.2f} (רווח סמך 95% (95% CI) {or_main['CI low']:.2f}-{or_main['CI high']:.2f}, p = {fmt_p(or_main.p)})**
  (רגרסיה לוגיסטית (Logistic regression) לפי Firth, מתוקננת לגיל ולמין).
- כל עלייה של 1 mmol/L בלקטט: OR של **{or_cont.OR:.2f} ({or_cont['CI low']:.2f}-{or_cont['CI high']:.2f}, p = {fmt_p(or_cont.p)})**.
- הישרדות 30 יום לפי קבוצה: מבחן log-rank, chi-square = {chi2:.2f}, p = {fmt_p(p_lr)} ({significance}).
- עם {events} אירועים בלבד האומדנים לא מדויקים, ורווחי הסמך רחבים. זו הדגמה על מאגר הדמו של
  100 מטופלים; אותו פייפליין רץ בלי שינוי על מאגר MIMIC-IV המלא.

## טבלה 1 (Table 1) - מאפייני המטופלים לפי רמת הלקטט המוקדמת

{md_table(t1)}

משתנים רציפים: חציון [IQR], מבחן Mann-Whitney U. משתנים קטגוריאליים: n (%), המבחן המדויק של Fisher.

## תמותה לפי טווח לקטט

{md_table(bands)}

![תמותה לפי טווח לקטט](figures/mortality_by_lactate.png)

## רגרסיה לוגיסטית - פטירה באשפוז

**ללא תקנון** ({METHODS[unadj.method]}):

{md_table(or_table(unadj))}

**מתוקנן, נראות מרבית (Maximum likelihood):**

{md_table(or_table(adj_ml))}

**מתוקנן, נראות מרבית עם ענישה לפי Firth (Firth penalised likelihood)** (השיטה המועדפת כשיש מעט אירועים):

{md_table(or_table(adj_firth))}

**לקטט כמשתנה רציף** (Firth):

{md_table(or_table(cont_firth))}

![תרשים יער (Forest plot)](figures/forest_adjusted.png)

## הישרדות 30 יום

![עקומות הישרדות Kaplan-Meier](figures/km_30day.png)

## מגבלות

- מדגם קטן ({len(df)} מטופלים, {events} אירועים): עוצמה סטטיסטית נמוכה ורווחי סמך רחבים.
- קריאטינין תוכנן כמשתנה מתקנן, אבל לא נכלל במודל הראשי כדי לשמור על יחס סביר של אירועים
  למשתנה (ראו את דוח בדיקת ההיתכנות).
- נתונים תצפיתיים: לקטט נמדד כשהצוות הקליני חושד בבעיה, ולכן עצם ההחלטה למדוד קשורה לחומרת
  המצב (הטיית הוריה, Confounding by indication).
"""
    (REPORTS / "03_analysis.md").write_text(rtl(report), encoding="utf-8")
    print(f"  analysis: adjusted OR {or_main.OR:.2f} ({or_main['CI low']:.2f}-{or_main['CI high']:.2f}), log-rank p {fmt_p(p_lr)}")
    return {"or": or_main.OR, "p_logrank": p_lr}


if __name__ == "__main__":
    run()
