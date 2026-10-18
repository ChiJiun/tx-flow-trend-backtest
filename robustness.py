"""統計推論與穩健性輔助：區塊 bootstrap、訊號分位報酬、月報酬、尾端風險與參數格點摘要。

這些函數只讀取既有的逐日底稿與指標特徵；參數格點與替代設定的實際回測仍由 backtest.py 以同一套
run()/benchmark() 執行，確保成本、轉倉與帳務口徑完全一致。
"""
import numpy as np
import pandas as pd


def extra_risk_metrics(daily_return):
    """Sortino（rf=0、252日）、歷史法日 VaR95 與 ES95（正值代表損失比例）。"""
    r = pd.Series(daily_return).astype(float).dropna()
    downside = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
    var95 = -float(r.quantile(0.05))
    tail = r[r <= r.quantile(0.05)]
    return dict(Sortino=float(r.mean() / downside * np.sqrt(252)) if downside > 0 else np.nan,
                daily_VaR95=var95, daily_ES95=-float(tail.mean()) if len(tail) else np.nan,
                skew=float(r.skew()), excess_kurtosis=float(r.kurt()))


def circular_block_bootstrap(returns, n_boot=5000, block=20, seed=20181231):
    """固定長度循環區塊 bootstrap，保留日報酬的短期相依；回傳 Sharpe 與年化平均報酬的抽樣分布。"""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_boot, -1)[:, :n] % n
    samples = r[idx]
    mean = samples.mean(axis=1)
    std = samples.std(axis=1, ddof=1)
    sharpe = mean / std * np.sqrt(252)
    return dict(sharpe=sharpe, annual_mean=mean * 252)


def bootstrap_summary(label, returns, n_boot=5000, block=20, seed=20181231):
    r = np.asarray(returns, dtype=float)
    point = r.mean() / r.std(ddof=1) * np.sqrt(252)
    boot = circular_block_bootstrap(r, n_boot, block, seed)
    lo, hi = np.percentile(boot["sharpe"], [2.5, 97.5])
    mlo, mhi = np.percentile(boot["annual_mean"], [2.5, 97.5])
    t_stat = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    return dict(series=label, days=len(r), Sharpe=float(point), Sharpe_ci_low=float(lo), Sharpe_ci_high=float(hi),
                prob_Sharpe_le_0=float((boot["sharpe"] <= 0).mean()),
                annual_mean_return=float(r.mean() * 252), annual_mean_ci_low=float(mlo), annual_mean_ci_high=float(mhi),
                t_stat_mean_daily_return=float(t_stat), n_boot=n_boot, block_length=block,
                method="circular block bootstrap of daily net returns; rf=0; not adjusted for prior candidate selection")


def signal_return_table(x, p, lookup, main_dates):
    """訊號日 t 的特徵對應同契約 t→t+1 收盤報酬（bp）：Q20 五分位與「趨勢×法人」2×2 條件表。"""
    pp = p.set_index("date")
    dates = list(pp.index)
    nxt = {}
    for i, d in enumerate(dates[:-1]):
        con = pp.contract.iloc[i]
        key = (dates[i + 1], con)
        nxt[d] = float(lookup.loc[key, "close"]) / float(pp.close.iloc[i]) - 1 if key in lookup.index else np.nan
    # 訊號日為正式期間每個執行日的前一交易日；特徵與次日報酬皆以訊號日對齊。
    signal_dates = [dates[dates.index(d) - 1] for d in main_dates]
    f = x.loc[signal_dates, ["intensity_ma20", "close", "price_ma20"]].copy()
    f["next_day_return"] = [nxt.get(d, np.nan) for d in f.index]
    f = f.dropna()
    f["trend"] = f.close > f.price_ma20
    f["flow"] = f.intensity_ma20 > 0
    f["q20_quintile"] = pd.qcut(f.intensity_ma20.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)

    def row(label, group):
        r = group.next_day_return
        return dict(group=label, days=len(r), mean_next_day_return_bp=float(r.mean() * 1e4),
                    median_next_day_return_bp=float(r.median() * 1e4), hit_rate=float((r > 0).mean()),
                    t_stat=float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 else np.nan,
                    mean_Q20=float(group.intensity_ma20.mean()))

    rows = [row(f"Q20 第{q}分位（{'最低' if q == 1 else '最高' if q == 5 else '中間'}）", g) for q, g in f.groupby("q20_quintile")]
    for trend in (True, False):
        for flow in (True, False):
            g = f[(f.trend == trend) & (f.flow == flow)]
            rows.append(row(f"{'收盤>MA20' if trend else '收盤≤MA20'} 且 {'Q20>0' if flow else 'Q20≤0'}", g))
    rows.append(row("全部訊號日", f))
    # 在趨勢成立的日子裡，Q20>0 與 Q20≤0 的次日平均報酬差異（Welch t）。
    a = f[f.trend & f.flow].next_day_return
    b = f[f.trend & ~f.flow].next_day_return
    welch = (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    table = pd.DataFrame(rows)
    table.attrs["welch_t_flow_given_trend"] = float(welch)
    table.attrs["flow_increment_given_trend_bp"] = float((a.mean() - b.mean()) * 1e4)
    return table


def monthly_returns(strategy_daily, benchmark_daily, capital):
    out = []
    for label, d in [("strategy", strategy_daily), ("benchmark", benchmark_daily)]:
        d = d.copy()
        d["month"] = d.date.dt.to_period("M").astype(str)
        for month, g in d.groupby("month"):
            start_equity = g.equity.iloc[0] - g.pnl.iloc[0]
            out.append(dict(series=label, month=month, net_pnl=float(g.pnl.sum()),
                            monthly_return=float(g.equity.iloc[-1] / start_equity - 1),
                            exposure_days=int((g.position_after != 0).sum()) if "position_after" in g else len(g)))
    return pd.DataFrame(out)


def grid_summary(grid, base_intensity=20, base_price=20):
    """參數格點的穩定性摘要：鄰域中位數、前後期 Sharpe 的秩相關、前期最佳參數在後期的表現。"""
    base = grid[(grid.intensity_window == base_intensity) & (grid.price_window == base_price)].iloc[0]
    rank_corr = float(grid[["Sharpe_first_half", "Sharpe_second_half"]].corr(method="spearman").iloc[0, 1])
    best_first = grid.loc[grid.Sharpe_first_half.idxmax()]
    neighbours = grid[(grid.intensity_window.between(15, 30)) & (grid.price_window.between(15, 30))]
    return dict(base_Sharpe=float(base.Sharpe), base_rank_by_Sharpe=int((grid.Sharpe > base.Sharpe).sum() + 1),
                grid_size=len(grid), grid_Sharpe_median=float(grid.Sharpe.median()), grid_Sharpe_min=float(grid.Sharpe.min()),
                grid_Sharpe_max=float(grid.Sharpe.max()), share_Sharpe_above_1=float((grid.Sharpe > 1).mean()),
                share_positive_net_pnl=float((grid.net_pnl > 0).mean()),
                neighbourhood_15_30_Sharpe_median=float(neighbours.Sharpe.median()), neighbourhood_15_30_Sharpe_min=float(neighbours.Sharpe.min()),
                spearman_first_vs_second_half=rank_corr,
                best_first_half_params=f"{int(best_first.intensity_window)}/{int(best_first.price_window)}",
                best_first_half_Sharpe_second_half=float(best_first.Sharpe_second_half),
                base_Sharpe_first_half=float(base.Sharpe_first_half), base_Sharpe_second_half=float(base.Sharpe_second_half),
                note="full-sample grid is descriptive; the 20/20 rule was chosen before this grid but after comparing 18 candidates")
