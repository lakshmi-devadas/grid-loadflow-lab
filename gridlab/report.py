"""Excel report and summary chart."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

STATUS_FILL = {
    "OK": "D3F9D8",
    "VIOLATION": "FFE8CC",
    "ISLANDING": "FFC9C9",
    "NOT CONVERGED": "FA5252",
}


def write_excel(path: Path, settings: dict, base: pd.DataFrame, summary: pd.DataFrame, details: pd.DataFrame):
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        pd.DataFrame(list(settings.items()), columns=["Setting", "Value"]).to_excel(xl, sheet_name="Study settings", index=False)
        base.to_excel(xl, sheet_name="Base case", index=False)
        summary.to_excel(xl, sheet_name="N-1 summary", index=False)
        details.to_excel(xl, sheet_name="Violations", index=False)

        for ws in xl.book.worksheets:
            for cell in ws[1]:
                cell.font = Font(bold=True)
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col) + 2
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(width, 45)
            ws.freeze_panes = "A2"

        ws = xl.book["N-1 summary"]
        status_col = list(summary.columns).index("status") + 1
        for row in ws.iter_rows(min_row=2):
            colour = STATUS_FILL.get(row[status_col - 1].value)
            if colour:
                for c in row:
                    c.fill = PatternFill("solid", fgColor=colour)


def plot_worst_loading(path: Path, summary: pd.DataFrame, limit: float, title: str):
    df = summary.dropna(subset=["worst_loading_pct"]).sort_values("worst_loading_pct")
    if df.empty:
        df = summary.assign(worst_loading_pct=0)
    fig, ax = plt.subplots(figsize=(8, max(3, 0.32 * len(df) + 1)))
    colours = ["#d9480f" if v > limit else "#495057" for v in df["worst_loading_pct"]]
    ax.barh(df["outage"], df["worst_loading_pct"], color=colours)
    ax.axvline(limit, color="#c92a2a", linestyle="--", linewidth=1, label=f"{limit:.0f}% thermal limit")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.set_xlabel("Worst branch loading after outage (% of rating)")
    ax.set_title(title, loc="left", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
