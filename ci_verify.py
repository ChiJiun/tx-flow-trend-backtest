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
    OUT / "volatility_matched_benchmark_summary.csv",
    OUT / "volatility_matched_benchmark_daily.csv",
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
expected_sheets = {"波動配平基準_摘要", "波動配平基準_逐日", "資金回撤疊圖"}
assert len(wb.sheetnames) == 18, f"unexpected workbook sheet count: {len(wb.sheetnames)}"
assert expected_sheets.issubset(wb.sheetnames), f"missing workbook sheets: {expected_sheets - set(wb.sheetnames)}"

doc = Document(BASE / "TX_flow_trend_report.docx")
doc_text = "\n".join(p.text for p in doc.paragraphs)
assert "事後波動配平診斷（不可直接交易）" in doc_text, "DOCX missing volatility-matched diagnostic"

assert (BASE / "TX_flow_trend_report.pdf").read_bytes()[:5] == b"%PDF-", "report PDF signature invalid"
for path in [OUT / "equity_comparison.png", OUT / "equity_comparison_log.png", OUT / "underwater_comparison.png"]:
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"PNG signature invalid: {path.name}"

validation = json.loads((OUT / "validation.json").read_text(encoding="utf-8"))
final = json.loads((OUT / "final_verification.json").read_text(encoding="utf-8"))
assert validation["all_strategy_and_benchmark_pnl_reconciled"] is True
assert validation["signal_dates_before_execution"] is True
assert final["strategy"]["days"] == final["benchmark"]["days"] == 1968

metrics = pd.read_csv(OUT / "metrics_comparison.csv")
vm = pd.read_csv(OUT / "volatility_matched_benchmark_summary.csv").iloc[0]
strategy = metrics.iloc[0]
benchmark = metrics.iloc[1]
assert np.isclose(strategy["net_pnl"], 3277536.576, atol=1e-6)
assert np.isclose(strategy["Sharpe"], 1.3020005980912697, atol=1e-12)
assert np.isclose(benchmark["net_pnl"], 8268352.664, atol=1e-6)
assert np.isclose(vm["annual_volatility"], strategy["annual_volatility"], atol=1e-12, rtol=0)
assert 0 < vm["position_equivalent"] < 1
assert bool(vm["directly_tradable"]) is False

print(
    "CI verification passed:",
    f"strategy Sharpe={strategy['Sharpe']:.6f},",
    f"vol-match scale={vm['position_equivalent']:.6f}",
)
