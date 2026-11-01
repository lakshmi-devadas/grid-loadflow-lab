import warnings

import pandas as pd
import pytest

from gridlab.contingency import Limits, run_n1
from gridlab.network import assign_ratings, load_case, run_pf

warnings.filterwarnings("ignore")


@pytest.fixture
def net():
    return load_case("case14")


def test_base_case_converges(net):
    assert run_pf(net)
    assert net.res_bus.vm_pu.between(0.9, 1.1).all()


def test_every_branch_is_tested_once(net):
    ratings = assign_ratings(net)
    summary, _ = run_n1(net, ratings)
    assert len(summary) == len(net.line) + len(net.trafo) == 20


def test_network_is_restored_after_study(net):
    ratings = assign_ratings(net)
    run_n1(net, ratings)
    assert net.line.in_service.all()
    assert net.trafo.in_service.all()


def test_condenser_transformer_outage_islands_bus_8(net):
    # IEEE bus 8 (synchronous condenser) connects only through transformer 7-8
    ratings = assign_ratings(net)
    summary, _ = run_n1(net, ratings)
    row = summary[summary.outage == "Trafo 7-8"].iloc[0]
    assert row.status == "ISLANDING"
    assert row.islanded_buses == "8"


def test_generous_ratings_leave_no_thermal_violations(net):
    ratings = assign_ratings(net, margin=10, min_rating_mva=500)
    summary, details = run_n1(net, ratings, Limits(v_min_pu=0.8, v_max_pu=1.2))
    assert (details.type == "Thermal").sum() == 0
    assert set(summary.status) <= {"OK", "ISLANDING"}


def test_tight_ratings_flag_the_known_weak_corridor(net):
    # Losing line 1-2 forces its ~158 MVA onto line 1-5, the classic IEEE 14 bottleneck
    summary, _ = run_n1(net, assign_ratings(net))
    row = summary[summary.outage == "Line 1-2"].iloc[0]
    assert row.status == "VIOLATION"
    assert row.worst_branch == "Line 1-5"


def test_ratings_csv_is_validated(tmp_path, net):
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"element": ["line"], "idx": [0]}).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        assign_ratings(net, ratings_csv=bad)
