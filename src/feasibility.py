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

from common import FIGURES, REPORTS, apply_criteria, candidate_stays, connect, load_protocol, md_table

MIN_EVENTS_PER_VARIABLE = 10   # common rule of thumb for logistic regression


def flow_figure(flow: list[dict], path) -> None:
    fig, ax = plt.subplots(figsize=(7, 1.25 * len(flow)))
    ax.axis("off")
    n = len(flow)
    for i, step in enumerate(flow):
        y = n - 1 - i
        ax.add_patch(plt.Rectangle((0.05, y + 0.15), 0.6, 0.7, fc="#e8eef7", ec="#1f3864", lw=1.2))
        ax.text(0.35, y + 0.6, step["step"], ha="center", va="center", fontsize=9.5, weight="bold")
        ax.text(0.35, y + 0.35, f"{step['stays']} stays · {step['patients']} patients",
                ha="center", va="center", fontsize=9)
        if i > 0:
            ax.annotate("", xy=(0.35, y + 0.85), xytext=(0.35, y + 1.15),
                        arrowprops=dict(arrowstyle="->", color="#1f3864"))
            if step["excluded"]:
                ax.text(0.7, y + 1.0, f"excluded: {step['excluded']}", va="center",
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
        "variable": ["age", "sex", "max_lactate_24h", "max_creatinine_24h", "in_hospital_death", "dod (30-day outcome)"],
        "available": [cohort.age.notna().sum(), cohort.sex.notna().sum(), cohort.max_lactate_24h.notna().sum(),
                      cohort.max_creatinine_24h.notna().sum(), cohort.in_hospital_death.notna().sum(), n],
    })
    completeness["% complete"] = (100 * completeness.available / max(n, 1)).round(1)

    if n == 0 or events == 0:
        verdict = "NOT FEASIBLE - no eligible patients or no outcome events."
    elif epv < MIN_EVENTS_PER_VARIABLE:
        verdict = (f"FEASIBLE WITH LIMITATIONS - {events} events for {n_params} model terms "
                   f"({epv:.1f} events per variable, below the usual {MIN_EVENTS_PER_VARIABLE}). "
                   "Recommend a reduced model (exposure + age), exact/penalised methods, "
                   "or running the study on the full MIMIC-IV database.")
    else:
        verdict = f"FEASIBLE - {events} events support a {n_params}-term model ({epv:.1f} EPV)."

    FIGURES.mkdir(parents=True, exist_ok=True)
    flow_figure(flow, FIGURES / "cohort_flow.png")

    flow_df = pd.DataFrame(flow).rename(columns={"step": "Step", "stays": "ICU stays",
                                                 "patients": "Patients", "excluded": "Excluded at this step"})
    report = f"""# Feasibility check - {protocol['study_id']}

**Study:** {protocol['title']}
**Requested by:** {protocol['principal_investigator']}
**Checked on:** {date.today().isoformat()} · **Source:** MIMIC-IV Clinical Database Demo v2.2

## Verdict

**{verdict}**

## Cohort flow

{md_table(flow_df)}

![Cohort flow](figures/cohort_flow.png)

## Exposure and outcome

| Measure | Value |
|---|---|
| Eligible patients | {n} |
| Lactate > {thr} mmol/L in first 24 h | {high} ({100*high/max(n,1):.0f}%) |
| In-hospital deaths (primary outcome) | {events} ({100*events/max(n,1):.0f}%) |
| Model terms planned (exposure + covariates) | {n_params} |
| Events per variable | {epv:.1f} (rule of thumb: >= {MIN_EVENTS_PER_VARIABLE}) |

## Variable completeness in the eligible cohort

{md_table(completeness)}

## Notes for the researcher

- Lactate is taken from blood-gas results (itemid {protocol['exposure']['lab_itemid']}); values outside
  {protocol['exposure']['plausible_range']} {protocol['exposure']['unit']} are rejected as implausible
  ({int(candidates.n_lactate_rejected.sum())} result(s) rejected across all stays).
- Labs are matched by patient and time window, because results drawn in the ED before admission
  often have no admission ID.
- Only the first ICU stay per patient is used, so each patient appears once.
"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "01_feasibility.md").write_text(report, encoding="utf-8")
    print(f"  feasibility: {n} eligible patients, {events} events, EPV {epv:.1f}")
    return {"n": n, "events": events, "epv": epv}


if __name__ == "__main__":
    run()
