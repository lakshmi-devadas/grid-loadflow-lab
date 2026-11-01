"""N-1 contingency analysis: take each branch out of service, re-run the power flow,
and record thermal overloads, voltage violations, islanding and non-convergence."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pandapower as pp
import pandapower.topology as top

from .network import branch_flows_mva, run_pf


@dataclass
class Limits:
    v_min_pu: float = 0.95
    v_max_pu: float = 1.10
    max_loading_pct: float = 100.0


def _islanded_buses(net: pp.pandapowerNet) -> set[int]:
    """Buses with no path to a slack/generator after the outage."""
    return set(top.unsupplied_buses(net))


def branch_loading(net, ratings: pd.DataFrame) -> pd.DataFrame:
    """Every branch's MVA flow and % loading for the net's current solved state."""
    flows = branch_flows_mva(net).merge(ratings, on=["element", "idx"])
    flows["loading_pct"] = 100 * flows["s_mva"] / flows["rating_mva"]
    return flows


def check_state(net, ratings: pd.DataFrame, limits: Limits) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (branch_violations, voltage_violations) for the net's current solved state."""
    flows = branch_loading(net, ratings)
    over = flows[flows["loading_pct"] > limits.max_loading_pct]

    v = net.res_bus.vm_pu.dropna()
    bad_v = v[(v < limits.v_min_pu) | (v > limits.v_max_pu)]
    volt = pd.DataFrame({"bus": bad_v.index, "vm_pu": bad_v.values})
    return over, volt


def run_n1(net: pp.pandapowerNet, ratings: pd.DataFrame, limits: Limits | None = None):
    """Run every single-branch outage.

    Returns:
        summary: one row per contingency
        details: one row per violation found
    """
    limits = limits or Limits()
    branches = ratings[["element", "idx"]].itertuples(index=False)
    summary, details = [], []

    for element, idx in branches:
        table = net.line if element == "line" else net.trafo
        a, b = (("from_bus", "to_bus") if element == "line" else ("hv_bus", "lv_bus"))
        name = f"{element.title()} {table.at[idx, a] + 1}-{table.at[idx, b] + 1}"  # IEEE 1-based

        table.at[idx, "in_service"] = False
        try:
            islanded = _islanded_buses(net)
            converged = run_pf(net)
            worst = None
            if not converged:
                status, over, volt = "NOT CONVERGED", pd.DataFrame(), pd.DataFrame()
            else:
                over, volt = check_state(net, ratings, limits)
                # Buses cut off from supply show NaN voltage; they are reported as islanding, not as V violations
                status = "ISLANDING" if islanded else ("VIOLATION" if len(over) or len(volt) else "OK")
                # Worst loading among the branches still in service, whether or not it violates
                loading = branch_loading(net, ratings)
                loading = loading[~((loading.element == element) & (loading.idx == idx))]
                worst = loading.loc[loading["loading_pct"].idxmax()]
            summary.append({
                "outage": name,
                "status": status,
                "overloaded_branches": len(over),
                "voltage_violations": len(volt),
                "islanded_buses": ", ".join(str(b + 1) for b in sorted(islanded)) or "-",
                "worst_branch": worst["name"] if worst is not None else "-",
                "worst_loading_pct": round(float(worst["loading_pct"]), 1) if worst is not None else None,
            })
            for _, r in over.iterrows():
                details.append({"outage": name, "type": "Thermal", "where": r["name"],
                                "value": round(r["loading_pct"], 1), "limit": limits.max_loading_pct,
                                "unit": "% of rating"})
            for _, r in volt.iterrows():
                details.append({"outage": name, "type": "Voltage", "where": f"Bus {int(r['bus']) + 1}",
                                "value": round(r["vm_pu"], 4),
                                "limit": limits.v_min_pu if r["vm_pu"] < limits.v_min_pu else limits.v_max_pu,
                                "unit": "pu"})
        finally:
            table.at[idx, "in_service"] = True  # always restore the network

    severity = {"NOT CONVERGED": 0, "ISLANDING": 1, "VIOLATION": 2, "OK": 3}
    summary_df = pd.DataFrame(summary)
    summary_df = summary_df.sort_values(
        by=["status", "worst_loading_pct"], key=lambda s: s.map(severity) if s.name == "status" else -s.fillna(0)
    ).reset_index(drop=True)
    return summary_df, pd.DataFrame(details, columns=["outage", "type", "where", "value", "limit", "unit"])
