"""Generate the Power BI report pages (PBIR format) for ClinicalResearchDesk.pbip.

Writes ClinicalResearchDesk.Report/definition/pages/** from a compact layout
spec, so the dashboard is reproducible and reviewable in git.
Usage: python bi/make_report.py

All on-screen text is Hebrew. Model names (tables, columns, measures) stay in
English; each field gets a Hebrew displayName inside the visual instead, so the
semantic model is untouched. Power BI lays out right-to-left text itself, so the
strings here are plain Hebrew (no bidi reordering).
"""
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES = HERE / "ClinicalResearchDesk.Report" / "definition" / "pages"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
NAVY, TEAL, RED, AMBER, GREEN, GREY = "#1F3864", "#2E86AB", "#C0392B", "#E67E22", "#27AE60", "#5F6B7A"


# ---------- field helpers ----------
def col(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def meas(table, name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def agg(table, name, fn=0):  # 0 = Sum, 1 = Avg
    return {"Aggregation": {"Expression": col(table, name), "Function": fn}}


def proj(field):
    display = None
    if isinstance(field, tuple):
        field, display = field
    kind = next(iter(field))
    if kind == "Aggregation":
        inner = field["Aggregation"]["Expression"]["Column"]
        fn = {0: "Sum", 1: "Avg"}[field["Aggregation"]["Function"]]
        ref = f"{fn}({inner['Expression']['SourceRef']['Entity']}.{inner['Property']})"
        native = inner["Property"]
    else:
        inner = field[kind]
        ref = f"{inner['Expression']['SourceRef']['Entity']}.{inner['Property']}"
        native = inner["Property"]
    out = {"field": field, "queryRef": ref, "nativeQueryRef": native}
    if display:
        out["displayName"] = display
    return out


def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": f"'{v}'"}}}


def color(hexcode):
    return {"solid": {"color": lit(hexcode)}}


def title_obj(text, size=12):
    return {"title": [{"properties": {"show": lit(True), "text": lit(text), "fontSize": lit(size),
                                      "bold": lit(True), "fontColor": color(NAVY), "alignment": lit("right")}}]}


def container_style(text=None):
    vco = {"background": [{"properties": {"show": lit(True), "color": color("#FFFFFF")}}],
           "border": [{"properties": {"show": lit(True), "color": color("#D6DCE5"), "radius": lit(8)}}],
           "dropShadow": [{"properties": {"show": lit(False)}}],
           "subTitle": [{"properties": {"show": lit(False)}}]}
    if text:
        vco.update(title_obj(text))
    return vco


# ---------- visual builders ----------
def visual(name, vtype, x, y, w, h, roles=None, objects=None, vco=None, sort=None):
    v = {"visualType": vtype}
    if roles:
        v["query"] = {"queryState": {r: {"projections": [proj(f) for f in fs]} for r, fs in roles.items()}}
        if sort:
            field, direction = sort
            v["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}], "isDefaultSort": True}
    if objects:
        v["objects"] = objects
    if vco is not None:
        v["visualContainerObjects"] = vco
    v["drillFilterOtherVisuals"] = True
    return {"$schema": f"{SCHEMA}/visualContainer/2.14.0/schema.json", "name": name,
            "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": 0}, "visual": v}


def textbox(name, x, y, w, h, runs):
    paragraphs = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{s}pt", "fontWeight": "bold" if b else "normal",
                                                            "color": c}}],
                   "horizontalTextAlignment": "right"} for t, s, b, c in runs]
    return {"$schema": f"{SCHEMA}/visualContainer/2.14.0/schema.json", "name": name,
            "position": {"x": x, "y": y, "z": 1, "height": h, "width": w, "tabOrder": 0},
            "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
                       "drillFilterOtherVisuals": True}}


def card(name, x, y, w, h, field, label, value_color=NAVY, size=30):
    objects = {"labels": [{"properties": {"color": color(value_color), "fontSize": lit(size)}}],
               "categoryLabels": [{"properties": {"show": lit(False)}}]}
    return visual(name, "card", x, y, w, h, {"Values": [field]}, objects, container_style(label))


def data_labels(fmt_color=NAVY):
    return {"labels": [{"properties": {"show": lit(True), "color": color(fmt_color), "fontSize": lit(11)}}]}


def bar_color(hexcode):
    return {"dataPoint": [{"properties": {"fill": color(hexcode)}}]}


def series_color(field, value, hexcode):
    """Fixed colour for one legend value (e.g. PASS = green)."""
    scope = {"Comparison": {"ComparisonKind": 0, "Left": field, "Right": {"Literal": {"Value": f"'{value}'"}}}}
    return {"properties": {"fill": color(hexcode)}, "selector": {"data": [{"scopeId": scope}]}}


def slicer(name, x, y, w, h, field, label):
    objects = {"data": [{"properties": {"mode": lit("Dropdown")}}],
               "header": [{"properties": {"show": lit(True), "text": lit(label), "fontColor": color(NAVY)}}]}
    return visual(name, "slicer", x, y, w, h, {"Values": [field]}, objects, container_style())


# ---------- pages ----------
def overview():
    F, L, A, C = "fact_patient", "dim_lactate_band", "dim_age_band", "dim_care_unit"
    v = [
        textbox("title", 24, 12, 1300, 96, [
            ("Clinical Research Data Desk · מחקר EMK-2026-014", 22, True, NAVY),
            ("לקטט מוקדם ותמותה באשפוז במטופלים מבוגרים בטיפול נמרץ · MIMIC-IV Demo v2.2, קובץ חילוץ ללא מזהים · מחקר פיקטיבי לתיק עבודות", 11, False, GREY),
        ]),
        slicer("sl_sex", 1340, 20, 180, 80, (col(F, "sex"), "מין"), "מין"),
        slicer("sl_adm", 1530, 20, 180, 80, (col(F, "admission_group"), "סוג קבלה"), "סוג קבלה"),
        slicer("sl_unit", 1720, 20, 176, 80, (col(C, "care_unit"), "יחידת טיפול נמרץ"), "יחידת טיפול נמרץ"),
    ]
    cards = [("Patients", "מטופלים שנכללו", NAVY), ("Deaths", "פטירות באשפוז", RED),
             ("Mortality %", "תמותה באשפוז", RED), ("High Lactate Share", "לקטט > 2 mmol/L", AMBER),
             ("Median Max Lactate", "חציון הלקטט המרבי (mmol/L)", NAVY), ("Median ICU LOS (days)", "חציון השהייה בטיפול נמרץ (ימים)", NAVY)]
    w = (1872 - 5 * 16) / 6
    for i, (m, label, c) in enumerate(cards):
        v.append(card(f"card_{i}", 24 + i * (w + 16), 124, w, 130, (meas(F, m), label), label, c))

    v.append(visual("mort_by_lactate", "clusteredColumnChart", 24, 270, 620, 400,
                    {"Category": [(col(L, "lactate_band"), "טווח לקטט (mmol/L)")], "Y": [(meas(F, "Mortality %"), "תמותה באשפוז")]},
                    {**data_labels(), **bar_color(RED)},
                    container_style("תמותה באשפוז לפי טווח הלקטט המוקדם (mmol/L)")))
    v.append(visual("lactate_vs_los", "scatterChart", 660, 270, 620, 400,
                    {"Category": [(col(F, "study_id"), "מטופל")], "X": [(agg(F, "max_lactate_24h"), "לקטט מרבי ב-24 השעות הראשונות (mmol/L)")],
                     "Y": [(agg(F, "icu_los_days"), "משך השהייה בטיפול נמרץ (ימים)")],
                     "Series": [(col(F, "in_hospital_death"), "נפטר באשפוז")]},
                    None, container_style("לקטט מרבי מול משך השהייה בטיפול נמרץ (1 = נפטר באשפוז)")))
    v.append(visual("pts_by_unit", "clusteredBarChart", 1296, 270, 600, 400,
                    {"Category": [(col(C, "care_unit"), "יחידה")], "Y": [(meas(F, "Patients"), "מטופלים")]},
                    {**data_labels(), **bar_color(TEAL)},
                    container_style("מטופלים לפי יחידת הטיפול הנמרץ הראשונה"), sort=(meas(F, "Patients"), "Descending")))
    v.append(visual("mort_by_age", "clusteredColumnChart", 24, 686, 620, 370,
                    {"Category": [(col(A, "age_band"), "קבוצת גיל")], "Y": [(meas(F, "Mortality %"), "תמותה באשפוז")]},
                    {**data_labels(), **bar_color(NAVY)}, container_style("תמותה באשפוז לפי קבוצת גיל")))
    v.append(visual("band_table", "tableEx", 660, 686, 620, 370,
                    {"Values": [(col(L, "lactate_band"), "לקטט (mmol/L)"), (col(L, "meaning"), "רמה"),
                                (meas(F, "Patients"), "מטופלים"), (meas(F, "Deaths"), "פטירות"),
                                (meas(F, "Mortality %"), "תמותה באשפוז"),
                                (meas(F, "30-day Mortality %"), "תמותה תוך 30 יום")]},
                    None, container_style("תוצאות לפי טווח לקטט")))
    v.append(card("risk_ratio", 1296, 686, 600, 170, (meas(F, "Risk Ratio (High vs Normal)"), "יחס סיכון לתמותה"),
                  "יחס סיכון (Risk ratio) לתמותה: לקטט > 2 לעומת ≤ 2", RED))
    note = card("sample_note", 1296, 872, 600, 184, (meas(F, "Sample Size Note"), "הערת גודל מדגם"), "לקרוא בזהירות", GREY)
    note["visual"]["objects"]["labels"] = [{"properties": {"color": color(GREY), "fontSize": lit(13)}}]
    note["visual"]["objects"]["wordWrap"] = [{"properties": {"show": lit(True)}}]
    v.append(note)
    return "overview", "סקירת המחקר", v


def quality():
    V, CF = "validation_checks", "cohort_flow"
    v = [textbox("q_title", 24, 12, 1872, 96, [
        ("איכות הנתונים ובחירת הקוהורט", 22, True, NAVY),
        ("26 בדיקות אוטומטיות על מאגר המקור ועל קובץ החילוץ, לפני המסירה לחוקר · כל FAIL חוסם את המסירה", 11, False, GREY),
    ])]
    cards = [("Checks", "בדיקות שהורצו", NAVY), ("Checks Passed", "עברו", GREEN), ("Checks Warned", "אזהרות (מתועדות)", AMBER),
             ("Checks Failed", "נכשלו", RED), ("Release Decision", "החלטת מסירה", GREEN)]
    w = (1872 - 4 * 16) / 5
    for i, (m, label, c) in enumerate(cards):
        v.append(card(f"q_card_{i}", 24 + i * (w + 16), 124, w, 130, (meas(V, m), label), label, c,
                      size=20 if m == "Release Decision" else 30))
    v.append(visual("cohort_funnel", "funnel", 24, 270, 760, 400,
                    {"Category": [(col(CF, "step"), "שלב")], "Y": [(meas(CF, "Patients at Step"), "מטופלים בשלב")]},
                    {**data_labels("#FFFFFF"), **bar_color(NAVY)},
                    container_style("זרימת הקוהורט: 100 מטופלים ← 67 שנכללו")))
    status_colors = {"dataPoint": [series_color(col(V, "status"), st, c)
                                   for st, c in [("PASS", GREEN), ("WARN", AMBER), ("FAIL", RED)]]}
    v.append(visual("checks_by_area", "barChart", 800, 270, 1096, 400,
                    {"Category": [(col(V, "area"), "תחום")], "Series": [(col(V, "status"), "תוצאה")],
                     "Y": [(meas(V, "Checks"), "בדיקות")]},
                    {**data_labels("#FFFFFF"), **status_colors}, container_style("בדיקות לפי תחום ותוצאה"),
                    sort=(meas(V, "Checks"), "Descending")))
    v.append(visual("checks_table", "tableEx", 24, 686, 1872, 370,
                    {"Values": [(col(V, "layer"), "שכבה"), (col(V, "area"), "תחום"), (col(V, "check_name"), "בדיקה"),
                                (col(V, "problems"), "שורות עם בעיה"), (col(V, "status"), "תוצאה")]},
                    None, container_style("יומן בדיקות התקינות (אזהרות קודם)"), sort=(col(V, "problems"), "Descending")))
    return "quality", "איכות נתונים", v


def write():
    pages = [overview(), quality()]
    if PAGES.exists():
        shutil.rmtree(PAGES)
    PAGES.mkdir(parents=True)
    for page_id, display, visuals in pages:
        d = PAGES / page_id
        (d / "visuals").mkdir(parents=True)
        page = {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": page_id, "displayName": display,
                "displayOption": "FitToPage", "height": 1080, "width": 1920,
                "objects": {"background": [{"properties": {"color": color("#F3F5F9"), "transparency": lit(0)}}]}}
        (d / "page.json").write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
        for i, vis in enumerate(visuals):
            vis["position"]["tabOrder"] = i
            vd = d / "visuals" / vis["name"]
            vd.mkdir()
            (vd / "visual.json").write_text(json.dumps(vis, indent=2, ensure_ascii=False), encoding="utf-8")
    meta = {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json",
            "pageOrder": [p[0] for p in pages], "activePageName": pages[0][0]}
    (PAGES / "pages.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {len(pages)} pages, {sum(len(p[2]) for p in pages)} visuals")


if __name__ == "__main__":
    write()
