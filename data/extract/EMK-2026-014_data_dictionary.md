# Data dictionary - EMK-2026-014

File: `EMK-2026-014_extract.csv` · 67 rows (one per patient) · 12 variables

| Variable | Unit / values | Definition |
|---|---|---|
| `study_id` | text | Study-specific patient ID (no link to hospital IDs in this file) |
| `age` | years | Age at ICU admission; values above 89 are set to 89 |
| `sex` | F/M | Sex as recorded |
| `admission_type` | text | Hospital admission type (e.g. EW EMER., URGENT, ELECTIVE) |
| `first_careunit` | text | First ICU care unit |
| `icu_los_days` | days | ICU length of stay |
| `max_lactate_24h` | mmol/L | Highest plausible blood lactate from -6 h to +24 h of ICU admission |
| `n_lactate_24h` | count | Number of lactate results in the window |
| `max_creatinine_24h` | mg/dL | Highest plausible serum creatinine in the same window (blank if none) |
| `in_hospital_death` | 0/1 | Died during the hospital admission (primary outcome) |
| `days_to_death_or_censor` | days | Days from ICU admission to death, censored at 30 |
| `death_within_30d` | 0/1 | Died within 30 days of ICU admission (secondary outcome) |

Identifiers removed: hospital subject/admission/stay IDs, all calendar dates.
Re-identification key is held by the data team only.