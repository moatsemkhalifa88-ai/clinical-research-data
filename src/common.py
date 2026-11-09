"""Shared helpers: protocol loading, database connection, candidate query,
Hebrew text for matplotlib."""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml
from bidi.algorithm import get_display

# DejaVu Sans ships with matplotlib and includes Hebrew glyphs, so figures
# render the same on every machine (and in CI).
matplotlib.rcParams["font.family"] = "DejaVu Sans"


def ink_centre(text: str) -> float:
    """Render `text` with matplotlib and return where its ink sits, from
    0 (left edge of the drawn text) to 1 (right edge)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(2, 1), dpi=100, facecolor="white")
    canvas = FigureCanvasAgg(fig)
    fig.text(0.5, 0.5, text, ha="center", va="center", fontsize=36, color="black")
    canvas.draw()
    cols = (255 - np.asarray(canvas.buffer_rgba())[..., 0].astype(float)).sum(axis=0)
    xs = np.nonzero(cols)[0]
    centre = (cols * np.arange(len(cols))).sum() / cols.sum()
    return (centre - xs[0]) / (xs[-1] - xs[0])


@lru_cache(maxsize=1)
def mpl_renders_rtl() -> bool:
    """Does this matplotlib lay out Hebrew right to left on its own?

    Checked by rendering, not by version: draw "מי" (a wide mem, then a narrow
    yod) and "ימ" (the same letters reversed). If matplotlib applies the bidi
    algorithm, the first letter is drawn on the right, so the ink of "מי" sits
    further right than the ink of "ימ". Without bidi it is the other way round.
    """
    return ink_centre("מי") > ink_centre("ימ")


def he(text: str) -> str:
    """Hebrew text for matplotlib, displayed right to left.

    If matplotlib already lays out right-to-left text (e.g. builds with libraqm),
    the text is returned as is; otherwise it is reordered with python-bidi.
    Use ONLY for strings passed to matplotlib. Markdown (GitHub) and Power BI
    apply the bidi algorithm themselves; reordering there would reverse the text.
    """
    text = str(text)
    if mpl_renders_rtl():
        return text
    return "\n".join(get_display(line) for line in text.split("\n"))


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "mimic_demo.db"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"            # Hebrew figures (the default)
FIGURES_EN = FIGURES / "en"              # English copies, used by README.en.md
EXTRACT_DIR = ROOT / "data" / "extract"
RESTRICTED_DIR = ROOT / "data" / "restricted"
DEFAULT_PROTOCOL = ROOT / "protocol" / "lactate_mortality.yaml"


def load_protocol(path: Path = DEFAULT_PROTOCOL) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def protocol_text(protocol: dict, field: str) -> str:
    """Hebrew version of a protocol text field (e.g. title_he), else the English one."""
    return str(protocol.get(f"{field}_he") or protocol[field]).strip()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found - run `python run_pipeline.py load` first")
    return sqlite3.connect(db_path)


def sql_params(protocol: dict) -> dict:
    pop, exp, creat = protocol["population"], protocol["exposure"], protocol["labs"]["creatinine"]
    return {
        "min_age": pop["min_age"],
        "min_los_hours": pop["min_icu_los_hours"],
        "hours_before": pop["lab_window_hours_before_icu"],
        "hours_after": pop["lab_window_hours_after_icu"],
        "lactate_itemid": exp["lab_itemid"],
        "lactate_min": exp["plausible_range"][0],
        "lactate_max": exp["plausible_range"][1],
        "creatinine_itemid": creat["itemid"],
        "creatinine_min": creat["plausible_range"][0],
        "creatinine_max": creat["plausible_range"][1],
    }


def candidate_stays(con: sqlite3.Connection, protocol: dict) -> pd.DataFrame:
    query = (ROOT / "sql" / "candidate_stays.sql").read_text(encoding="utf-8")
    df = pd.read_sql_query(query, con, params=sql_params(protocol))
    for col in ["intime", "outtime", "admittime", "dischtime", "deathtime", "dod"]:
        df[col] = pd.to_datetime(df[col])
    return df


# Sequential inclusion steps, in the order a flow diagram shows them: (flag, Hebrew label, English label)
ALL_STAYS = ("כל האשפוזים בטיפול נמרץ במאגר", "All ICU stays in the database")
CRITERIA = [
    ("c_adult", "גיל {min_age} ומעלה", "Age >= {min_age}"),
    ("c_first_stay", "אשפוז ראשון של המטופל בטיפול נמרץ", "First ICU stay of the patient"),
    ("c_los", "שהייה בטיפול נמרץ של {min_icu_los_hours} שעות לפחות", "ICU length of stay >= {min_icu_los_hours} h"),
    ("c_lactate_measured", "נמדד לקטט ({lab_window_hours_before_icu} שעות לפני עד {lab_window_hours_after_icu} שעות אחרי הקבלה)",
     "Lactate measured (-{lab_window_hours_before_icu} h to +{lab_window_hours_after_icu} h)"),
]


def apply_criteria(df: pd.DataFrame, protocol: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Apply inclusion criteria one at a time and record the flow."""
    pop = protocol["population"]
    labels = {"min_age": pop["min_age"], "min_icu_los_hours": pop["min_icu_los_hours"],
              "lab_window_hours_before_icu": pop["lab_window_hours_before_icu"],
              "lab_window_hours_after_icu": pop["lab_window_hours_after_icu"]}
    flow = [{"step": ALL_STAYS[0], "step_en": ALL_STAYS[1], "stays": len(df),
             "patients": df.subject_id.nunique(), "excluded": 0}]
    current = df
    for col, label, label_en in CRITERIA:
        kept = current[current[col] == 1]
        flow.append({"step": label.format(**labels), "step_en": label_en.format(**labels), "stays": len(kept),
                     "patients": kept.subject_id.nunique(), "excluded": len(current) - len(kept)})
        current = kept
    return current.copy(), flow


def rtl(markdown: str) -> str:
    """Wrap a Markdown document for right-to-left display on GitHub.

    The blank lines inside the div are required: without them GitHub does not
    render the Markdown (headings, tables, images) inside the HTML block.
    """
    return f'<div dir="rtl">\n\n{markdown.strip()}\n\n</div>\n'


def md_table(df: pd.DataFrame) -> str:
    """Markdown table without the tabulate dependency."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)
