"""Compare one-contract futures P&L with TAIEX using the same initial TX notional."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
MULTIPLIER = 200.0

def build():
    strategy = pd.read_csv(OUT / "strategy_daily.csv", parse_dates=["date"])
    futures = pd.read_csv(OUT / "benchmark_daily.csv", parse_dates=["date"])
    taiex = pd.read_csv(BASE / "input/taiex.csv", parse_dates=["date"])
    source = json.loads((BASE / "source_audits/taiex_sources.json").read_text(encoding="utf-8"))
    prices = pd.read_csv(BASE / "input/prices.csv", parse_dates=["date"])
    dates = strategy.date
    assert dates.equals(futures.date) and not taiex.date.duplicated().any()
    spot = taiex.set_index("date").close.reindex(dates)
    assert spot.notna().all() and (spot > 0).all()
    first = prices.set_index("date").loc[dates.iloc[0]]
    initial_tx_notional = float(first.open) * MULTIPLIER
    index_open = float(source["first_session_open"])
    assert source["first_session"] == str(dates.iloc[0].date())
    assert index_open > 0 and initial_tx_notional > 0
    assert np.isclose(float(spot.iloc[0]), float(source["first_session_close"]))
    out = pd.DataFrame({"date": dates, "taiex_close": spot.to_numpy(),
                        "strategy_pnl": strategy.pnl.to_numpy(), "tx_buy_hold_pnl": futures.pnl.to_numpy()})
    out["strategy_equity_per_initial_tx_notional"] = initial_tx_notional + out.strategy_pnl.cumsum()
    out["tx_buy_hold_equity_per_initial_tx_notional"] = initial_tx_notional + out.tx_buy_hold_pnl.cumsum()
    out["taiex_price_index_equity"] = initial_tx_notional * out.taiex_close / index_open
    assert np.isclose(out.strategy_equity_per_initial_tx_notional.iloc[-1]-initial_tx_notional, strategy.pnl.sum())
    assert np.isclose(out.tx_buy_hold_equity_per_initial_tx_notional.iloc[-1]-initial_tx_notional, futures.pnl.sum())
    assert (out[["strategy_equity_per_initial_tx_notional", "tx_buy_hold_equity_per_initial_tx_notional",
                 "taiex_price_index_equity"]] > 0).all().all()
    start, end = dates.iloc[0], dates.iloc[-1]
    years = ((end-start).days+1)/365.25
    results = []
    for label, column, tradable, cost in [
        ("V04一口／起始名目價值", "strategy_equity_per_initial_tx_notional", True, "含原始一口手續費、稅及滑價"),
        ("TX近月買進持有／起始名目價值", "tx_buy_hold_equity_per_initial_tx_notional", True, "含一口成交及轉倉成本"),
        ("加權股價指數價格報酬", "taiex_price_index_equity", False, "指數價格、未計股息與實際追蹤費用"),
    ]:
        equity = out[column]
        ret = equity.pct_change()
        ret.iloc[0] = equity.iloc[0]/initial_tx_notional-1
        prefix = {"strategy_equity_per_initial_tx_notional": "strategy",
                  "tx_buy_hold_equity_per_initial_tx_notional": "tx_buy_hold",
                  "taiex_price_index_equity": "taiex"}[column]
        out[prefix+"_return"] = ret
        peak = equity.cummax().clip(lower=initial_tx_notional)
        out[prefix+"_drawdown"] = equity/peak-1
        cumulative = float(equity.iloc[-1]/initial_tx_notional-1)
        mdd = float(-out[prefix+"_drawdown"].min())
        vol = float(ret.std(ddof=1)*np.sqrt(252))
        sharpe = float(ret.mean()/ret.std(ddof=1)*np.sqrt(252))
        results.append(dict(series=label, start=str(start.date()), end=str(end.date()), days=len(out),
                            reference_capital=initial_tx_notional, reference_definition="首日TX實際開盤價×200，固定作為三序列共同比較基數",
                            initial_taiex_open=index_open if prefix=="taiex" else np.nan,
                            final_equity=float(equity.iloc[-1]), net_pnl_equivalent=float(equity.iloc[-1]-initial_tx_notional),
                            cumulative_return=cumulative, CAGR=(1+cumulative)**(1/years)-1,
                            Sharpe=sharpe, annual_volatility=vol, MDD_pct=mdd,
                            MDD_amount=float((peak-equity).max()),
                            directly_tradable=tradable, cost_treatment=cost))
    active = out.strategy_return - out.taiex_return
    tracking_error = float(active.std(ddof=1)*np.sqrt(252))
    for result in results:
        result["tracking_error_vs_taiex"] = tracking_error if result["series"].startswith("V04") else np.nan
        result["information_ratio_vs_taiex"] = (float(active.mean()*252/tracking_error)
            if tracking_error > 0 and result["series"].startswith("V04") else np.nan)
    out.to_csv(OUT / "market_normalized_daily.csv", index=False, encoding="utf-8-sig")
    summary = pd.DataFrame(results)
    summary.to_csv(OUT / "market_normalized_summary.csv", index=False, encoding="utf-8-sig")
    return summary

if __name__ == "__main__":
    print(build()[["series", "cumulative_return", "CAGR", "Sharpe", "MDD_pct", "information_ratio_vs_taiex"]].to_string(index=False))
