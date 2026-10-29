"""Step 2 - protocol-driven, de-identified extract for the researcher.

Follows "minimum necessary": only the variables listed in the protocol leave
the database. Patient identifiers are replaced by study IDs, and the key that
links them back is written to data/restricted/ (never sent or committed).
Absolute dates are removed; time is given as days from ICU admission.
"""
from __future__ import annotations

import pandas as pd

from common import EXTRACT_DIR, RESTRICTED_DIR, apply_criteria, candidate_stays, connect, load_protocol

FOLLOW_UP_DAYS = 30
AGE_CAP = 89          # ages above 89 are grouped (HIPAA Safe Harbor)

DICTIONARY = {
    "study_id": ("text", "Study-specific patient ID (no link to hospital IDs in this file)"),
    "age": ("years", f"Age at ICU admission; values above {AGE_CAP} are set to {AGE_CAP}"),
    "sex": ("F/M", "Sex as recorded"),
    "admission_type": ("text", "Hospital admission type (e.g. EW EMER., URGENT, ELECTIVE)"),
    "first_careunit": ("text", "First ICU care unit"),
    "icu_los_days": ("days", "ICU length of stay"),
    "max_lactate_24h": ("mmol/L", "Highest plausible blood lactate from -6 h to +24 h of ICU admission"),
    "n_lactate_24h": ("count", "Number of lactate results in the window"),
    "max_creatinine_24h": ("mg/dL", "Highest plausible serum creatinine in the same window (blank if none)"),
    "in_hospital_death": ("0/1", "Died during the hospital admission (primary outcome)"),
    "days_to_death_or_censor": ("days", f"Days from ICU admission to death, censored at {FOLLOW_UP_DAYS}"),
    "death_within_30d": ("0/1", f"Died within {FOLLOW_UP_DAYS} days of ICU admission (secondary outcome)"),
}


def derive(cohort: pd.DataFrame) -> pd.DataFrame:
    df = cohort.copy()
    days_to_death = (df.dod - df.intime.dt.normalize()).dt.days
    df["death_within_30d"] = (days_to_death.notna() & (days_to_death <= FOLLOW_UP_DAYS)).astype(int)
    df["days_to_death_or_censor"] = days_to_death.where(df.death_within_30d == 1, FOLLOW_UP_DAYS).clip(lower=0)
    df["age"] = df.age.clip(upper=AGE_CAP)
    df["icu_los_days"] = df.icu_los_days.round(2)
    df["in_hospital_death"] = df.in_hospital_death.astype(int)
    return df


def run() -> pd.DataFrame:
    protocol = load_protocol()
    with connect() as con:
        cohort, _ = apply_criteria(candidate_stays(con, protocol), protocol)
    df = derive(cohort).sort_values("intime").reset_index(drop=True)

    # pseudonymise: sequential study IDs; the linkage key stays restricted
    prefix = protocol["study_id"].split("-")[-1]
    df["study_id"] = [f"P{prefix}-{i:04d}" for i in range(1, len(df) + 1)]
    RESTRICTED_DIR.mkdir(parents=True, exist_ok=True)
    df[["study_id", "subject_id", "hadm_id", "stay_id"]].to_csv(
        RESTRICTED_DIR / f"{protocol['study_id']}_linkage_key.csv", index=False)

    # minimum necessary: keep only approved variables, in protocol order
    allowed = protocol["minimum_necessary_variables"]
    extract = df[allowed].sample(frac=1, random_state=14).reset_index(drop=True)  # row order reveals nothing

    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    out = EXTRACT_DIR / f"{protocol['study_id']}_extract.csv"
    extract.to_csv(out, index=False)

    lines = [f"# Data dictionary - {protocol['study_id']}", "",
             f"File: `{out.name}` · {len(extract)} rows (one per patient) · {len(allowed)} variables", "",
             "| Variable | Unit / values | Definition |", "|---|---|---|"]
    lines += [f"| `{v}` | {DICTIONARY[v][0]} | {DICTIONARY[v][1]} |" for v in allowed]
    lines += ["", "Identifiers removed: hospital subject/admission/stay IDs, all calendar dates.",
              "Re-identification key is held by the data team only."]
    (EXTRACT_DIR / f"{protocol['study_id']}_data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  extract: {len(extract)} rows x {len(allowed)} variables -> {out.relative_to(EXTRACT_DIR.parents[1])}")
    return extract


if __name__ == "__main__":
    run()
