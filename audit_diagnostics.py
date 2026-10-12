"""Reproducible source, roll-gap, and price-filter sensitivity diagnostics."""
import json
import numpy as np
import pandas as pd

def diagnostics(base, out, p, lookup, raw, x, main_dates, strategy_daily, price_only_daily, run, template, metrics, volatility_matched_benchmark):
    # Compare overlapping institutional rows against the archived raw provider response.
    provider = pd.DataFrame(json.loads((base / "source_audits/FinMind_raw_response.json").read_text(encoding="utf-8"))["data"])
    provider["身份別"] = provider.institutional_investors.replace({"外資": "外資及陸資"})
    provider["date"] = pd.to_datetime(provider.date)
    official = raw[["date", "身份別", "多方交易口數", "空方交易口數", "多空交易口數淨額"]].copy()
    merged = official.merge(provider[["date", "身份別", "long_deal_volume", "short_deal_volume"]],
                            on=["date", "身份別"], how="left", validate="one_to_one")
    assert merged[["long_deal_volume", "short_deal_volume"]].notna().all().all()
    diff = merged[(merged["多方交易口數"] != merged.long_deal_volume) |
                  (merged["空方交易口數"] != merged.short_deal_volume)].copy()
    diff["provider_net"] = diff.long_deal_volume - diff.short_deal_volume
    diff.to_csv(out / "institutional_source_differences.csv", index=False, encoding="utf-8-sig")
    alternate = merged.copy()
    alternate["buy"] = alternate.long_deal_volume
    alternate["sell"] = alternate.short_deal_volume
    totals = alternate.groupby("date")[["buy", "sell"]].sum()
    q = (totals.buy - totals.sell) / (totals.buy + totals.sell)
    q20 = q.reindex(x.index).rolling(20, min_periods=20).mean()
    alternate_signal = (q20 > 0) & (x.close > x.price_ma20)
    signal_diff = x.buy_condition.ne(alternate_signal) & x.intensity_ma20.notna()
    impact = x.loc[signal_diff, ["close", "price_ma20", "trade_intensity", "intensity_ma20"]].copy()
    impact["provider_intensity_ma20"] = q20.loc[signal_diff]
    impact["execution_date"] = [x.index[x.index.get_loc(d) + 1] if x.index.get_loc(d) + 1 < len(x) else pd.NaT for d in impact.index]
    impact.to_csv(out / "institutional_signal_changes.csv", index_label="signal_date", encoding="utf-8-sig")
    provider_summary = dict(compared_rows=len(merged), differing_rows=len(diff),
        differing_dates=sorted(str(d.date()) for d in diff.date.unique()),
        affected_ma20_days=int(((q20-x.intensity_ma20).abs()>1e-14).sum()),
        changed_signal_days=int(signal_diff.sum()),
        changed_execution_targets=int(signal_diff.shift(1, fill_value=False).reindex(main_dates).sum()),
        source_availability="Regular-session volume is generally published after close; exact historical first-release snapshots/revisions are unavailable.",
        point_in_time_verified=False)
    (out / "institutional_source_audit.json").write_text(json.dumps(provider_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Back-adjust using only the prior session's overlap closes at each contract switch.
    adj = p[["date", "contract", "close"]].copy()
    offsets = []
    cumulative = 0.
    gaps = []
    for i, row in enumerate(adj.itertuples(index=False)):
        gap = 0.
        if i and row.contract != adj.contract.iloc[i-1]:
            yesterday = adj.iloc[i-1]
            new_previous = float(lookup.loc[(yesterday.date, row.contract), "close"])
            assert np.isfinite(new_previous)
            gap = new_previous - float(yesterday.close)
            cumulative += gap
        offsets.append(cumulative)
        gaps.append(gap)
    adj["roll_gap_points"] = gaps
    adj["cumulative_offset"] = offsets
    adj["adjusted_close"] = adj.close - adj.cumulative_offset
    adj = adj.set_index("date")
    adj["raw_ma20"] = adj.close.rolling(20, min_periods=20).mean()
    adj["adjusted_ma20"] = adj.adjusted_close.rolling(20, min_periods=20).mean()
    adj["raw_target"] = ((x.intensity_ma20 > 0) & (adj.close > adj.raw_ma20)).astype(int)
    adj["adjusted_target"] = ((x.intensity_ma20 > 0) & (adj.adjusted_close > adj.adjusted_ma20)).astype(int)
    adj["changed_target"] = adj.raw_target != adj.adjusted_target
    adj.loc[main_dates].reset_index().to_csv(out / "roll_gap_signal_audit.csv", index=False, encoding="utf-8-sig")
    target = adj.adjusted_target.shift(1).reindex(main_dates)
    alt_metrics, _ = run(dict(template, code="roll_adjusted_diagnostic", group="換月敏感度",
                              name="前日重疊價差調整訊號", rule="昨日可知換月價差回溯調整MA20；隔日開盤多單/空手",
                              target=target))
    roll_summary = dict(roll_switches=int((adj.roll_gap_points != 0).sum()),
        changed_signal_days=int(adj.loc[main_dates, "changed_target"].sum()),
        raw_net_pnl=float(metrics["net_pnl"]), adjusted_net_pnl=float(alt_metrics["net_pnl"]),
        raw_trades=int(metrics["trades"]), adjusted_trades=int(alt_metrics["trades"]),
        raw_Sharpe=float(metrics["Sharpe"]), adjusted_Sharpe=float(alt_metrics["Sharpe"]),
        diagnostic_only=True, point_in_time_gap="New contract's previous close; known before switch day's signal.")
    (out / "roll_gap_summary.json").write_text(json.dumps(roll_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preserve exact cost/P&L reconciliation and separate excluded price-only days.
    strat = strategy_daily.set_index("date")
    price = price_only_daily.set_index("date")
    assert strat.index.equals(price.index)
    classes = np.select([(strat.target == 1) & (price.target == 1),
                         (strat.target == 0) & (price.target == 1)],
                        ["both_long", "price_only_rejected_by_flow"], default="both_flat")
    rows = []
    for label in ["both_long", "price_only_rejected_by_flow", "both_flat"]:
        mask = classes == label
        rows.append(dict(execution_target_state=label, days=int(mask.sum()),
                         strategy_gross_pnl=float(strat.loc[mask, "gross_pnl"].sum()),
                         price_only_gross_pnl=float(price.loc[mask, "gross_pnl"].sum()),
                         strategy_cost=float(strat.loc[mask, "cost"].sum()),
                         price_only_cost=float(price.loc[mask, "cost"].sum()),
                         strategy_net_pnl=float(strat.loc[mask, "pnl"].sum()),
                         price_only_net_pnl=float(price.loc[mask, "pnl"].sum()),
                         net_difference=float((strat.loc[mask, "pnl"]-price.loc[mask, "pnl"]).sum())))
    decomposition = pd.DataFrame(rows)
    assert np.isclose(decomposition.net_difference.sum(), strat.pnl.sum()-price.pnl.sum(), atol=1e-6)
    decomposition.to_csv(out / "flow_incremental_attribution.csv", index=False, encoding="utf-8-sig")
    matched_daily, matched = volatility_matched_benchmark(price.reset_index(), metrics["annual_volatility"])
    matched["series"] = "價格單獨策略：事後波動配平"
    pd.DataFrame([matched]).to_csv(out / "price_only_volatility_matched_summary.csv", index=False, encoding="utf-8-sig")
    matched_daily.to_csv(out / "price_only_volatility_matched_daily.csv", index=False, encoding="utf-8-sig")
    return provider_summary, roll_summary, decomposition, matched
