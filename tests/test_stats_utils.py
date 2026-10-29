"""Checks the hand-written statistics in src/stats_utils.py against
independent references: scikit-learn, SciPy, a direct optimisation of
Firth's penalised likelihood, and small examples worked out by hand."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import optimize, stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import stats_utils as su  # noqa: E402


@pytest.fixture
def logit_data():
    rng = np.random.default_rng(42)
    n = 400
    x1 = rng.normal(size=n)
    x2 = rng.binomial(1, 0.4, size=n)
    lin = -1.0 + 0.8 * x1 - 0.5 * x2
    y = rng.binomial(1, 1 / (1 + np.exp(-lin)))
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


# ---------- logistic regression ----------

def test_ml_logistic_matches_sklearn(logit_data):
    from sklearn.linear_model import LogisticRegression

    res = su.logistic(logit_data, "y", ["x1", "x2"])
    ref = LogisticRegression(C=np.inf, tol=1e-10, max_iter=1000).fit(logit_data[["x1", "x2"]], logit_data["y"])
    ours = np.log(res.table["OR"].to_numpy())
    theirs = np.r_[ref.intercept_, ref.coef_.ravel()]
    assert res.converged
    np.testing.assert_allclose(ours, theirs, atol=1e-5)


def _firth_by_optimiser(df, outcome, terms):
    """Maximise l(b) + 0.5*log|I(b)| directly - an independent route to Firth's estimate."""
    y = df[outcome].to_numpy(float)
    X = np.column_stack([np.ones(len(df))] + [df[t].to_numpy(float) for t in terms])

    def neg_pen_ll(b):
        eta = X @ b
        ll = np.sum(y * eta - np.logaddexp(0, eta))
        p = 1 / (1 + np.exp(-eta))
        info = X.T @ (X * (p * (1 - p))[:, None])
        return -(ll + 0.5 * np.linalg.slogdet(info)[1])

    return optimize.minimize(neg_pen_ll, np.zeros(X.shape[1]), method="BFGS", options={"gtol": 1e-10}).x


def test_firth_matches_direct_optimisation(logit_data):
    small = logit_data.iloc[:60]  # few events, where Firth matters
    res = su.logistic(small, "y", ["x1", "x2"], firth=True)
    np.testing.assert_allclose(np.log(res.table["OR"]), _firth_by_optimiser(small, "y", ["x1", "x2"]), atol=1e-4)


def test_firth_finite_under_complete_separation():
    # x perfectly predicts y: ML estimates diverge, Firth stays finite
    df = pd.DataFrame({"y": [0, 0, 0, 0, 1, 1, 1, 1], "x": [1, 2, 3, 4, 5, 6, 7, 8]})
    res = su.logistic(df, "y", ["x"], firth=True)
    assert res.converged
    assert np.isfinite(res.table["OR"]).all()
    np.testing.assert_allclose(np.log(res.table["OR"]), _firth_by_optimiser(df, "y", ["x"]), atol=1e-4)


def test_firth_shrinks_towards_null(logit_data):
    small = logit_data.iloc[:60]
    ml = np.log(su.logistic(small, "y", ["x1"]).table["OR"].iloc[1])
    firth = np.log(su.logistic(small, "y", ["x1"], firth=True).table["OR"].iloc[1])
    assert abs(firth) < abs(ml)


# ---------- survival ----------

def test_kaplan_meier_hand_example():
    # deaths at 1, 2, 3, 5; censored at 2 and 4
    time = [1, 2, 2, 3, 4, 5]
    event = [1, 1, 0, 1, 0, 1]
    km = su.kaplan_meier(time, event)
    expected = [1.0, 5 / 6, 5 / 6 * 4 / 5, 5 / 6 * 4 / 5 * 2 / 3, 0.0]
    np.testing.assert_allclose(km["survival"], expected)
    assert km["at_risk"].tolist() == [6, 6, 5, 3, 1]


def test_logrank_matches_scipy():
    rng = np.random.default_rng(7)
    t0, t1 = rng.exponential(10, 40), rng.exponential(6, 40)
    c0, c1 = rng.uniform(0, 15, 40), rng.uniform(0, 15, 40)
    time = np.round(np.r_[np.minimum(t0, c0), np.minimum(t1, c1)], 1)  # rounding creates ties
    event = np.r_[t0 <= c0, t1 <= c1].astype(int)
    group = np.r_[np.zeros(40), np.ones(40)].astype(int)

    _, p = su.logrank(time, event, group)

    def censored(mask):
        return stats.CensoredData(uncensored=time[mask & (event == 1)], right=time[mask & (event == 0)])

    ref = stats.logrank(censored(group == 0), censored(group == 1))
    assert p == pytest.approx(ref.pvalue, rel=1e-6)


# ---------- proportions ----------

def test_wilson_textbook_example():
    # 1 success out of 20: Newcombe (1998), method 3 -> 0.0089 to 0.2361
    lo, hi = su.wilson(1, 20)
    assert (round(lo, 4), round(hi, 4)) == (0.0089, 0.2361)


@pytest.mark.parametrize("k,n", [(0, 10), (1, 20), (7, 67), (81, 263), (50, 50)])
def test_wilson_matches_scipy(k, n):
    ref = stats.binomtest(k, n).proportion_ci(method="wilson")
    # SciPy uses z = 1.95996..., the project rounds to 1.96: agreement to 1e-5
    np.testing.assert_allclose(su.wilson(k, n), (ref.low, ref.high), atol=1e-5)
    assert 0 <= su.wilson(k, n)[0] <= su.wilson(k, n)[1] <= 1
