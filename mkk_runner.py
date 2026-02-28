"""
mkk_runner.py — Main Orchestrator + Email + CLI
Usage:
  python mkk_automation.py --mode DAILY
  python mkk_automation.py --mode SCAN_ONLY
  python mkk_automation.py --mode BACKTEST
  python mkk_automation.py --mode REPORT
  python mkk_automation.py --mode EXIT_ONLY
"""
import argparse, logging, os, sys, smtplib, traceback, time
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from typing import List, Dict, Optional
import pandas as pd

from mkk_core import (Config, MKKDatabase, IndexCache,
                      MarketRegimeEngine, RiskManager)
from mkk_scanner import SectorHeatmap, EliteSwingScanner, BulkBacktest
from mkk_paper import PaperTradingEngine

# ── BACKTEST STOCK LIST ───────────────────────────────────────────────
# High-quality NSE stocks for aggregate backtest (Gap 1)
BACKTEST_UNIVERSE = [
    'RELIANCE.NS','TCS.NS','INFY.NS','HDFCBANK.NS','ICICIBANK.NS',
    'BAJFINANCE.NS','HINDUNILVR.NS','AXISBANK.NS','WIPRO.NS','HCLTECH.NS',
    'LT.NS','SUNPHARMA.NS','TITAN.NS','ASIANPAINT.NS','MARUTI.NS',
    'NESTLEIND.NS','ULTRACEMCO.NS','TECHM.NS','POWERGRID.NS','NTPC.NS',
    'DRREDDY.NS','DIVISLAB.NS','BAJAJFINSV.NS','BHARTIARTL.NS','PIDILITIND.NS',
    'ADANIENT.NS','SBILIFE.NS','HDFCLIFE.NS','APOLLOHOSP.NS','DMART.NS',
    'SIEMENS.NS','ABB.NS','HAVELLS.NS','VOLTAS.NS','CROMPTON.NS',
    'COFORGE.NS','PERSISTENT.NS','LTIM.NS','MPHASIS.NS','OFSS.NS',
    'GLAND.NS','ALKEM.NS','LALPATHLAB.NS','METROPOLIS.NS','SYNGENE.NS',
    'PAGEIND.NS','TRENT.NS','NAUKRI.NS','ZOMATO.NS','POLICYBZR.NS',
]


# ══════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ══════════════════════════════════════════════════════════════════════
def setup_logging(log_file: str = 'run_log.txt'):
    fmt = '%(asctime)s [%(levelname)s] %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, mode='a', encoding='utf-8'),
        ]
    )
    # Quiet noisy libraries
    for lib in ('yfinance', 'urllib3', 'requests', 'peewee'):
        logging.getLogger(lib).setLevel(logging.CRITICAL)
    return logging.getLogger('mkk')


# ══════════════════════════════════════════════════════════════════════
# EMAIL
# ══════════════════════════════════════════════════════════════════════
def send_email(cfg: Config, subject: str, body: str) -> bool:
    if not all([cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD, cfg.EMAIL_RECIPIENT]):
        logging.getLogger('mkk').warning(
            'Email not configured (set EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT)')
        return False
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From']    = cfg.EMAIL_SENDER
        msg['To']      = cfg.EMAIL_RECIPIENT
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD)
            smtp.sendmail(cfg.EMAIL_SENDER, cfg.EMAIL_RECIPIENT, msg.as_string())
        logging.getLogger('mkk').info(f'Email sent: {subject}')
        return True
    except Exception as e:
        logging.getLogger('mkk').error(f'Email failed: {e}')
        return False


def build_daily_email(
        cfg: Config,
        re: MarketRegimeEngine,
        entries: List[dict],
        exits: List[dict],
        open_positions: List[dict],
        snap: dict,
        perf: dict,
        top_sectors: List[dict]) -> str:

    today    = date.today().isoformat()
    n_entry  = len(entries)
    n_exit   = len(exits)
    nifty_cl = re.nifty_close()
    r3m      = re.details.get('ret_3m_pct', 0)

    lines = []
    sep = '─' * 55

    lines += [
        '════════════════════════════════════════════════════════',
        f'  MKK PAPER TRADING SYSTEM  |  {today}',
        '════════════════════════════════════════════════════════',
        '',
        '[ 1 ] MARKET REGIME',
        sep,
        f'  Regime   : {re.regime}  (Score {re.score}/100)',
        f'  Nifty 50 : ₹{nifty_cl:,.2f}  |  3M return: {r3m:+.1f}%',
        f'  Entries  : {"✅ OPEN" if re.allow_entry() else "🚫 BLOCKED"}',
        '',
    ]

    lines += ['[ 2 ] TODAY\'S NEW ENTRIES', sep]
    if entries:
        for e in entries:
            lines += [
                f'  {e["ticker"]:<12} {e.get("trade_type","SWING"):<12} '
                f'{e.get("pattern","")}',
                f'    Sector   : {e.get("macro_sector","")} › {e.get("sector","")}',
                f'    Entry    : ₹{e["entry_price"]:,.2f}  '
                f'Stop ₹{e["stop_loss"]:,.2f}',
                f'    T1/T2/T3 : ₹{e["target_t1"]:,.2f} / '
                f'₹{e["target_t2"]:,.2f} / ₹{e["target_t3"]:,.2f}',
                f'    Qty      : {e["shares"]}  '
                f'Capital ₹{e["capital_invested"]:,.0f}  '
                f'Heat {e.get("heat_contribution",0)*100:.2f}%',
                '',
            ]
    else:
        lines += ['  No new entries today.', '']

    lines += ['[ 3 ] TODAY\'S EXITS', sep]
    if exits:
        for x in exits:
            pnl_s  = f'₹{x.get("pnl",0):+,.0f}'
            rm_s   = f'{x.get("r_mult",0):+.2f}R' if x.get('r_mult') else ''
            lines += [
                f'  {x["ticker"]:<12} {x.get("exit_type",""):<14} '
                f'Entry ₹{x.get("entry_price",0):,.2f} → '
                f'₹{x.get("exit_price",0):,.2f}',
                f'    P&L {pnl_s}  {rm_s}  '
                f'Held {x.get("hold_days",0)} days',
                '',
            ]
    else:
        lines += ['  No exits today.', '']

    lines += ['[ 4 ] OPEN POSITIONS', sep]
    if open_positions:
        for p in open_positions:
            alert = ' ⚠️ NEAR STOP' if p['dist_stop_pct'] < 3 else ''
            lines += [
                f'  {p["ticker"]:<12} {p["sector"]:<18} {p["pattern"]}',
                f'    Entry ₹{p["entry_price"]:,.2f}  '
                f'Now ₹{p["current_price"]:,.2f}  '
                f'Stop ₹{p["stop"]:,.2f} ({p["dist_stop_pct"]:.1f}% away){alert}',
                f'    Unreal ₹{p["unreal_pnl"]:+,.0f}  '
                f'{p["r_mult"]:+.2f}R  '
                f'Held {p["hold_days"]}d',
                '',
            ]
    else:
        lines += ['  No open positions.', '']

    lines += ['[ 5 ] PORTFOLIO SNAPSHOT', sep]
    total_pnl = perf.get('total_pnl', 0) if perf else 0
    wr        = perf.get('win_rate', 0)  if perf else 0
    avg_r     = perf.get('avg_r', 0)    if perf else 0
    n_trades  = perf.get('total', 0)    if perf else 0
    lines += [
        f'  Paper Capital  : ₹{cfg.TOTAL_CAPITAL:,.0f}',
        f'  Deployed       : ₹{snap.get("deployed",0):,.0f}  '
        f'Cash ₹{snap.get("cash",0):,.0f}',
        f'  Portfolio Heat : {snap.get("portfolio_heat_pct",0):.1f}%',
        f'  Open Positions : {snap.get("n_open",0)}',
        f'  Unrealised P&L : ₹{snap.get("unreal_pnl",0):+,.0f}',
        f'  Total P&L (closed) : ₹{total_pnl:+,.0f}  '
        f'(from {n_trades} closed trades)',
        f'  Win Rate       : {wr:.1f}%  Avg R: {avg_r:.2f}',
        '',
    ]

    lines += ['[ 6 ] SECTOR HEATMAP (Top 5 by RS)', sep]
    if top_sectors:
        lines.append(f'  {"Sector":<24} {"RS 3M":>8} {"Trend%":>7} {"Gate":>6}')
        for s in top_sectors:
            rs_s   = f'{s["rs_3m"]:.3f}' if s.get('rs_3m') else '  N/A'
            gate_s = 'OPEN' if s.get('gate_open') else 'SHUT'
            lines.append(f'  {s["sector"]:<24} {rs_s:>8} '
                         f'{s["trend_score"]:>6.0f}% {gate_s:>6}')
    else:
        lines.append('  No sector data available.')
    lines.append('')

    lines += [
        '[ 7 ] NEXT RUN',
        sep,
        f'  Scheduled: Next market day at 09:20 AM IST',
        f'  DB: mkk_system.db (committed to GitHub)',
        '',
        '════════════════════════════════════════════════════════',
        '  MKK Paper Trading System | Automated | Educational Only',
        '════════════════════════════════════════════════════════',
    ]

    return '\n'.join(lines)


def build_failure_email(error: str, db: Optional[MKKDatabase]) -> str:
    last_run = 'Unknown'
    integrity = 'DB unavailable'
    try:
        if db:
            row = db.q(
                "SELECT run_date FROM paper_sessions "
                "ORDER BY created_at DESC LIMIT 1").fetchone()
            if row:
                last_run = row[0]
            integrity = ', '.join(db.integrity_check())
    except Exception:
        pass
    return '\n'.join([
        f'MKK System encountered an error on {date.today().isoformat()}.',
        '',
        f'Last successful run : {last_run}',
        f'DB integrity        : {integrity}',
        '',
        'ERROR TRACEBACK:',
        '─' * 55,
        error,
        '─' * 55,
        '',
        'The database was NOT committed. Please investigate before next run.',
    ])


# ══════════════════════════════════════════════════════════════════════
# MODES
# ══════════════════════════════════════════════════════════════════════
def run_daily(cfg: Config, db: MKKDatabase, log) -> dict:
    """Full daily run: exits → scan → entries → snapshot → email."""
    t_start  = datetime.now()
    today    = date.today().isoformat()
    psid     = f"RUN_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    db.q('INSERT INTO paper_sessions(session_id,run_date,run_start,mode) '
         'VALUES(?,?,?,?)', (psid, today, t_start.isoformat(), 'DAILY'))
    db.conn.commit()

    # ── Regime ────────────────────────────────────────────────────────
    re   = MarketRegimeEngine(cfg)
    re.detect()
    risk = RiskManager(cfg, re, db)

    # ── Sector Heatmap ─────────────────────────────────────────────────
    hm = SectorHeatmap(cfg, re, db)

    # ── Load universe ─────────────────────────────────────────────────
    tickers = db.tickers_with_sectors(exclude_asm=cfg.EXCLUDE_ASM)
    log.info(f'Universe: {len(tickers)} tickers')

    # ── Paper engine: EXITS FIRST ──────────────────────────────────────
    paper = PaperTradingEngine(cfg, re, risk, db)
    exits = paper.process_exits()

    # ── Scan ───────────────────────────────────────────────────────────
    portfolio_exp = db.paper_sector_exposure(cfg)
    hm.compute([], portfolio_exp)   # sector gate pre-scan

    entries = []
    scan_results = []
    n_setups = 0

    if re.allow_entry():
        scanner = EliteSwingScanner(cfg, re, risk, db, hm)
        sid     = db.new_session(re.regime, re.score, re.nifty_close(), cfg)
        scan_results = scanner.scan(tickers)
        n_setups     = len(scan_results)

        # Recompute heatmap with hit rates
        hm.compute(scan_results, portfolio_exp)
        scanner.save(sid)
        db.close_session(sid, scanner.st)

        # ── ENTRIES ────────────────────────────────────────────────────
        entries = paper.process_entries(scan_results, psid)
    else:
        log.info(f'BEAR regime — scanning skipped. Exits only.')
        sid = db.new_session(re.regime, re.score, re.nifty_close(), cfg)
        db.close_session(sid, {'total': 0, 'elite': 0})

    # ── Snapshot ───────────────────────────────────────────────────────
    snap    = paper.take_snapshot()
    perf    = db.paper_perf_summary()
    open_p  = paper.open_positions_summary()
    top_sec = hm.top_sectors(5)

    # ── Email ──────────────────────────────────────────────────────────
    subject = (f"MKK Paper Trading | {today} | {re.regime} | "
               f"{len(entries)} entries | {len(exits)} exits")
    body    = build_daily_email(cfg, re, entries, exits, open_p,
                                snap, perf, top_sec)
    email_sent = send_email(cfg, subject, body)

    # ── Close session ──────────────────────────────────────────────────
    dur = (datetime.now() - t_start).seconds
    db.q('UPDATE paper_sessions SET run_end=?,duration_sec=?,'
         'exits_processed=?,entries_taken=?,scan_setups=?,email_sent=? '
         'WHERE session_id=?',
         (datetime.now().isoformat(), dur, len(exits),
          len(entries), n_setups, int(email_sent), psid))
    db.conn.commit()

    # ── Integrity check ────────────────────────────────────────────────
    for msg in db.integrity_check():
        log.info(f'Integrity: {msg}')

    log.info(f'Daily run complete: {dur}s | '
             f'{len(entries)} entries | {len(exits)} exits')
    return {'entries': len(entries), 'exits': len(exits), 'setups': n_setups}


def run_scan_only(cfg: Config, db: MKKDatabase, log):
    """Scan and log results, no trade entry. Sends scan summary email."""
    re   = MarketRegimeEngine(cfg)
    re.detect()
    risk = RiskManager(cfg, re, db)
    hm   = SectorHeatmap(cfg, re, db)
    tickers = db.tickers_with_sectors()
    hm.compute([], db.paper_sector_exposure(cfg))
    scanner = EliteSwingScanner(cfg, re, risk, db, hm)
    sid     = db.new_session(re.regime, re.score, re.nifty_close(), cfg)
    results = scanner.scan(tickers)
    hm.compute(results, db.paper_sector_exposure(cfg))
    scanner.save(sid)
    db.close_session(sid, scanner.st)
    log.info(f'Scan complete: {len(results)} setups saved')

    # ── Email scan summary ─────────────────────────────────────────
    today   = date.today().isoformat()
    subject = (f"MKK Scan Summary | {today} | {re.regime} | "
               f"{len(results)} setups found")
    lines   = [
        f'MKK SCAN SUMMARY — {today}',
        '─' * 55,
        f'Regime   : {re.regime}  (Score {re.score}/100)',
        f'Nifty 50 : ₹{re.nifty_close():,.2f}',
        f'Scanned  : {scanner.st["total"]} stocks in {scanner.st["dur"]:.1f} min',
        f'Setups   : {len(results)} elite setups found',
        '',
    ]
    if results:
        lines.append(f'  {"Rank":<5} {"Ticker":<12} {"Score":>6} '
                     f'{"PriScore":>9} {"Pattern":<18} {"Sector"}')
        lines.append('  ' + '─' * 72)
        for r in results:
            lines.append(
                f'  {r.get("Priority_Rank",0):<5} {r.get("Ticker",""):<12} '
                f'{r.get("Score",0):>6} {r.get("Priority_Score",0):>9} '
                f'{r.get("Pattern",""):<18} {r.get("Macro_Sector","")}')
        top = results[0]
        lines += [
            '',
            'TOP SETUP:',
            '─' * 55,
            f'  Ticker   : {top.get("Ticker")}',
            f'  Pattern  : {top.get("Pattern")}  Score {top.get("Score")}/100',
            f'  Sector   : {top.get("Macro_Sector")} › {top.get("Sector")}',
            f'  Price    : ₹{top.get("Price",0):,.2f}',
            f'  Stop     : ₹{top.get("Stop_Loss",0):,.2f}  Risk {top.get("Risk_%",0):.1f}%',
            f'  T1/T2/T3 : ₹{top.get("T1",0):,.2f} / ₹{top.get("T2",0):,.2f} / ₹{top.get("T3",0):,.2f}',
            f'  RS 3M    : {top.get("RS_3M","N/A")}  RS Rank {top.get("RS_Rank",0)}',
            f'  Qty      : {top.get("Shares",0)}  Capital ₹{top.get("Capital",0):,.0f}',
        ]
    else:
        lines.append('  No elite setups found today.')
    lines += [
        '',
        '─' * 55,
        'Note: SCAN_ONLY mode — no trades entered.',
        'Switch to DAILY mode for automated paper trading.',
    ]
    send_email(cfg, subject, '\n'.join(lines))


def run_exit_only(cfg: Config, db: MKKDatabase, log):
    """Process exits only, no scan, no entries."""
    re   = MarketRegimeEngine(cfg)
    re.detect()
    risk = RiskManager(cfg, re, db)
    paper = PaperTradingEngine(cfg, re, risk, db)
    exits = paper.process_exits()
    snap  = paper.take_snapshot()
    log.info(f'Exit-only run: {len(exits)} exits processed')


def run_backtest(cfg: Config, db: MKKDatabase, log):
    """Aggregate walk-forward backtest across BACKTEST_UNIVERSE."""
    bt = BulkBacktest(cfg, db)
    df = bt.run(BACKTEST_UNIVERSE, years=3)
    if not df.empty:
        # Email results
        lines = ['BULK BACKTEST RESULTS', '─' * 55]
        lines.append(f'Stocks: {len(df)} | Period: 3Y OOS')
        lines.append(f'Median CAGR  : {df["cagr_pct"].median():+.1f}%')
        lines.append(f'Median Alpha : {df["alpha_pct"].median():+.1f}%')
        lines.append(f'Pos Alpha    : {(df["alpha_pct"]>0).sum()}/{len(df)}')
        lines.append(f'Avg Win Rate : {df["win_rate_pct"].mean():.1f}%')
        lines.append(f'Avg PF       : {df["profit_factor"].mean():.2f}')
        lines.append('')
        lines.append('Top 10 by Alpha:')
        for _, r in df.head(10).iterrows():
            lines.append(f'  {r["ticker"]:<15} '
                         f'CAGR={r["cagr_pct"]:+.1f}%  '
                         f'Alpha={r["alpha_pct"]:+.1f}%  '
                         f'WR={r["win_rate_pct"]:.0f}%')
        send_email(cfg,
                   f'MKK Bulk Backtest | {date.today().isoformat()}',
                   '\n'.join(lines))


def run_report(cfg: Config, db: MKKDatabase, log):
    """Performance report + email."""
    re   = MarketRegimeEngine(cfg)
    re.detect()
    risk  = RiskManager(cfg, re, db)
    paper = PaperTradingEngine(cfg, re, risk, db)
    snap  = paper.take_snapshot()
    perf  = db.paper_perf_summary()
    open_p = paper.open_positions_summary()

    lines = [
        f'MKK PAPER TRADING REPORT — {date.today().isoformat()}',
        '─' * 55,
        f'Regime   : {re.regime} (Score {re.score}/100)',
        f'Nifty 50 : ₹{re.nifty_close():,.2f}',
        '',
        'PORTFOLIO',
        f'  Capital   : ₹{cfg.TOTAL_CAPITAL:,.0f}',
        f'  Deployed  : ₹{snap.get("deployed",0):,.0f}',
        f'  Open P&L  : ₹{snap.get("unreal_pnl",0):+,.0f}',
        '',
    ]
    if perf:
        lines += [
            'CLOSED TRADES',
            f'  Total     : {perf["total"]}',
            f'  Win Rate  : {perf["win_rate"]:.1f}%',
            f'  Total P&L : ₹{perf["total_pnl"]:+,.0f}',
            f'  Avg R     : {perf["avg_r"]:.3f}',
            f'  P. Factor : {perf["pf"]:.2f}',
            f'  Avg Win   : ₹{perf["avg_win"]:,.0f}',
            f'  Avg Loss  : ₹{perf["avg_loss"]:,.0f}',
            '',
        ]
    if open_p:
        lines += ['OPEN POSITIONS']
        for p in open_p:
            lines.append(f'  {p["ticker"]:<12} '
                         f'₹{p["entry_price"]:,.2f} → ₹{p["current_price"]:,.2f}  '
                         f'₹{p["unreal_pnl"]:+,.0f}  '
                         f'{p["r_mult"]:+.2f}R  '
                         f'{p["hold_days"]}d')

    # Scan history
    sh = db.qdf(
        "SELECT scan_date,regime,elite_setups,duration_min "
        "FROM scan_sessions ORDER BY scan_start DESC LIMIT 10")
    if not sh.empty:
        lines += ['', 'RECENT SCANS']
        for _, r in sh.iterrows():
            lines.append(f'  {r["scan_date"]}  {r["regime"]:<10}  '
                         f'{r["elite_setups"]} setups  '
                         f'{r["duration_min"] or 0:.1f}min')

    send_email(cfg,
               f'MKK Weekly Report | {date.today().isoformat()}',
               '\n'.join(lines))
    log.info('Report email sent')


# ══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='MKK Trading System')
    parser.add_argument('--mode', default='DAILY',
                        choices=['DAILY','SCAN_ONLY','BACKTEST',
                                 'REPORT','EXIT_ONLY'])
    parser.add_argument('--db',   default=None,
                        help='Override DB path')
    args = parser.parse_args()

    log = setup_logging('run_log.txt')
    log.info(f'═══ MKK AUTOMATION START | mode={args.mode} '
             f'| {datetime.now().isoformat()} ═══')

    cfg = Config()
    if args.db:
        cfg.DB_PATH = args.db

    db = None
    success = False

    try:
        db = MKKDatabase(cfg.DB_PATH)
        log.info(f'DB connected: {cfg.DB_PATH}')

        # Check universe — warn if empty
        cnt = db.q('SELECT COUNT(*) FROM universe').fetchone()[0]
        if cnt == 0:
            log.warning(
                'Universe table empty! Run with a stock_L.csv first:\n'
                '  from mkk_core import MKKDatabase, Config\n'
                '  db = MKKDatabase("mkk_system.db")\n'
                '  db.load_csv("stock_L.csv")')
            # Don't abort — macro events and schema still useful

        if args.mode == 'DAILY':
            for attempt in range(2):
                try:
                    run_daily(cfg, db, log)
                    success = True
                    break
                except Exception as e:
                    if attempt == 0:
                        log.warning(f'Daily run attempt 1 failed: {e} — retrying in 60s')
                        time.sleep(60)
                        IndexCache.clear()
                    else:
                        raise

        elif args.mode == 'SCAN_ONLY':
            run_scan_only(cfg, db, log); success = True

        elif args.mode == 'EXIT_ONLY':
            run_exit_only(cfg, db, log); success = True

        elif args.mode == 'BACKTEST':
            run_backtest(cfg, db, log); success = True

        elif args.mode == 'REPORT':
            run_report(cfg, db, log); success = True

        if not success:
            raise RuntimeError('All attempts failed')

    except Exception as e:
        tb = traceback.format_exc()
        log.error(f'FATAL ERROR:\n{tb}')
        try:
            send_email(
                cfg,
                f'⚠️ MKK System ERROR | {date.today().isoformat()} | {type(e).__name__}',
                build_failure_email(tb, db))
        except Exception:
            pass
        sys.exit(1)

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    log.info(f'═══ MKK AUTOMATION COMPLETE | success={success} ═══')
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
