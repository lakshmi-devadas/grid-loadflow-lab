"""Command-line entry point.

Examples:
    python run_study.py
    python run_study.py --case case30 --margin 1.2
    python run_study.py --ratings data/my_ratings.csv --vmin 0.94 --vmax 1.06
"""

import argparse
from datetime import datetime
from pathlib import Path

from gridlab.contingency import Limits, check_state, run_n1
from gridlab.network import CASES, assign_ratings, branch_flows_mva, load_case, run_pf
from gridlab.report import plot_worst_loading, write_excel


def main():
    p = argparse.ArgumentParser(description="N-1 contingency study on an IEEE test system")
    p.add_argument("--case", default="case14", choices=list(CASES))
    p.add_argument("--margin", type=float, default=1.5,
                   help="rating = margin x base-case MVA flow (ignored if --ratings is given)")
    p.add_argument("--min-rating", type=float, default=30.0, help="floor for derived ratings, MVA")
    p.add_argument("--ratings", help="CSV with columns element,idx,rating_mva")
    p.add_argument("--vmin", type=float, default=0.95)
    p.add_argument("--vmax", type=float, default=1.10)
    p.add_argument("--max-loading", type=float, default=100.0)
    p.add_argument("--out", default="results")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    limits = Limits(args.vmin, args.vmax, args.max_loading)

    net = load_case(args.case)
    ratings = assign_ratings(net, args.margin, args.min_rating, args.ratings)

    if not run_pf(net):
        raise SystemExit("Base case did not converge.")
    base = branch_flows_mva(net).merge(ratings, on=["element", "idx"])
    base["loading_pct"] = (100 * base["s_mva"] / base["rating_mva"]).round(1)
    base["s_mva"] = base["s_mva"].round(2)
    base_over, base_volt = check_state(net, ratings, limits)

    summary, details = run_n1(net, ratings, limits)

    settings = {
        "Case": args.case,
        "Run at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Ratings": args.ratings or f"Derived: max({args.margin} x base flow, {args.min_rating} MVA)",
        "Voltage band (pu)": f"{args.vmin} - {args.vmax}",
        "Thermal limit (%)": args.max_loading,
        "Contingencies run": len(summary),
        "Base-case violations": len(base_over) + len(base_volt),
    }
    write_excel(out / f"{args.case}_n1_report.xlsx", settings, base, summary, details)
    plot_worst_loading(out / f"{args.case}_n1_loading.png", summary, args.max_loading,
                       f"{args.case.upper()} N-1: worst post-contingency loading per outage")

    counts = summary["status"].value_counts()
    print(f"\n{args.case}: {len(summary)} contingencies")
    for status in ["NOT CONVERGED", "ISLANDING", "VIOLATION", "OK"]:
        print(f"  {status:<14} {counts.get(status, 0)}")
    print("\nMost severe:")
    print(summary.head(5)[["outage", "status", "worst_branch", "worst_loading_pct"]].to_string(index=False))
    print(f"\nReport: {out / f'{args.case}_n1_report.xlsx'}")


if __name__ == "__main__":
    main()
