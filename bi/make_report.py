"""Generate the Power BI report pages (PBIR format) for ClinicalResearchDesk.pbip.

Writes ClinicalResearchDesk.Report/definition/pages/** from a compact layout
spec, so the dashboard is reproducible and reviewable in git.
Usage: python bi/make_report.py
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
                                      "bold": lit(True), "fontColor": color(NAVY)}}]}


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
                                                            "color": c}}]} for t, s, b, c in runs]
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
            ("Clinical Research Data Desk · Study EMK-2026-014", 22, True, NAVY),
            ("Early lactate and in-hospital mortality in adult ICU patients · MIMIC-IV Demo v2.2, de-identified extract · mock study for portfolio use", 11, False, GREY),
        ]),
        slicer("sl_sex", 1340, 20, 180, 80, col(F, "sex"), "Sex"),
        slicer("sl_adm", 1530, 20, 180, 80, col(F, "admission_group"), "Admission"),
        slicer("sl_unit", 1720, 20, 176, 80, col(C, "care_unit"), "ICU unit"),
    ]
    cards = [("Patients", "Eligible patients", NAVY), ("Deaths", "In-hospital deaths", RED),
             ("Mortality %", "In-hospital mortality", RED), ("High Lactate Share", "Lactate > 2 mmol/L", AMBER),
             ("Median Max Lactate", "Median max lactate (mmol/L)", NAVY), ("Median ICU LOS (days)", "Median ICU stay (days)", NAVY)]
    w = (1872 - 5 * 16) / 6
    for i, (m, label, c) in enumerate(cards):
        v.append(card(f"card_{i}", 24 + i * (w + 16), 124, w, 130, meas(F, m), label, c))

    v.append(visual("mort_by_lactate", "clusteredColumnChart", 24, 270, 620, 400,
                    {"Category": [col(L, "lactate_band")], "Y": [meas(F, "Mortality %")]},
                    {**data_labels(), **bar_color(RED)},
                    container_style("In-hospital mortality by early lactate band (mmol/L)")))
    v.append(visual("lactate_vs_los", "scatterChart", 660, 270, 620, 400,
                    {"Category": [(col(F, "study_id"), "Patient")], "X": [(agg(F, "max_lactate_24h"), "Max lactate, first 24 h (mmol/L)")],
                     "Y": [(agg(F, "icu_los_days"), "ICU length of stay (days)")],
                     "Series": [(col(F, "in_hospital_death"), "Died in hospital")]},
                    None, container_style("Max lactate vs ICU length of stay (1 = died in hospital)")))
    v.append(visual("pts_by_unit", "clusteredBarChart", 1296, 270, 600, 400,
                    {"Category": [col(C, "care_unit")], "Y": [meas(F, "Patients")]},
                    {**data_labels(), **bar_color(TEAL)},
                    container_style("Patients by first ICU unit"), sort=(meas(F, "Patients"), "Descending")))
    v.append(visual("mort_by_age", "clusteredColumnChart", 24, 686, 620, 370,
                    {"Category": [col(A, "age_band")], "Y": [meas(F, "Mortality %")]},
                    {**data_labels(), **bar_color(NAVY)}, container_style("In-hospital mortality by age band")))
    v.append(visual("band_table", "tableEx", 660, 686, 620, 370,
                    {"Values": [(col(L, "lactate_band"), "Lactate (mmol/L)"), (col(L, "meaning"), "Level"), meas(F, "Patients"),
                                meas(F, "Deaths"), (meas(F, "Mortality %"), "In-hospital mortality"),
                                (meas(F, "30-day Mortality %"), "30-day mortality")]},
                    None, container_style("Outcomes by lactate band")))
    v.append(card("risk_ratio", 1296, 686, 600, 170, meas(F, "Risk Ratio (High vs Normal)"),
                  "Mortality risk ratio: lactate > 2 vs ≤ 2", RED))
    note = card("sample_note", 1296, 872, 600, 184, meas(F, "Sample Size Note"), "Read with care", GREY)
    note["visual"]["objects"]["labels"] = [{"properties": {"color": color(GREY), "fontSize": lit(13)}}]
    note["visual"]["objects"]["wordWrap"] = [{"properties": {"show": lit(True)}}]
    v.append(note)
    return "overview", "Study overview", v


def quality():
    V, CF = "validation_checks", "cohort_flow"
    v = [textbox("q_title", 24, 12, 1872, 96, [
        ("Data quality & cohort selection", 22, True, NAVY),
        ("26 automated checks run on the source database and the delivered extract before release · any FAIL blocks the extract", 11, False, GREY),
    ])]
    cards = [("Checks", "Checks run", NAVY), ("Checks Passed", "Passed", GREEN), ("Checks Warned", "Warnings (documented)", AMBER),
             ("Checks Failed", "Failed", RED), ("Release Decision", "Release decision", GREEN)]
    w = (1872 - 4 * 16) / 5
    for i, (m, label, c) in enumerate(cards):
        v.append(card(f"q_card_{i}", 24 + i * (w + 16), 124, w, 130, meas(V, m), label, c,
                      size=20 if m == "Release Decision" else 30))
    v.append(visual("cohort_funnel", "funnel", 24, 270, 760, 400,
                    {"Category": [col(CF, "step")], "Y": [meas(CF, "Patients at Step")]},
                    {**data_labels("#FFFFFF"), **bar_color(NAVY)},
                    container_style("Cohort flow: 100 patients → 67 eligible")))
    status_colors = {"dataPoint": [series_color(col(V, "status"), st, c)
                                   for st, c in [("PASS", GREEN), ("WARN", AMBER), ("FAIL", RED)]]}
    v.append(visual("checks_by_area", "barChart", 800, 270, 1096, 400,
                    {"Category": [(col(V, "area"), "Area")], "Series": [(col(V, "status"), "Result")], "Y": [meas(V, "Checks")]},
                    {**data_labels("#FFFFFF"), **status_colors}, container_style("Checks by area and result"),
                    sort=(meas(V, "Checks"), "Descending")))
    v.append(visual("checks_table", "tableEx", 24, 686, 1872, 370,
                    {"Values": [(col(V, "layer"), "Layer"), (col(V, "area"), "Area"), (col(V, "check_name"), "Check"),
                                (col(V, "problems"), "Rows with problems"), (col(V, "status"), "Result")]},
                    None, container_style("Validation log (warnings first)"), sort=(col(V, "problems"), "Descending")))
    return "quality", "Data quality", v


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
