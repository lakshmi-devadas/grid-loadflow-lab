"""Load a test network and attach branch ratings.

IEEE test cases in pandapower carry placeholder thermal limits (lines ~42 kA, transformers
9900 MVA), so loading percentages from them are meaningless. This module assigns explicit MVA
ratings instead, either from a CSV you provide or from a documented rule:

    rating = max(margin x base-case MVA flow, min_rating_mva)

That rule is an *assumption for study purposes*, not real equipment data. Replace it with
nameplate ratings whenever you have them.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pandapower as pp
import pandapower.networks as pn

warnings.filterwarnings("ignore", message=".*numba.*")

CASES = {
    "case14": pn.case14,
    "case30": pn.case30,
    "case57": pn.case57,
}


def load_case(name: str) -> pp.pandapowerNet:
    if name not in CASES:
        raise ValueError(f"Unknown case '{name}'. Choose from: {', '.join(CASES)}")
    return CASES[name]()


def run_pf(net: pp.pandapowerNet) -> bool:
    """Run AC power flow. Returns False instead of raising if it fails to converge."""
    try:
        pp.runpp(net, numba=False)
        return True
    except pp.LoadflowNotConverged:
        return False


def branch_flows_mva(net: pp.pandapowerNet) -> pd.DataFrame:
    """Apparent power through every line and transformer (max of both ends), in MVA."""
    lines = pd.DataFrame({
        "element": "line",
        "idx": net.line.index,
        "from_bus": net.line.from_bus.values,
        "to_bus": net.line.to_bus.values,
        "s_mva": np.maximum(
            np.hypot(net.res_line.p_from_mw, net.res_line.q_from_mvar),
            np.hypot(net.res_line.p_to_mw, net.res_line.q_to_mvar),
        ).values,
    })
    trafos = pd.DataFrame({
        "element": "trafo",
        "idx": net.trafo.index,
        "from_bus": net.trafo.hv_bus.values,
        "to_bus": net.trafo.lv_bus.values,
        "s_mva": np.maximum(
            np.hypot(net.res_trafo.p_hv_mw, net.res_trafo.q_hv_mvar),
            np.hypot(net.res_trafo.p_lv_mw, net.res_trafo.q_lv_mvar),
        ).values,
    })
    df = pd.concat([lines, trafos], ignore_index=True)
    df["s_mva"] = df["s_mva"].fillna(0.0)  # out-of-service branches report NaN
    # Labels use IEEE 1-based bus numbers so results match published single-line diagrams
    df["name"] = df.apply(lambda r: f"{r.element.title()} {r.from_bus + 1}-{r.to_bus + 1}", axis=1)
    return df


def assign_ratings(
    net: pp.pandapowerNet,
    margin: float = 1.5,
    min_rating_mva: float = 30.0,
    ratings_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Return a table of branch ratings (element, idx, rating_mva).

    If ratings_csv is given it must have columns element,idx,rating_mva and is used as-is.
    Otherwise ratings are derived from the base-case flow using the rule in the module docstring.
    """
    if ratings_csv:
        ratings = pd.read_csv(ratings_csv)
        missing = {"element", "idx", "rating_mva"} - set(ratings.columns)
        if missing:
            raise ValueError(f"ratings CSV is missing columns: {missing}")
        return ratings[["element", "idx", "rating_mva"]]

    if not run_pf(net):
        raise RuntimeError("Base case did not converge; cannot derive ratings.")
    base = branch_flows_mva(net)
    base["rating_mva"] = np.maximum(base["s_mva"] * margin, min_rating_mva).round(1)
    return base[["element", "idx", "rating_mva"]]
