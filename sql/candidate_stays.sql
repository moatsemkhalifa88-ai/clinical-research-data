-- ------------------------------------------------------------------
-- Candidate ICU stays with one flag per protocol criterion.
-- Parameters (:name) come from the protocol YAML, never hard-coded.
-- Used by both the feasibility check and the extraction step.
-- ------------------------------------------------------------------
WITH stays AS (
    SELECT
        i.subject_id,
        i.hadm_id,
        i.stay_id,
        i.intime,
        i.outtime,
        i.first_careunit,
        i.los                                                     AS icu_los_days,
        p.gender                                                  AS sex,
        -- MIMIC shifts dates; age at the stay = anchor_age + years since anchor_year
        p.anchor_age + (CAST(strftime('%Y', i.intime) AS INTEGER) - p.anchor_year) AS age,
        p.dod,
        a.admittime,
        a.dischtime,
        a.deathtime,
        a.admission_type,
        a.hospital_expire_flag                                   AS in_hospital_death,
        ROW_NUMBER() OVER (PARTITION BY i.subject_id ORDER BY i.intime) AS icu_stay_seq
    FROM icustays   i
    JOIN patients   p ON p.subject_id = i.subject_id
    JOIN admissions a ON a.hadm_id    = i.hadm_id
),
labs_window AS (
    -- Labs are matched on subject + time window, not hadm_id:
    -- ED / pre-admission draws often have an empty hadm_id.
    SELECT
        s.stay_id,
        l.itemid,
        l.valuenum
    FROM stays s
    JOIN labevents l
      ON l.subject_id = s.subject_id
     AND l.itemid IN (:lactate_itemid, :creatinine_itemid)
     AND julianday(l.charttime) >= julianday(s.intime) - :hours_before / 24.0
     AND julianday(l.charttime) <= julianday(s.intime) + :hours_after  / 24.0
),
labs AS (
    SELECT
        stay_id,
        MAX(CASE WHEN itemid = :lactate_itemid
                  AND valuenum BETWEEN :lactate_min AND :lactate_max THEN valuenum END)       AS max_lactate_24h,
        SUM(CASE WHEN itemid = :lactate_itemid
                  AND valuenum BETWEEN :lactate_min AND :lactate_max THEN 1 ELSE 0 END)       AS n_lactate_24h,
        SUM(CASE WHEN itemid = :lactate_itemid
                  AND (valuenum IS NULL
                       OR valuenum NOT BETWEEN :lactate_min AND :lactate_max) THEN 1 ELSE 0 END) AS n_lactate_rejected,
        MAX(CASE WHEN itemid = :creatinine_itemid
                  AND valuenum BETWEEN :creatinine_min AND :creatinine_max THEN valuenum END) AS max_creatinine_24h
    FROM labs_window
    GROUP BY stay_id
)
SELECT
    s.*,
    COALESCE(l.n_lactate_24h, 0)        AS n_lactate_24h,
    COALESCE(l.n_lactate_rejected, 0)   AS n_lactate_rejected,
    l.max_lactate_24h,
    l.max_creatinine_24h,
    -- one flag per inclusion criterion
    (s.age >= :min_age)                                   AS c_adult,
    (s.icu_stay_seq = 1)                                  AS c_first_stay,
    (s.icu_los_days * 24 >= :min_los_hours)               AS c_los,
    (l.max_lactate_24h IS NOT NULL)                       AS c_lactate_measured
FROM stays s
LEFT JOIN labs l ON l.stay_id = s.stay_id
ORDER BY s.subject_id, s.intime;
