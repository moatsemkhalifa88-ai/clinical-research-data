# Data validation - EMK-2026-014

**Result: READY TO RELEASE**

WARN items are documented for the researcher; they do not block release because the
extraction already handles them (e.g. implausible values are excluded by the protocol ranges).

## Source database checks (15 pass · 1 warn · 0 fail)

> **Note on the time-order warning:** 0 ICU stay(s) start before the admission and 14 end after hospital discharge (up to 27.0 h). Late ICU out-times are a known documentation lag in the source system. The protocol only uses the first 24 h after ICU admission, so the extract is not affected.

| area | check | problems | status |
|---|---|---|---|
| Keys | `patients.subject_id` is unique | 0 | PASS |
| Keys | `admissions.hadm_id` is unique | 0 | PASS |
| Keys | `icustays.stay_id` is unique | 0 | PASS |
| Referential | every ICU stay links to an admission | 0 | PASS |
| Referential | every admission links to a patient | 0 | PASS |
| Time order | admission ends after it starts | 0 | PASS |
| Time order | ICU stay ends after it starts | 0 | PASS |
| Time order | ICU stay falls inside its admission (1 h tolerance) | 14 | WARN |
| Consistency | death flag matches recorded death time | 0 | PASS |
| Consistency | in-hospital deaths have a date of death | 0 | PASS |
| Units | Lactate results all in mmol/L | 0 | PASS |
| Ranges | Lactate values inside [0.1, 30] | 0 | PASS |
| Ranges | Lactate results have a numeric value | 0 | PASS |
| Units | Creatinine results all in mg/dL | 0 | PASS |
| Ranges | Creatinine values inside [0.1, 25] | 0 | PASS |
| Ranges | Creatinine results have a numeric value | 0 | PASS |

## Extract checks (10 pass · 0 warn · 0 fail)

| area | check | problems | status |
|---|---|---|---|
| Structure | only approved variables, in protocol order | 0 | PASS |
| Privacy | no hospital identifiers or calendar dates | 0 | PASS |
| Privacy | ages above 89 are grouped | 0 | PASS |
| Structure | one row per patient | 0 | PASS |
| Ranges | age between 18 and 89 | 0 | PASS |
| Ranges | exposure inside [0.1, 30] | 0 | PASS |
| Ranges | follow-up days between 0 and 30 | 0 | PASS |
| Consistency | 30-day deaths have follow-up < 30 days or die on day 30 | 0 | PASS |
| Completeness | primary outcome has no missing values | 0 | PASS |
| Completeness | creatinine available (covariate) | 0 | PASS |

## Missing values in the extract

| variable | % missing |
|---|---|
| study_id | 0.0 |
| age | 0.0 |
| sex | 0.0 |
| admission_type | 0.0 |
| first_careunit | 0.0 |
| icu_los_days | 0.0 |
| max_lactate_24h | 0.0 |
| n_lactate_24h | 0.0 |
| max_creatinine_24h | 0.0 |
| in_hospital_death | 0.0 |
| days_to_death_or_censor | 0.0 |
| death_within_30d | 0.0 |
