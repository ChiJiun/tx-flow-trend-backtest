"""CI checks for reproducible backtest/report outputs."""
from pathlib import Path
import json
import zipfile
import pandas as pd
import numpy as np
from openpyxl import load_workbook
from docx import Document

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
assert len(wb.sheetnames) == 19, f"unexpected workbook sheet count: {len(wb.sheetnames)}"
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
assert final["strategy"]["days"] == final["benchmark"]["days"] == 1968

metrics = pd.read_csv(OUT / "metrics_comparison.csv")
risk = pd.read_csv(OUT / "one_contract_risk_matched_summary.csv").iloc[0]
strategy = metrics.iloc[0]
benchmark = metrics.iloc[1]
assert np.isclose(strategy["net_pnl"], 3277536.576, atol=1e-6)
assert np.isclose(strategy["Sharpe"], 1.3674407230136694, atol=1e-12, rtol=0)
assert np.isclose(benchmark["net_pnl"], 8268352.664, atol=1e-6)
assert np.isclose(validation["parameters"]["reference_capital"], 2195000.0, atol=1e-6)
assert int(risk["position_contracts"]) == 1
assert bool(risk["integer_contracts_only"]) is True
assert int(risk["exposure_days"]) == int(strategy["exposure_days"]) == 658
assert int(risk["trades"]) == int(strategy["trades"]) == 147
assert risk["annual_volatility"] >= strategy["annual_volatility"]
assert bool(risk["directly_tradable"]) is False

print(
    "CI verification passed:",
    f"strategy Sharpe={strategy['Sharpe']:.6f},",
    f"one-contract matched shift={int(risk['selected_shift_trading_days'])}",
)
