# MKK Institutional Trading System
### Automated Paper Trading | NSE Cash Equities | GitHub Actions

> **Educational use only. Not financial advice. Paper trading only.**

---

## What This Does

Runs a fully automated swing trading system on NSE-listed equities:

- **Daily at 9:20 AM IST** (Mon–Fri) via GitHub Actions — no manual intervention
- **Scans 2,200+ NSE stocks** through a 9-stage filter funnel
- **Ranks elite setups** by a 7-factor Priority Score (RS, VCP, sector, R:R, etc.)
- **Enters paper trades** at next-day open with full position sizing and risk rules
- **Exits** based on previous day's OHLC: stop-loss, T1/T2/T3 targets, or time exit
- **Emails you a daily summary** with entries, exits, open positions, and portfolio snapshot
- **Persists everything** in a SQLite DB committed back to your GitHub repo

---

## Architecture

```
mkk_automation.py     ← entry point (thin wrapper)
mkk_core.py           ← Config, DB, sector taxonomy, indicators, regime, risk
mkk_scanner.py        ← 9-stage scanner, sector heatmap, bulk backtest
mkk_paper.py          ← paper trading engine (exits + entries)
mkk_runner.py         ← orchestrator, email, CLI modes
.github/workflows/
  daily_run.yml       ← GitHub Actions schedule + commit workflow
mkk_system.db         ← SQLite database (committed to repo)
run_log.txt           ← plain text log of every run
requirements.txt
```

---

## One-Time Setup (15 minutes)

### Step 1 — Fork this repository

Click **Fork** on GitHub. This creates your private copy.

> Make it **private** if you want to keep your trades confidential.  
> Public repos with secrets use GitHub Secrets — the secrets are never exposed in code.

---

### Step 2 — Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add these 3 secrets:

| Secret name       | Value                                      |
|-------------------|--------------------------------------------|
| `EMAIL_SENDER`    | Your Gmail address e.g. `you@gmail.com`   |
| `EMAIL_PASSWORD`  | Gmail **App Password** (not your login password — see note below) |
| `EMAIL_RECIPIENT` | Address to receive daily emails (can be same as sender) |

**Gmail App Password setup:**
1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Security → 2-Step Verification (must be enabled)
3. Security → App Passwords → Select app: Mail → Generate
4. Copy the 16-character password → paste into `EMAIL_PASSWORD` secret

---

### Step 3 — Upload your stock universe (one-time)

The system needs NSE's equity list (`stock_L.csv`). Get it from:
- NSE India website → Market Data → Securities available for trading → Download CSV

Then run this **once** locally or in a GitHub Actions manual trigger:

```python
# Run locally (one time only):
from mkk_core import MKKDatabase
db = MKKDatabase('mkk_system.db')
db.load_csv('path/to/stock_L.csv')
db.close()
```

Or trigger manually via GitHub Actions UI:
1. Go to **Actions** → **MKK Daily Paper Trading**
2. Click **Run workflow** → mode: `SCAN_ONLY`

This will auto-create the DB with schema + macro events but won't scan (universe is empty).

**To upload your existing DB from Colab:**
1. Download `mkk_system.db` from your Google Drive
2. Commit it to your forked repo root:
   ```bash
   git add mkk_system.db
   git commit -m "Add initial DB with NSE universe"
   git push
   ```

The Actions workflow will use this DB and update it after every run.

---

### Step 4 — Enable GitHub Actions

1. Go to your forked repo → **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**
3. The workflow will run automatically at 9:20 AM IST on weekdays

---

### Step 5 — Verify first run

Trigger a manual run:
1. **Actions** → **MKK Daily Paper Trading** → **Run workflow** → mode: `SCAN_ONLY`
2. Watch the live log
3. Check your email for the daily summary
4. Verify `mkk_system.db` was committed back to the repo

---

## Run Modes

| Mode          | What it does                                                   |
|---------------|----------------------------------------------------------------|
| `DAILY`       | Full run: exits → scan → entries → snapshot → email (default) |
| `SCAN_ONLY`   | Scan and log setups, no trade entry                            |
| `EXIT_ONLY`   | Process exits on open trades only, no scan                     |
| `BACKTEST`    | Aggregate walk-forward backtest on 50 benchmark stocks         |
| `REPORT`      | Performance report email (win rate, R, P&L breakdown)          |

Trigger any mode manually: **Actions** → **MKK Daily Paper Trading** → **Run workflow** → select mode.

---

## Trading Protocol

### Entries (swing — daily timeframe)
- Signal generated at previous day's close
- Entry price = **next day's open** from yfinance
- Gap filter: skip if open > signal price × 1.03 (gap up chase protection)
- Filters applied before entry: sector gate, portfolio heat cap, sector exposure <25%, correlation <0.75 with open positions, macro event blackout, earnings guard

### Exits (checked each morning before scanning)
- **STOPPED_OUT**: previous day's low ≤ stop loss → exit at stop
- **T1_HIT**: previous day's high ≥ T1 → exit 30% at T1, move stop to breakeven
- **T2_HIT**: previous day's high ≥ T2 → exit 40% at T2
- **T3_HIT**: previous day's high ≥ T3 → exit remaining at T3
- **TIME_EXIT**: holding days ≥ 20 → exit at previous close
- Trailing stop updated every morning: `trail = max(current_stop, prev_high − 1.5×ATR)`

### Position Sizing
- Base risk: 1.5% of capital per trade
- Regime-adjusted: BULL 100% → BEAR_WK 50% → BEAR 0%
- Graduated loss response: 2 losses → 75% size | 3 losses → 50% | 4+ → paused
- Kelly sizing activates after 20 closed trades
- Max position: 15% of capital | Max sector: 25% | Max portfolio heat: 12% (BULL)

### Regime-Based Position Limits

| Regime   | Max Positions | Portfolio Heat Cap |
|----------|--------------|-------------------|
| BULL     | 8            | 12%               |
| BULL_WK  | 6            | 9%                |
| NEUTRAL  | 4            | 6%                |
| BEAR_WK  | 2            | 3%                |
| BEAR     | 0 (no new)   | 0%                |

---

## Gap Implementations (v6.1)

| Gap | Description | Status |
|-----|-------------|--------|
| Gap 1 | Aggregate walk-forward backtest (50+ stocks) | ✅ `--mode BACKTEST` |
| Gap 5 | Macro event calendar (RBI, FOMC, Budget, F&O expiry) | ✅ Auto-populated |
| Gap 6 | Volatility-adjusted ATR stop (1.5× / 2.0× / 2.5×) | ✅ Live in scanner |
| Gap 7 | 3-layer earnings date inference with DB cache | ✅ Live in scanner |

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `universe` | All NSE stocks with sector classification |
| `scan_sessions` | Every scan run with funnel statistics |
| `scan_results` | All elite setups found, priority-ranked |
| `paper_trades` | Open and closed paper trades |
| `paper_exits` | Exit events with P&L and R-multiples |
| `paper_snapshots` | Daily equity curve |
| `paper_sessions` | Automation run log |
| `sector_snapshots` | Daily sector heatmap |
| `macro_events` | RBI/FOMC/Budget/F&O blackout calendar |
| `earnings_calendar` | Cached earnings dates (3-layer inference) |
| `bulk_backtest_results` | Walk-forward OOS stats per stock |
| `system_events` | Error and info log |

---

## Querying Your Data

```python
import sqlite3, pandas as pd
conn = sqlite3.connect('mkk_system.db')

# Today's elite setups (priority ranked)
pd.read_sql("SELECT priority_rank,ticker,score,priority_score,macro_sector,"
            "pattern,rs_3m,rs_rank,to_resistance,stop_loss,target_t1 "
            "FROM scan_results WHERE scan_date=date('now') "
            "ORDER BY priority_rank", conn)

# Open paper trades with unrealised context
pd.read_sql("SELECT ticker,entry_date,entry_price,stop_loss,"
            "target_t1,target_t2,target_t3,shares_remaining,"
            "macro_sector,pattern,regime "
            "FROM paper_trades WHERE status IN ('OPEN','PARTIAL')", conn)

# Closed trade P&L
pd.read_sql("SELECT pe.exit_date,pt.ticker,pe.exit_type,"
            "pe.pnl_net,pe.r_multiple,pe.holding_days "
            "FROM paper_exits pe JOIN paper_trades pt "
            "ON pe.trade_id=pt.trade_id "
            "ORDER BY pe.exit_date DESC", conn)

# Equity curve
pd.read_sql("SELECT snap_date,total_capital,unrealized_pnl,"
            "realized_pnl_ytd,drawdown_pct,portfolio_heat "
            "FROM paper_snapshots ORDER BY snap_date", conn)

# Sector heatmap (today)
pd.read_sql("SELECT macro_sector,sector,rs_3m,trend_score,"
            "scan_hit_rate,sector_gate "
            "FROM sector_snapshots WHERE snap_date=date('now') "
            "ORDER BY rs_3m DESC", conn)

# Run history
pd.read_sql("SELECT run_date,regime,exits_processed,entries_taken,"
            "scan_setups,duration_sec "
            "FROM paper_sessions ORDER BY run_date DESC LIMIT 20", conn)
```

---

## Environment Variables (GitHub Secrets)

| Variable | Required | Description |
|----------|----------|-------------|
| `EMAIL_SENDER` | Yes | Gmail address to send from |
| `EMAIL_PASSWORD` | Yes | Gmail App Password (16 chars) |
| `EMAIL_RECIPIENT` | Yes | Address to receive emails |
| `DB_PATH` | No | Override DB path (default: `mkk_system.db`) |
| `PAPER_CAPITAL` | No | Paper trading capital in ₹ (default: 500000) |

---

## GitHub Free Tier Limits

| Resource | Limit | MKK Usage |
|----------|-------|-----------|
| Actions minutes/month | 2,000 | ~60–75 min/day × 22 days = ~1,650 min |
| Storage | 500 MB | DB grows ~50KB/month → years of runway |
| Artifact retention | 90 days | Run logs kept 30 days |

---

## Transition to Real Money (when ready)

After Phase 1 paper trading (40+ signals) and Phase 2 pilot (₹50K, max 2 positions):

1. Create a second DB: `mkk_live.db`
2. Mirror the paper logic with Zerodha Kite API for order placement
3. Replace yfinance with Kite Historical Data API for better NSE data quality

**Deploy real money only if** Phase 2 win rate ≥ 50%, avg R ≥ 1.5, no single trade loss > ₹3,000 over 3+ months.

---

## Troubleshooting

**Actions not triggering?**
- Check Actions is enabled: repo → Actions → enable
- GitHub cron schedules can be delayed 5–15 minutes — normal behaviour

**yfinance errors in log?**
- Usually rate limiting. The system retries once after 60 seconds
- NSE data quality issues (split adjustments, block deals) are known yfinance limitations

**DB not committed?**
- Check Actions log for git errors
- Ensure `GITHUB_TOKEN` has write permissions: repo → Settings → Actions → Workflow permissions → Read and write

**Email not arriving?**
- Verify Gmail App Password (not account password)
- Check spam folder
- Test Gmail SMTP from Python locally before pushing

**Universe empty on first run?**
- Upload `mkk_system.db` with universe pre-loaded, or
- Run `db.load_csv('stock_L.csv')` locally and commit the DB

---

## System Confidence Level

Current statistical confidence: **42/100** (pre-paper trading).

Roadmap to 80%+ confidence:
- Complete 60–90 days of paper trading (40+ closed trades)
- Achieve aggregate OOS positive alpha across bulk backtest
- Phase 2 pilot at ₹50K with capped risk

This system is for learning systematic trading. Use it to understand if the strategy has edge before committing capital.

---

*MKK Trading System | Built with Python + yfinance + SQLite + GitHub Actions*
