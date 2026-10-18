"""特殊期間（急跌／跳空事件）下的訊號狀態與損益：事後描述，不用於調整策略。

事件視窗以公開重大事件的日曆日為起點，再以實際交易日曆截取；另列兩段由資料本身辨識
（樣本內單日開盤跳空最深）的期間，並在名稱中標示「資料辨識」。所有視窗只讀取既有的
策略與基準逐日底稿，沒有任何參數或規則因此改動。
"""
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"

# (名稱, 起日, 迄日)；起迄為日曆日，實際交易日由行情日曆決定。
EVENTS = [
    ("2018Q4 美股修正急跌", "2018-10-01", "2018-12-31"),
    ("2020Q1 COVID-19股災", "2020-02-20", "2020-03-31"),
    ("2021-05 本土疫情修正", "2021-05-10", "2021-05-31"),
    ("2022 升息空頭（全年）", "2022-01-03", "2022-12-30"),
    ("2024-08 全球急跌", "2024-08-01", "2024-08-09"),
    ("2025-04 美國關稅衝擊", "2025-04-01", "2025-04-30"),
    ("2026-03 跳空（資料辨識）", "2026-03-02", "2026-03-31"),
    ("2026-06 跳空（資料辨識）", "2026-06-01", "2026-06-30"),
]


def build(strategy_daily, benchmark_daily, prices, lookup):
    """回傳每個事件視窗的描述統計，並寫出 output/event_windows.csv。"""
    s = strategy_daily.set_index("date")
    b = benchmark_daily.set_index("date")
    assert s.index.equals(b.index)
    p = prices.set_index("date")
    # 同一契約的開盤相對前一交易日收盤的跳空；若前一日近月契約不同，改用該契約前一日收盤。
    gaps = []
    dates = list(p.index)
    for i, d in enumerate(dates):
        if i == 0:
            gaps.append(np.nan)
            continue
        con = p.contract.iloc[i]
        prev_date = dates[i - 1]
        prev_close = float(lookup.loc[(prev_date, con), "close"]) if (prev_date, con) in lookup.index else np.nan
        gaps.append(float(p.open.iloc[i]) / prev_close - 1 if np.isfinite(prev_close) and prev_close > 0 else np.nan)
    gap = pd.Series(gaps, index=p.index, name="open_gap_pct").reindex(s.index)
    assert gap.notna().all()
    rows = []
    for name, start, end in EVENTS:
        mask = (s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))
        if not mask.any():
            continue
        sw, bw, gw = s[mask], b[mask], gap[mask]
        worst = gw.idxmin()
        # 最深跳空日之後策略第一次重新進場的日期，以及從跳空日收盤到該進場開盤的近月價格變動（錯過的反彈幅度）。
        after = s[(s.index > worst) & (s.position_before == 0) & (s.position_after == 1)]
        reentry = after.index[0] if len(after) else pd.NaT
        reentry_open = float(lookup.loc[(reentry, p.contract.loc[reentry]), "open"]) if len(after) else np.nan
        rows.append(dict(
            event=name, window_start=str(sw.index[0].date()), window_end=str(sw.index[-1].date()),
            trading_days=int(mask.sum()),
            position_at_window_start=int(sw.position_before.iloc[0]),
            strategy_exposure_days=int((sw.position_after != 0).sum()),
            strategy_entries=int(((sw.position_before == 0) & (sw.position_after == 1)).sum()),
            strategy_exits=int(((sw.position_before == 1) & (sw.position_after == 0)).sum()),
            strategy_net_pnl=float(sw.pnl.sum()),
            strategy_worst_day_pnl=float(sw.pnl.min()),
            benchmark_net_pnl=float(bw.pnl.sum()),
            worst_open_gap_pct=float(gw.min()),
            worst_open_gap_date=str(worst.date()),
            held_on_worst_gap_day=int(sw.loc[worst, "position_before"]),
            near_month_close_change_pct=float(p.close.loc[sw.index[-1]] / p.close.loc[sw.index[0]] - 1),
            first_reentry_after_worst_gap=str(reentry.date()) if len(after) else "",
            trading_days_to_reentry=int(s.index.get_loc(reentry) - s.index.get_loc(worst)) if len(after) else np.nan,
            near_month_move_gap_close_to_reentry_open_pct=float(reentry_open / p.close.loc[worst] - 1) if len(after) else np.nan,
        ))
    table = pd.DataFrame(rows)
    assert len(table) == len(EVENTS)
    table.to_csv(OUT / "event_windows.csv", index=False, encoding="utf-8-sig")
    return table


if __name__ == "__main__":
    strategy = pd.read_csv(OUT / "strategy_daily.csv", parse_dates=["date"])
    benchmark = pd.read_csv(OUT / "benchmark_daily.csv", parse_dates=["date"])
    prices = pd.read_csv(BASE / "input/prices.csv", parse_dates=["date"])
    contracts = pd.read_csv(BASE / "input/all_contracts.csv", parse_dates=["date"]).set_index(["date", "contract"])
    print(build(strategy, benchmark, prices, contracts).to_string(index=False))
