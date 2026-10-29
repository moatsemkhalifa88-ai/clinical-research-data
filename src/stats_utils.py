"""Small, dependency-light statistics toolkit (numpy + scipy only).

* logistic regression - maximum likelihood, or Firth's penalised likelihood
  (reduces small-sample bias when there are few events)
* Kaplan-Meier estimator and two-group log-rank test
* Wilson confidence interval for a proportion
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class LogitResult:
    table: pd.DataFrame        # term, OR, CI low, CI high, p
    n: int
    events: int
    method: str
    converged: bool


def logistic(df: pd.DataFrame, outcome: str, terms: list[str], firth: bool = False,
             max_iter: int = 100, tol: float = 1e-8) -> LogitResult:
    data = df[[outcome] + terms].dropna()
    y = data[outcome].to_numpy(float)
    X = np.column_stack([np.ones(len(data))] + [data[t].to_numpy(float) for t in terms])
    beta = np.zeros(X.shape[1])
    converged = False
    for _ in range(max_iter):
        p = 1 / (1 + np.exp(-X @ beta))
        w = p * (1 - p)
        info = X.T @ (X * w[:, None])
        score = X.T @ (y - p)
        if firth:
            # hat-matrix diagonal of the weighted design
            inv = np.linalg.inv(info)
            h = np.einsum("ij,jk,ik->i", X * np.sqrt(w)[:, None], inv, X * np.sqrt(w)[:, None])
            score = X.T @ (y - p + h * (0.5 - p))
        step = np.linalg.solve(info, score)
        # step halving keeps Newton stable when events are rare
        while np.max(np.abs(step)) > 5:
            step /= 2
        beta += step
        if np.max(np.abs(step)) < tol:
            converged = True
            break
    p = 1 / (1 + np.exp(-X @ beta))
    cov = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    se = np.sqrt(np.diag(cov))
    z = beta / se
    table = pd.DataFrame({
        "term": ["(intercept)"] + terms,
        "OR": np.exp(beta),
        "CI low": np.exp(beta - 1.96 * se),
        "CI high": np.exp(beta + 1.96 * se),
        "p": 2 * stats.norm.sf(np.abs(z)),
    })
    return LogitResult(table, len(data), int(y.sum()), "Firth penalised" if firth else "Maximum likelihood", converged)


def kaplan_meier(time: np.ndarray, event: np.ndarray) -> pd.DataFrame:
    time, event = np.asarray(time, float), np.asarray(event, int)
    rows, surv, var_sum = [{"time": 0.0, "survival": 1.0, "ci_low": 1.0, "ci_high": 1.0, "at_risk": len(time)}], 1.0, 0.0
    for t in np.unique(time[event == 1]):
        at_risk = int((time >= t).sum())
        d = int(((time == t) & (event == 1)).sum())
        surv *= 1 - d / at_risk
        if at_risk > d:
            var_sum += d / (at_risk * (at_risk - d))
        # log-log confidence interval (stays inside 0-1)
        if 0 < surv < 1:
            se = np.sqrt(var_sum) / abs(np.log(surv))
            lo, hi = surv ** np.exp(1.96 * se), surv ** np.exp(-1.96 * se)
        else:
            lo = hi = surv
        rows.append({"time": float(t), "survival": surv, "ci_low": lo, "ci_high": hi, "at_risk": at_risk})
    return pd.DataFrame(rows)


def logrank(time: np.ndarray, event: np.ndarray, group: np.ndarray) -> tuple[float, float]:
    """Two-group log-rank test. Returns (chi-square, p-value)."""
    time, event, group = np.asarray(time, float), np.asarray(event, int), np.asarray(group, int)
    o_minus_e, var = 0.0, 0.0
    for t in np.unique(time[event == 1]):
        at_risk = time >= t
        n, n1 = at_risk.sum(), (at_risk & (group == 1)).sum()
        d = ((time == t) & (event == 1)).sum()
        d1 = ((time == t) & (event == 1) & (group == 1)).sum()
        o_minus_e += d1 - d * n1 / n
        if n > 1:
            var += d * (n1 / n) * (1 - n1 / n) * (n - d) / (n - 1)
    chi2 = o_minus_e ** 2 / var if var > 0 else 0.0
    return float(chi2), float(stats.chi2.sf(chi2, 1))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    # clip: floating-point error can give -1e-17 when k == 0
    return max(0.0, centre - half), min(1.0, centre + half)
