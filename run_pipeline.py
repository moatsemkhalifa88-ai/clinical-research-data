"""Run the full research-data workflow, or one step.

    python run_pipeline.py            # all steps
    python run_pipeline.py load       # 0. ZIP -> SQLite
    python run_pipeline.py feasibility
    python run_pipeline.py extract
    python run_pipeline.py validate
    python run_pipeline.py analysis
    python run_pipeline.py bi         # 5. star schema for Power BI
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import analysis, export_bi, extract, feasibility, load_data, validate  # noqa: E402

STEPS = {
    "load": ("0. Load MIMIC-IV demo into SQLite", load_data.load),
    "feasibility": ("1. Feasibility check", feasibility.run),
    "extract": ("2. Protocol-driven de-identified extract", extract.run),
    "validate": ("3. Data validation", validate.run),
    "analysis": ("4. Statistical analysis", analysis.run),
    "bi": ("5. Export star schema for Power BI", export_bi.run),
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(STEPS)
    for key in wanted:
        title, fn = STEPS[key]
        print(title)
        result = fn()
        if key == "validate" and result is False:
            sys.exit("Validation failed - extract NOT released. See reports/02_validation.md")
    print("Done. Reports are in reports/")
