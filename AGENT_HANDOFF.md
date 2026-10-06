# TX Flow Trend Backtest - Agent Handoff

## Current repository

- GitHub: https://github.com/ChiJiun/tx-flow-trend-backtest
- Branch: `main`
- Latest implementation commit before this handoff update: `1737172` (`ci: pin runner and update GitHub actions`); feature commit: `1b4d7ee`.
- Repository is public.
- GitHub issue #1 (CI regression) and #2 (volatility-matched benchmark) are closed. Issue #3 (log-y equity curve) remains open only because the tracked local PDF binary is locked by another Windows process and could not be refreshed; source code and CI both generate the updated PDF successfully.
- GitHub Actions workflow `Backtest regression` passed run `37527148941` on `ubuntu-24.04`, Python 3.12, `actions/checkout@v7`, and `actions/setup-python@v7`.

## Project purpose

Reproduce a Taiwan TX futures backtest using:

1. 20-day average institutional net-trade intensity > 0.
2. Current near-month close > 20-day near-month close average.
3. Signal generated after day t close and executed at day t+1 open.
4. Long one TX contract or flat. No shorting, pyramiding, stop loss, or intraday exit.
5. Both strategy and Buy-and-Hold benchmark roll on the same pre-expiry schedule.

## Verified baseline results

Formal period: 2018-08-31 to 2026-10-05, 1,968 trading days, initial capital NT$10,000,000, multiplier NT$200/point.

| Metric | Strategy | Buy-and-Hold benchmark |
|---|---:|---:|
| Cumulative return | 32.78% | 82.68% |
| CAGR | 3.56% | 7.72% |
| Sharpe | 1.302 | 1.108 |
| Calmar | 0.906 | 0.694 |
| MDD | 3.93% | 11.12% |
| Annual volatility | 2.82% | 7.20% |
| Strategy exposure | 658/1,968 days (33.4%) | Nearly full period |

The benchmark's 11.12% MDD is not by itself evidence of a code error. It has materially higher exposure and volatility than the strategy. For fair risk comparison, add a post-hoc volatility-matched benchmark, but retain fixed-one-contract results as the primary executable comparison.

Implemented volatility-matched diagnostic: scaling benchmark gross P&L and all transaction-cost components proportionally to `0.315010` TX-equivalent matches strategy annual volatility at `2.8187%`. Diagnostic CAGR is `2.8995%`, MDD `4.2541%`, Sharpe `1.0657`, and Calmar `0.6816`. This is explicitly labeled full-sample post-hoc and not directly tradable.

## Important implementation notes

- `backtest.py` still contains hard-coded baseline assertions (`net_pnl` and `Sharpe`). They now coexist with `ci_verify.py`; a future cleanup should move expected values into a named/versioned regression fixture so parameter/data changes fail with a clearer expected-update path.
- `backtest.py` now generates `volatility_matched_benchmark_summary.csv`, `volatility_matched_benchmark_daily.csv`, and regenerates `final_verification.json` each run.
- `make_report.py` now preserves the linear equity chart, adds `equity_comparison_log.png`, validates that log-y equity inputs are non-empty/finite/strictly positive, and includes the log-y chart in DOCX/XLSX/PDF builds.
- The report keeps fixed-one-contract Buy-and-Hold as the primary comparison and presents the volatility-matched result in a clearly separate diagnostic section.
- `backtest.py` rebuilds the base workbook; `make_report.py` then adds report-only sheets/images. Final workbook has 18 sheets.

## GitHub scan findings and proposed issues

### Priority 1 - reproducibility and correctness

1. **Add CI regression workflow for the backtest and report build**
   - Run `python backtest.py` and `python make_report.py` on a pinned Python version.
   - Verify expected output files, ZIP integrity, and key reconciliation checks.
   - Keep generated artifacts out of the CI diff unless intentionally refreshed.

2. **Replace hard-coded metric assertions with parameterized regression controls**
   - Move expected values to a versioned fixture or a clearly named regression file.
   - Make parameter/data changes produce an explicit expected-update message instead of a generic assertion failure.

3. **Add fair risk-matched benchmark diagnostics**
   - Keep fixed-one-contract benchmark as the primary executable comparison.
   - Add a separate volatility-matched benchmark with transparent scaling, cost treatment, and a warning that full-sample matching is post-hoc.

### Priority 2 - usability and research quality

4. **Add logarithmic-y equity curve and clarify chart units**
   - Preserve the linear chart.
   - Add a separate log-y image and include it in the workbook/report with an explicit title and unit label.

5. **Add an untouched out-of-sample evaluation path**
   - Freeze the selected rule and evaluate a genuinely unused period.
   - Keep exploratory candidates and selection diagnostics separate from the out-of-sample result.

6. **Add data versioning and source-refresh checks**
   - Record source URLs, retrieval dates, input hashes, and schema checks in a machine-readable manifest.
   - Fail early when required columns or date coverage change.

### Priority 3 - repository hygiene

7. **Add `SECURITY.md` and clarify the repository license**
   - GitHub reports no security policy.
   - The repository contains a font license, but no clear project-level software/data license was found in the tracked file list. Decide whether the code, derived outputs, and source data have different terms.

8. **Document generated-artifact policy**
   - State whether PDFs, DOCX, XLSX, PNGs, and large raw source files are canonical tracked outputs or release artifacts.
   - Consider Git LFS or release assets for large binaries if repository size becomes a concern.

## Recommended order for the next agent

1. Close any application holding `TX_flow_trend_report.pdf`, rerun `python make_report.py`, verify the canonical tracked PDF changed, commit/push that binary refresh, then close GitHub issue #3.
2. Replace hard-coded baseline assertions with a named/versioned regression fixture while preserving current accounting checks and `ci_verify.py`.
3. Add an untouched out-of-sample evaluation path without reusing exploratory periods for selection.
4. Add data/source manifest checks, then address `SECURITY.md`, licensing, and generated-artifact policy.

## Validation already run

Validation completed in an isolated copy because the working-directory PDF was locked: `backtest.py` → `make_report.py` → `ci_verify.py` all passed, `pdfinfo` reported 8 pages, and the workbook contained 18 sheets. GitHub Actions independently repeated the full pipeline successfully on Python 3.12. The working-directory DOCX/XLSX/PNG/CSV outputs were refreshed from the validated isolated build; only the tracked canonical PDF binary remains stale until its Windows file lock is released.
