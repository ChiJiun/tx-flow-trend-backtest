"""Gate claims of prospective evidence against the preregistered freeze.

Accepts a future daily ledger exported by a separately reviewed forward engine.
It deliberately never re-labels the historical exploratory sample as out-of-sample.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pandas as pd
from validate_inputs import validate

BASE = Path(__file__).resolve().parent

def assess(path):
    validate()
    protocol = json.loads((BASE / "prospective_protocol.json").read_text(encoding="utf-8"))
    freeze = pd.Timestamp(protocol["frozen_on"])
    daily = pd.read_csv(path, parse_dates=["date", "signal_date"])
    required = {"date", "signal_date", "pnl", "equity", "daily_return", "cost", "target"}
    if not required.issubset(daily): raise ValueError(f"missing ledger fields: {required-set(daily)}")
    if daily.empty or daily.date.isna().any() or daily.signal_date.isna().any():
        raise ValueError("empty ledger or invalid dates")
    if daily.date.duplicated().any() or not daily.date.is_monotonic_increasing:
        raise ValueError("dates must be strictly increasing")
    if daily.date.min() <= freeze or not (daily.signal_date < daily.date).all():
        raise ValueError("historical overlap or future signal detected")
    if not np.isfinite(daily[["pnl", "equity", "daily_return", "cost"]]).all().all():
        raise ValueError("nonfinite ledger")
    if not daily.target.isin([0, 1]).all() or (daily.cost < 0).any():
        raise ValueError("invalid position or cost")
    initial = float(protocol["capital"])
    if not np.allclose(daily.equity, initial + daily.pnl.cumsum(), atol=1e-6, rtol=0):
        raise ValueError("equity does not reconcile")
    if not np.allclose(daily.daily_return, daily.pnl / daily.equity.shift(fill_value=initial), atol=1e-12, rtol=0):
        raise ValueError("daily returns do not reconcile")
    peak = daily.equity.cummax().clip(lower=initial)
    drawdown = float((1 - daily.equity/peak).max())
    vol = float(daily.daily_return.std(ddof=1))
    sharpe = float(daily.daily_return.mean()/vol*np.sqrt(252)) if vol > 0 else None
    result = dict(status="pending" if len(daily) < protocol["minimum_future_sessions"] else "evaluable",
                  frozen_on=protocol["frozen_on"], future_days=len(daily), first=str(daily.date.min().date()),
                  last=str(daily.date.max().date()), ledger_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                  net_pnl=float(daily.pnl.sum()), Sharpe=sharpe, MDD_pct=drawdown)
    if result["status"] == "evaluable":
        criteria = protocol["primary_success_criteria"]
        result["primary_criteria_pass"] = (result["net_pnl"] > criteria["after_cost_net_pnl_gt"]
            and sharpe is not None and sharpe > criteria["sharpe_gt"]
            and drawdown <= criteria["max_drawdown_pct_lte"])
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("future_daily_csv", help="forward-engine output from genuinely new sessions")
    args = parser.parse_args()
    print(json.dumps(assess(args.future_daily_csv), ensure_ascii=False, indent=2))
