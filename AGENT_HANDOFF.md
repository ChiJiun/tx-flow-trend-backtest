# TX Flow Trend Backtest - Agent Handoff

## Current repository

- GitHub: https://github.com/ChiJiun/tx-flow-trend-backtest
- Branch: `main`
- Current commit: `d6f999b` (`Initial commit: TX flow trend backtest`)
- Working tree was clean before this handoff update.
- Repository is public. GitHub currently shows 0 open issues, 0 pull requests, no workflow runs, and no `SECURITY.md`.

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

Previous analytical estimate: scaling benchmark P&L to approximately 0.315 TX-equivalent produces annual volatility near 2.82%, CAGR about 2.90%, MDD about 4.25%, and Sharpe about 1.066. This is a diagnostic fractional exposure, not a directly tradable integer TX position; transaction costs must be redefined for any smaller-contract implementation.

## Important implementation notes

- `backtest.py` contains hard-coded baseline assertions at the end (`net_pnl` and `Sharpe`). They protect the current dataset but intentionally fail after changing parameters or data. Replace with parameterized expected values or a separate regression test before making the workflow reusable.
- `make_report.py` currently generates linear equity and underwater charts only. It embeds `equity_comparison.png` and `underwater_comparison.png` into the workbook and report.
- The requested next visual change is an additional `equity_comparison_log.png` with a logarithmic y-axis. Preserve the existing linear chart.
- `make_report.py` currently states and reports only fixed-one-contract results. If a volatility-matched benchmark is added, label it as a diagnostic comparison and do not mix it into the primary fixed-one-contract table without a clear separate section.
- `backtest.py` rebuilds the base workbook; `make_report.py` then adds the report-only sheets, images, and Chinese field dictionary.

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

1. Implement the log-y chart and volatility-matched diagnostic in source code.
2. Regenerate outputs and run visual QA for the PNG, XLSX, DOCX, and PDF.
3. Add regression/CI scaffolding without weakening current accounting assertions.
4. Commit and push with a focused message; then open the selected GitHub issues using the issue text above.

## Validation already run

Bundled Python successfully ran `backtest.py` and reproduced the baseline metrics above. No working-tree changes existed before adding this handoff document.
