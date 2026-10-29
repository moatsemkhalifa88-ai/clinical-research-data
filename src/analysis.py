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

from common import EXTRACT_DIR, FIGURES, REPORTS, load_protocol, md_table
from stats_utils import kaplan_meier, logistic, logrank, wilson

NAVY, RED, GREY = "#1f3864", "#c0392b", "#7f8c8d"
LABELS = {"high_lactate": "Lactate > threshold", "lactate_per_mmol": "Lactate (per 1 mmol/L)",
          "age_per_10y": "Age (per 10 years)", "female": "Female sex"}


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

    rows.append(["Patients, n", str(len(df)), str(len(lo)), str(len(hi)), ""])
    cont("Age, median [IQR]", "age")
    binary("Female, n (%)", df.sex.eq("F"))
    binary("Emergency admission, n (%)", df.admission_type.str.contains("EMER", na=False))
    cont("Max lactate 24 h, mmol/L", "max_lactate_24h")
    cont("Max creatinine 24 h, mg/dL", "max_creatinine_24h")
    cont("ICU length of stay, days", "icu_los_days")
    binary("In-hospital death, n (%)", df.in_hospital_death.eq(1))
    binary("Death within 30 days, n (%)", df.death_within_30d.eq(1))
    return pd.DataFrame(rows, columns=["Characteristic", "All", f"Lactate <= {thr}", f"Lactate > {thr}", "p"])


def fig_lactate_bands(df: pd.DataFrame, path) -> pd.DataFrame:
    bands = pd.cut(df.max_lactate_24h, [0, 2, 4, np.inf], labels=["<= 2", "2-4", "> 4"])
    rows = []
    for band in bands.cat.categories:
        sub = df[bands == band]
        k, n = int(sub.in_hospital_death.sum()), len(sub)
        lo, hi = wilson(k, n)
        rows.append({"Lactate band (mmol/L)": band, "Patients": n, "Deaths": k,
                     "Mortality": f"{100*k/n:.0f}%" if n else "-",
                     "95% CI": f"{100*lo:.0f}-{100*hi:.0f}%" if n else "-", "_p": k / n if n else np.nan,
                     "_lo": lo, "_hi": hi})
    t = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(len(t))
    ax.bar(x, 100 * t._p, color=[NAVY, "#e67e22", RED], width=0.6)
    ax.errorbar(x, 100 * t._p, yerr=[100 * (t._p - t._lo), 100 * (t._hi - t._p)], fmt="none", ecolor="black", capsize=5, lw=1)
    for i, r in t.iterrows():
        ax.text(i, 2, f"n={r.Patients}", ha="center", color="white", fontsize=9, weight="bold")
    ax.set_xticks(x, t["Lactate band (mmol/L)"])
    ax.set_xlabel("Highest lactate in first 24 h of ICU (mmol/L)")
    ax.set_ylabel("In-hospital mortality (%)")
    ax.set_title("In-hospital mortality by early lactate (95% Wilson CI)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    return t[[c for c in t.columns if not c.startswith("_")]]


def fig_km(df: pd.DataFrame, thr: float, path) -> tuple[float, float]:
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for grp, colour, label in [(0, NAVY, f"Lactate <= {thr}"), (1, RED, f"Lactate > {thr}")]:
        sub = df[df.high_lactate == grp]
        km = kaplan_meier(sub.days_to_death_or_censor, sub.death_within_30d)
        km = pd.concat([km, pd.DataFrame([{**km.iloc[-1].to_dict(), "time": 30.0}])])
        ax.step(km.time, 100 * km.survival, where="post", color=colour, lw=2, label=f"{label} (n={len(sub)})")
        ax.fill_between(km.time, 100 * km.ci_low, 100 * km.ci_high, step="post", color=colour, alpha=0.12)
    chi2, p = logrank(df.days_to_death_or_censor, df.death_within_30d, df.high_lactate)
    ax.set_xlim(0, 30); ax.set_ylim(0, 102)
    ax.set_xlabel("Days from ICU admission"); ax.set_ylabel("Survival (%)")
    ax.set_title(f"30-day survival by early lactate (log-rank p = {fmt_p(p)})")
    ax.legend(loc="lower left", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    return chi2, p


def fig_forest(res, path) -> None:
    t = res.table[res.table.term != "(intercept)"].iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.5, 0.6 * len(t) + 1.2))
    y = np.arange(len(t))
    ax.errorbar(t.OR, y, xerr=[t.OR - t["CI low"], t["CI high"] - t.OR], fmt="o", color=NAVY, capsize=4)
    ax.axvline(1, color=GREY, ls="--", lw=1)
    ax.set_xscale("log"); ax.set_yticks(y, t.term.map(LABELS))
    ax.set_xlabel("Odds ratio for in-hospital death (log scale, 95% CI)")
    ax.set_title(f"Adjusted model ({res.method}, n={res.n}, events={res.events})", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def or_table(res) -> pd.DataFrame:
    t = res.table[res.table.term != "(intercept)"].copy()
    return pd.DataFrame({"Term": t.term.map(LABELS), "Odds ratio": t.OR.map("{:.2f}".format),
                         "95% CI": [f"{a:.2f}-{b:.2f}" for a, b in zip(t["CI low"], t["CI high"])],
                         "p": t.p.map(fmt_p)})


def run() -> dict:
    protocol = load_protocol()
    thr = protocol["exposure"]["high_threshold"]
    df = pd.read_csv(EXTRACT_DIR / f"{protocol['study_id']}_extract.csv")
    df["high_lactate"] = (df.max_lactate_24h > thr).astype(int)
    df["female"] = df.sex.eq("F").astype(int)
    df["age_per_10y"] = df.age / 10
    df["lactate_per_mmol"] = df.max_lactate_24h
    FIGURES.mkdir(parents=True, exist_ok=True)

    t1 = table_one(df, thr)
    bands = fig_lactate_bands(df, FIGURES / "mortality_by_lactate.png")
    chi2, p_lr = fig_km(df, thr, FIGURES / "km_30day.png")

    unadj = logistic(df, "in_hospital_death", ["high_lactate"])
    full_terms = ["high_lactate", "age_per_10y", "female"]
    adj_ml = logistic(df, "in_hospital_death", full_terms)
    adj_firth = logistic(df, "in_hospital_death", full_terms, firth=True)
    cont_firth = logistic(df, "in_hospital_death", ["lactate_per_mmol", "age_per_10y", "female"], firth=True)
    fig_forest(adj_firth, FIGURES / "forest_adjusted.png")

    events = int(df.in_hospital_death.sum())
    or_main = adj_firth.table.set_index("term").loc["high_lactate"]
    or_cont = cont_firth.table.set_index("term").loc["lactate_per_mmol"]

    report = f"""# Analysis - {protocol['study_id']}

**Question:** {protocol['question'].strip()}

**Data:** de-identified extract `{protocol['study_id']}_extract.csv` ({len(df)} patients, {events} in-hospital deaths).

## Key findings

- Patients with lactate > {thr} mmol/L had an adjusted odds ratio for in-hospital death of
  **{or_main.OR:.2f} (95% CI {or_main['CI low']:.2f}-{or_main['CI high']:.2f}, p = {fmt_p(or_main.p)})**
  (Firth logistic regression, adjusted for age and sex).
- Each additional 1 mmol/L of lactate: OR **{or_cont.OR:.2f} ({or_cont['CI low']:.2f}-{or_cont['CI high']:.2f}, p = {fmt_p(or_cont.p)})**.
- 30-day survival by group: log-rank chi-square = {chi2:.2f}, p = {fmt_p(p_lr)}{' (statistically significant at 0.05)' if p_lr < 0.05 else ' (not statistically significant at 0.05)'}.
- With {events} events the estimates are imprecise (wide CIs). This is a demonstration on the
  100-patient demo database; the same pipeline runs unchanged on the full MIMIC-IV database.

## Table 1 - characteristics by early lactate

{md_table(t1)}

Continuous variables: median [IQR], Mann-Whitney U test. Categorical: n (%), Fisher's exact test.

## Mortality by lactate band

{md_table(bands)}

![Mortality by lactate band](figures/mortality_by_lactate.png)

## Logistic regression - in-hospital death

**Unadjusted** ({unadj.method}):

{md_table(or_table(unadj))}

**Adjusted, maximum likelihood:**

{md_table(or_table(adj_ml))}

**Adjusted, Firth penalised likelihood** (preferred with few events):

{md_table(or_table(adj_firth))}

**Lactate as a continuous variable** (Firth):

{md_table(or_table(cont_firth))}

![Forest plot](figures/forest_adjusted.png)

## 30-day survival

![Kaplan-Meier curves](figures/km_30day.png)

## Limitations

- Small sample ({len(df)} patients, {events} events): low power and wide confidence intervals.
- Creatinine was planned as a covariate but is left out of the main model to keep the
  events-per-variable ratio reasonable (see the feasibility report).
- Observational data: lactate is measured when clinicians suspect a problem, so who gets
  tested is itself related to severity (confounding by indication).
"""
    (REPORTS / "03_analysis.md").write_text(report, encoding="utf-8")
    print(f"  analysis: adjusted OR {or_main.OR:.2f} ({or_main['CI low']:.2f}-{or_main['CI high']:.2f}), log-rank p {fmt_p(p_lr)}")
    return {"or": or_main.OR, "p_logrank": p_lr}


if __name__ == "__main__":
    run()
