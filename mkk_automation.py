"""
mkk_automation.py — MKK Institutional Trading System
Entry point for GitHub Actions automated paper trading.

Usage:
  python mkk_automation.py --mode DAILY       # default: exits + scan + entries + email
  python mkk_automation.py --mode SCAN_ONLY   # scan only, no trade entry
  python mkk_automation.py --mode EXIT_ONLY   # process exits only
  python mkk_automation.py --mode BACKTEST    # bulk walk-forward backtest
  python mkk_automation.py --mode REPORT      # performance report + email
  python mkk_automation.py --db path/to.db    # override DB path

Architecture (4-module split):
  mkk_core.py     — Config, DB, Taxonomy, Indicators, Regime, Risk, TC
  mkk_scanner.py  — EliteSwingScanner, SectorHeatmap, BulkBacktest
  mkk_paper.py    — PaperTradingEngine (exits + entries, swing protocol)
  mkk_runner.py   — Orchestrator, email, CLI argument handling

GitHub Actions:
  .github/workflows/daily_run.yml
  Runs Mon–Fri at 09:20 AM IST (03:30 UTC).
  DB committed back to repo after each successful run.
  Email sent via Gmail SMTP (secrets: EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT).
"""

from mkk_runner import main

if __name__ == '__main__':
    main()
