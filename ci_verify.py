"""CI checks for reproducible backtest/report outputs."""
from pathlib import Path
import json
import zipfile
import pandas as pd
import numpy as np
from openpyxl import load_workbook
from docx import Document
from regression_baseline import verify_regression_baseline

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"

required = [
    BASE / "TX_flow_trend_workbook.xlsx",
    BASE / "TX_flow_trend_report.docx",
    BASE / "TX_flow_trend_report.pdf",
    OUT / "validation.json",
    OUT / "final_verification.json",
    OUT / "metrics_comparison.csv",
    OUT / "one_contract_risk_matched_summary.csv",
    OUT / "one_contract_risk_matched_daily.csv",
    OUT / "one_contract_risk_matched_distribution.csv",
    OUT / "equity_comparison.png",
    OUT / "equity_comparison_log.png",
    OUT / "underwater_comparison.png",
]
missing = [str(p.relative_to(BASE)) for p in required if not p.is_file() or p.stat().st_size == 0]
assert not missing, f"missing or empty required outputs: {missing}"

for path in [BASE / "TX_flow_trend_workbook.xlsx", BASE / "TX_flow_trend_report.docx"]:
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None, f"corrupt ZIP container: {path.name}"

wb = load_workbook(BASE / "TX_flow_trend_workbook.xlsx", read_only=True)
expected_sheets = {"一口風險配平_摘要", "一口風險配平_逐日", "一口風險配平_位移分布", "資金回撤疊圖"}
assert len(wb.sheetnames) == 23, f"unexpected workbook sheet count: {len(wb.sheetnames)}"
assert {"法人濾網增量歸因", "價格單獨波動配平", "同曝險大盤比較摘要", "同曝險大盤比較逐日"}.issubset(wb.sheetnames)
assert expected_sheets.issubset(wb.sheetnames), f"missing workbook sheets: {expected_sheets - set(wb.sheetnames)}"

doc = Document(BASE / "TX_flow_trend_report.docx")
doc_text = "\n".join(p.text for p in doc.paragraphs)
assert "一口等曝險風險診斷" in doc_text, "DOCX missing one-contract risk-matched diagnostic"

assert (BASE / "TX_flow_trend_report.pdf").read_bytes()[:5] == b"%PDF-", "report PDF signature invalid"
for path in [OUT / "equity_comparison.png", OUT / "equity_comparison_log.png", OUT / "underwater_comparison.png"]:
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"PNG signature invalid: {path.name}"

validation = json.loads((OUT / "validation.json").read_text(encoding="utf-8"))
final = json.loads((OUT / "final_verification.json").read_text(encoding="utf-8"))
assert validation["all_strategy_and_benchmark_pnl_reconciled"] is True
assert validation["signal_dates_before_execution"] is True
assert final["strategy"]["days"] == final["benchmark"]["days"] == validation["days"]

metrics = pd.read_csv(OUT / "metrics_comparison.csv")
risk = pd.read_csv(OUT / "one_contract_risk_matched_summary.csv").iloc[0]
strategy = metrics.iloc[0]
benchmark = metrics.iloc[1]
assert np.isclose(strategy["net_pnl"], 3277536.576, atol=1e-6)
assert np.isclose(strategy["Sharpe"], 1.3674407230136694, atol=1e-12, rtol=0)
assert np.isclose(benchmark["net_pnl"], 8268352.664, atol=1e-6)
assert np.isclose(validation["parameters"]["capital"], 2195000.0, atol=1e-6)
assert int(risk["position_contracts"]) == 1
assert bool(risk["integer_contracts_only"]) is True
assert int(risk["exposure_days"]) == int(strategy["exposure_days"]) == 658
assert int(risk["trades"]) == int(strategy["trades"]) == 147
assert risk["annual_volatility"] >= strategy["annual_volatility"]
assert bool(risk["directly_tradable"]) is False
verify_regression_baseline({
    "period": validation["period"],
    "parameters": validation["parameters"],
    "input_sha256": validation["input_sha256"],
    "metrics": {
        "strategy.days": int(final["strategy"]["days"]),
        "strategy.net_pnl": float(strategy["net_pnl"]),
        "strategy.Sharpe": float(strategy["Sharpe"]),
        "benchmark.days": int(final["benchmark"]["days"]),
        "benchmark.net_pnl": float(benchmark["net_pnl"]),
    },
})
assert np.isclose(final["strategy"]["net_pnl"], strategy["net_pnl"], atol=1e-6, rtol=0)
assert np.isclose(final["benchmark"]["net_pnl"], benchmark["net_pnl"], atol=1e-6, rtol=0)
assert f"策略{int(strategy['trades'])}筆完整方向交易" in doc_text, "DOCX trade count differs from CSV"
source = json.loads((OUT / 'institutional_source_audit.json').read_text(encoding='utf-8'))
roll = json.loads((OUT / 'roll_gap_summary.json').read_text(encoding='utf-8'))
assert source['differing_rows'] == 2 and source['changed_signal_days'] == 0
assert roll['changed_signal_days'] == 14
assert f"{roll['changed_signal_days']}天訊號不同" in doc_text
assert np.isclose(pd.read_csv(OUT / 'flow_incremental_attribution.csv').net_difference.sum(),
                  strategy.net_pnl - pd.read_csv(OUT / 'ablation.csv').set_index('code').loc['price_only', 'net_pnl'], atol=1e-6)
ablation = pd.read_csv(OUT / "ablation.csv").set_index("code")
assert ablation.loc["flow_only", "rule"] == "交易強度MA20>0；隔日開盤多單/空手"
assert ablation.loc["price_only", "rule"] == "近月收盤>價格MA20；隔日開盤多單/空手"
market = pd.read_csv(OUT / 'market_normalized_summary.csv')
assert len(market) == 3
assert market.reference_capital.nunique() == 1
assert np.isclose(market.loc[0, 'MDD_pct'], strategy['MDD_pct'])
assert market.loc[0, 'cumulative_return'] < market.loc[2, 'cumulative_return']
assert np.isclose(market.loc[0, 'net_pnl_equivalent'], strategy['net_pnl'], atol=1e-6)
assert np.isclose(market.loc[1, 'net_pnl_equivalent'], benchmark['net_pnl'], atol=1e-6)

print(
    "CI verification passed:",
    f"strategy Sharpe={strategy['Sharpe']:.6f},",
    f"one-contract matched shift={int(risk['selected_shift_trading_days'])}",
)
