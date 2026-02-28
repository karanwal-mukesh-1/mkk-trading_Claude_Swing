"""
mkk_core.py — MKK Institutional Trading System
DB schema + migration | Sector taxonomy | Indicators | Regime | Risk | TC
"""
import os, sqlite3, json, logging, math, warnings
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings('ignore')
log = logging.getLogger('mkk')


# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Config:
    # Capital
    TOTAL_CAPITAL: float   = float(os.getenv('PAPER_CAPITAL', 500_000))
    MAX_POSITIONS: int     = 8
    MAX_SECTOR_EXP: float  = 0.25
    MAX_SINGLE_POS: float  = 0.15
    CASH_RESERVE:   float  = 0.10
    MAX_HOLD_DAYS:  int    = 20

    # Portfolio heat caps by regime
    HEAT_CAP: Dict = field(default_factory=lambda: {
        'BULL':0.12,'BULL_WK':0.09,'NEUTRAL':0.06,
        'BEAR_WK':0.03,'BEAR':0.0,'VOLATILE':0.04})

    # India NSE TC
    BROKERAGE_FLAT:       float = 20.0
    STT_DELIVERY_PCT:     float = 0.001
    EXCHANGE_CHARGES_PCT: float = 0.0000345
    SEBI_CHARGES_PCT:     float = 0.000001
    GST_RATE:             float = 0.18
    STAMP_DUTY_PCT:       float = 0.00015
    SLIPPAGE_LARGE:       float = 0.001
    SLIPPAGE_MID:         float = 0.0025
    SLIPPAGE_SMALL:       float = 0.005
    MIN_VAL_LARGE:        float = 100_000_000
    MIN_VAL_MID:          float = 10_000_000

    # Risk
    MAX_RISK_PER_TRADE: float = 0.015
    ATR_STOP_MULT:      float = 2.0   # base; overridden by vol-adj (Gap6)
    SWING_RR:           float = 2.5
    POSITIONAL_RR:      float = 4.0
    TRAIL_ATR:          float = 1.5
    MAX_DD:             float = 0.15

    # Graduated loss
    LOSS_REDUCE_AT: int = 2
    LOSS_HALF_AT:   int = 3
    LOSS_PAUSE_AT:  int = 4
    WIN_TIGHTEN_AT: int = 5

    # Universe
    EXCHANGE:      str   = '.NS'
    LOOKBACK:      int   = 300
    MIN_BARS:      int   = 150
    MIN_LISTING_Y: float = 1.0
    EXCLUDE_ASM:   bool  = True

    # Benchmarks
    NIFTY50:   str = '^NSEI'
    NIFTY500:  str = '^CRSLDX'
    MIDCAP150: str = '^NSEMDCP50'

    # Price & Liquidity
    MIN_PRICE:   float = 20.0
    MIN_AVG_VOL: int   = 300_000

    # Trend MAs
    MA_FAST: int = 21; MA_MED: int = 50; MA_SLOW: int = 200
    EMA_S:   int = 9;  EMA_M:  int = 21; WEEKLY_MA: int = 20

    # Momentum
    RSI_PERIOD: int = 14; RSI_MIN: float = 40; RSI_MAX: float = 72
    RSI_HARD:   float = 80; ATR_PERIOD: int = 14
    MACD_FAST: int = 12; MACD_SLOW: int = 26; MACD_SIG: int = 9

    # Consolidation
    CONSOL_DAYS: int = 8; MAX_CONSOL_RANGE: float = 0.06
    SWING_HI_LB: int = 60; SWING_HI_THR: float = 0.08

    # RS
    RS_3M_MIN: float = 1.05; RS_6M_MIN: float = 1.10; RS_SLOPE_LB: int = 20

    # VCP
    VCP_ENABLE:    bool      = True
    VCP_LOOKBACKS: List[int] = field(default_factory=lambda: [15, 30])

    # Breakout
    RES_PERIOD: int = 20; BO_PROX: float = 3.0; VOL_CONTR_LIM: float = 0.70

    # Correlation
    MAX_CORR: float = 0.75; CORR_LB: int = 60

    # Earnings blackout
    EARNINGS_BK: int = 5

    # Sector gate
    SECTOR_TREND_MIN:    float = 50.0
    SECTOR_RS_MIN:       float = 1.00
    SECTOR_BYPASS_RANK:  int   = 90

    # Gap entry filter
    MAX_GAP_PCT: float = 3.0   # skip entry if open > prev_close × 1.03

    # Scoring
    MIN_SCORE:      int = 70
    MIN_SCORE_CONS: int = 80

    # Priority weights
    PRI_RS_RANK:  int = 25; PRI_VCP:   int = 20; PRI_SECTOR: int = 20
    PRI_BREAKOUT: int = 15; PRI_RR:    int = 10; PRI_LIQ:    int = 5
    PRI_EARN:     int = 5

    # Positional
    POS_RS_3M_MIN:      float = 1.20
    POS_VCP_MIN:        float = 40.0
    MIN_WATCHLIST_STAGE: int  = 4

    # Email
    EMAIL_SENDER:    str = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD:  str = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_RECIPIENT: str = os.getenv('EMAIL_RECIPIENT', '')

    # DB
    DB_PATH: str = os.getenv('DB_PATH', 'mkk_system.db')

    def min_avg_val(self) -> float:
        return max(10_000_000, 10 * self.TOTAL_CAPITAL * self.MAX_SINGLE_POS)

    def heat_cap(self, regime: str) -> float:
        return self.HEAT_CAP.get(regime, 0.06)

    def to_dict(self) -> dict:
        d = {}
        for f in self.__dataclass_fields__:
            v = getattr(self, f)
            if isinstance(v, (str, int, float, bool, list)):
                d[f] = v
        return d


# ══════════════════════════════════════════════════════════════════════
# NSE SECTOR TAXONOMY
# ══════════════════════════════════════════════════════════════════════
NSE_TAXONOMY = {
    'Energy & Power': {
        'Oil & Gas': {'keywords': ['oil','petroleum','refiner','ongc','bpcl','iocl','hpcl','mrpl','cpcl','reliance','castrol','gulfoil']},
        'Power Generation': {'keywords': ['power','energy','ntpc','tata power','adani power','adani green','torrent power','cesc','nhpc','sjvn']},
        'Power Transmission': {'keywords': ['powergrid','grid','transmission','sterlite power','kalpataru','kec inter']},
        'Solar & Renewable': {'keywords': ['solar','wind','renew','greenko','sterling wilson','inox wind','suzlon']},
    },
    'BFSI': {
        'Private Banks': {'keywords': ['hdfc bank','icici bank','axis bank','kotak','indusind','yes bank','federal bank','bandhan','idfc','rbl','bank']},
        'Public Banks': {'keywords': ['sbi','pnb','bank of baroda','canara','union bank','indian bank','uco bank','central bank']},
        'NBFCs & HFCs': {'keywords': ['finance','capital','bajaj finance','cholamandalam','muthoot','manappuram','pnb housing','aavas','home first']},
        'Insurance': {'keywords': ['insurance','life','general','lici','sbi life','hdfc life','icici pru','star health','go digit','max life']},
        'Brokers & Exchanges': {'keywords': ['angel one','5paisa','iifl','motilal','nse','bse','cdsl','nsdl','cams','kfintech','broker']},
        'Fintech & Payment': {'keywords': ['payment','paytm','razorpay','infibeam','fino','policybazaar']},
    },
    'Technology': {
        'IT Services': {'keywords': ['tcs','infosys','wipro','hcl tech','tech mahindra','mphasis','hexaware','cyient','birlasoft']},
        'Mid-cap IT': {'keywords': ['coforge','persistent','ltimindtree','eclerx','mastek','zensar','sonata']},
        'Software Products': {'keywords': ['tata elxsi','intellect','nucleus','sify','mapmy','indiamart']},
        'Electronics & Semiconductors': {'keywords': ['semiconductor','dixon','amber','kaynes','syrma','data pattern','avalon','bharat electron']},
    },
    'Healthcare': {
        'Pharma — Large': {'keywords': ['sun pharma','dr reddy','cipla','lupin','alkem','alembic','aurobindo','glenmark','zydus']},
        'Pharma — Mid/Small': {'keywords': ['ajanta','eris life','suven','sequent','divi','granules','laurus','syngene']},
        'Hospitals': {'keywords': ['hospital','healthcare','apollo','fortis','narayana','aster','max health','manipal','medanta']},
        'Diagnostics': {'keywords': ['diagnostic','lab','lal path','metropolis','thyrocare','vijaya']},
        'Medical Devices': {'keywords': ['device','implant','hll lifecare','poly medicure']},
    },
    'Consumer': {
        'FMCG': {'keywords': ['hindustan unilever','itc','britannia','nestle','marico','dabur','godrej consumer','emami','varun beverages','tata consumer']},
        'Retail & QSR': {'keywords': ['dmart','avenue','trent','v-mart','zomato','devyani','westlife','restaurant']},
        'Consumer Durables': {'keywords': ['titan','voltas','whirlpool','havells','orient electric','crompton','bajaj electric','v-guard']},
        'Jewellery & Luxury': {'keywords': ['kalyan','pc jeweller','senco','thangamayil','kddl','jewel']},
        'Textiles & Apparel': {'keywords': ['textile','raymond','arvind','aditya birla fashion','page industries','dollar','lux']},
    },
    'Industrials': {
        'Capital Goods': {'keywords': ['larsen','l&t','siemens','abb','cummins','thermax','bhel','ge t&d','triveni']},
        'Defence': {'keywords': ['hal','defence','bel','bharat forge','paras defence','astra micro','data pattern','mtar']},
        'Engineering & EPC': {'keywords': ['engineers india','ircon','rvnl','kalpataru','dilip buildcon','pnc infra','g r infra']},
        'Logistics': {'keywords': ['logistics','transport','delhivery','vrl','gati','allcargo','concor']},
    },
    'Materials': {
        'Metals & Mining': {'keywords': ['steel','tata steel','jsw steel','sail','hindalco','vedanta','hindustan zinc','nalco','nmdc','coal','moil']},
        'Specialty Chemicals': {'keywords': ['pidilite','asian paints','berger','kansai','atul','fine organic','galaxy surfact','navin fluorine','sudarshan']},
        'Commodity Chemicals': {'keywords': ['deepak nitrite','gujarat fluorochemicals','balaji amines','vinati organics','alkyl amines']},
        'Cement': {'keywords': ['cement','ultratech','ambuja','acc','shree cement','dalmia','ramco']},
    },
    'Real Estate': {
        'Developers': {'keywords': ['dlf','godrej properties','prestige','brigade','phoenix','sobha','oberoi','mahindra lifespace']},
        'REITs': {'keywords': ['reit','mindspace','embassy','brookfield','nexus']},
        'Housing Finance': {'keywords': ['hdfc','lic housing','pnb housing','aavas','home first','aptus','india shelter']},
    },
    'Auto & Mobility': {
        'OEM — 4W': {'keywords': ['maruti','tata motors','mahindra','force motors']},
        'OEM — 2W & 3W': {'keywords': ['bajaj','hero motocorp','tvs motor','ola electric','ather','eicher','greaves']},
        'OEM — Commercial': {'keywords': ['ashok leyland','sml isuzu']},
        'Auto Ancillary': {'keywords': ['motherson','bharat forge','sona blw','minda','endurance','gabriel','bosch','fag','timken']},
        'Tractors': {'keywords': ['escorts','sonalika','vstagro','tractor']},
    },
    'Telecom & Media': {
        'Telecom': {'keywords': ['bharti airtel','airtel','reliance jio','vodafone','hfcl','tejas networks','route mobile']},
        'Media & Entertainment': {'keywords': ['pvr','inox','sun tv','zee','network18','tips','saregama','nazara']},
    },
    'Agriculture': {
        'Agrochemicals': {'keywords': ['upl','pi industries','rallis','bayer crop','dhanuka','coromandel','agrochem']},
        'Seeds & Fertilisers': {'keywords': ['kaveri seed','chambal','gsfc','gnfc','rashtriya chemical','fertiliser']},
        'Food Processing': {'keywords': ['tata consumer','britannia','heritage food','avanti feeds','waterbase']},
    },
    'Infrastructure': {
        'Roads & Highways': {'keywords': ['knrcon','dilip buildcon','ashoka buildcon','psp projects','road','highway']},
        'Ports & Airports': {'keywords': ['adani ports','gujarat pipavav','airport','gmr infra','port']},
        'Urban Infra & Water': {'keywords': ['va tech wabag','ion exchange','water','patel engineering']},
    },
}

def classify_stock(symbol: str, company_name: str) -> Tuple[str, str, str]:
    name_lower = (company_name + ' ' + symbol).lower()
    for macro, sectors in NSE_TAXONOMY.items():
        for sector, meta in sectors.items():
            for kw in meta['keywords']:
                if kw in name_lower:
                    return macro, sector, sector
    return 'Other', 'Unclassified', 'Unclassified'


# ══════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════
SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS universe (
    symbol TEXT PRIMARY KEY, company_name TEXT, series TEXT,
    listing_date TEXT, isin TEXT, face_value REAL, market_lot INTEGER DEFAULT 1,
    ns_ticker TEXT, macro_sector TEXT, sector TEXT, industry TEXT,
    is_active INTEGER DEFAULT 1, on_asm INTEGER DEFAULT 0, on_gsm INTEGER DEFAULT 0,
    last_updated TEXT);

CREATE TABLE IF NOT EXISTS macro_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT NOT NULL, event_type TEXT NOT NULL,
    description TEXT, blackout_days INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_me_date ON macro_events(event_date);

CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker TEXT NOT NULL, estimated_date TEXT NOT NULL,
    source TEXT, confidence TEXT DEFAULT 'LOW',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, estimated_date));

CREATE TABLE IF NOT EXISTS sector_snapshots (
    snap_id TEXT PRIMARY KEY, snap_date TEXT, macro_sector TEXT,
    sector TEXT, n_stocks INTEGER, rs_3m REAL, trend_score REAL,
    pct_above_50ma REAL, scan_hit_rate REAL, portfolio_exposure REAL,
    sector_gate INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_ss_date ON sector_snapshots(snap_date);

CREATE TABLE IF NOT EXISTS scan_sessions (
    session_id TEXT PRIMARY KEY, scan_date TEXT, scan_start TEXT,
    scan_end TEXT, duration_min REAL, regime TEXT, regime_score INTEGER,
    nifty_close REAL, total_scanned INTEGER DEFAULT 0,
    data_failed INTEGER DEFAULT 0, sector_filtered INTEGER DEFAULT 0,
    price_vol_pass INTEGER DEFAULT 0, trend_pass INTEGER DEFAULT 0,
    consol_pass INTEGER DEFAULT 0, momentum_pass INTEGER DEFAULT 0,
    rs_pass INTEGER DEFAULT 0, rs_slope_pass INTEGER DEFAULT 0,
    vcp_pass INTEGER DEFAULT 0, corr_filtered INTEGER DEFAULT 0,
    elite_setups INTEGER DEFAULT 0, config_snapshot TEXT, notes TEXT);

CREATE TABLE IF NOT EXISTS scan_results (
    result_id TEXT PRIMARY KEY, session_id TEXT, scan_date TEXT,
    ticker TEXT, price REAL, score INTEGER, priority_score INTEGER,
    priority_rank INTEGER, trade_type TEXT, pattern TEXT, rsi REAL,
    rs_3m REAL, rs_6m REAL, rs_rank INTEGER, rs_improving INTEGER,
    vcp_quality REAL, vol_contraction REAL, pct_from_high REAL,
    to_resistance REAL, stop_loss REAL, atr_mult REAL,
    risk_pct REAL, target_t1 REAL, target_t2 REAL, target_t3 REAL,
    shares_suggested INTEGER, capital_required REAL, risk_inr REAL,
    slippage_est REAL, tc_all_in REAL, above_200ma INTEGER,
    macd_positive INTEGER, ema_cross INTEGER, regime TEXT,
    avg_volume INTEGER, avg_val REAL, near_earnings INTEGER DEFAULT 0,
    macro_sector TEXT, sector TEXT, industry TEXT,
    weekly_above_ma20 INTEGER DEFAULT 0, portfolio_heat_contrib REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_sr_date ON scan_results(scan_date);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
    trade_type TEXT, direction TEXT DEFAULT 'LONG',
    entry_date TEXT NOT NULL, entry_price REAL NOT NULL,
    shares INTEGER NOT NULL, shares_remaining INTEGER,
    capital_invested REAL, stop_loss REAL NOT NULL,
    risk_per_share REAL, risk_amount REAL, heat_contribution REAL,
    target_t1 REAL, target_t2 REAL, target_t3 REAL,
    t1_hit INTEGER DEFAULT 0, t2_hit INTEGER DEFAULT 0,
    be_stop_active INTEGER DEFAULT 0,
    pattern TEXT, score INTEGER, priority_score INTEGER,
    regime TEXT, rs_3m REAL, rs_rank INTEGER, vcp_quality REAL,
    rsi_at_entry REAL, atr_at_entry REAL, atr_mult_used REAL,
    transaction_cost REAL DEFAULT 0, slippage_est REAL DEFAULT 0,
    macro_sector TEXT, sector TEXT,
    status TEXT DEFAULT 'OPEN', notes TEXT,
    session_id TEXT, trade_source TEXT DEFAULT 'PAPER',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_pt_status ON paper_trades(status);

CREATE TABLE IF NOT EXISTS paper_exits (
    exit_id TEXT PRIMARY KEY, trade_id TEXT REFERENCES paper_trades(trade_id),
    exit_date TEXT, exit_price REAL, shares_exited INTEGER,
    exit_type TEXT, pnl_gross REAL, pnl_net REAL, pnl_pct REAL,
    r_multiple REAL, holding_days INTEGER, mae REAL, mfe REAL,
    transaction_cost REAL DEFAULT 0, notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS paper_snapshots (
    snap_date TEXT PRIMARY KEY, total_capital REAL, deployed REAL,
    cash REAL, open_positions INTEGER, unrealized_pnl REAL,
    realized_pnl_ytd REAL, portfolio_peak REAL, drawdown_pct REAL,
    portfolio_heat REAL, regime TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS paper_sessions (
    session_id TEXT PRIMARY KEY, run_date TEXT, run_start TEXT,
    run_end TEXT, duration_sec REAL, mode TEXT,
    regime TEXT, regime_score INTEGER,
    exits_processed INTEGER DEFAULT 0, entries_taken INTEGER DEFAULT 0,
    scan_setups INTEGER DEFAULT 0, errors TEXT,
    email_sent INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS bulk_backtest_results (
    run_id TEXT PRIMARY KEY, run_date TEXT, ticker TEXT,
    years INTEGER, cagr_pct REAL, max_dd_pct REAL,
    trades INTEGER, win_rate_pct REAL, avg_r REAL,
    profit_factor REAL, bench_cagr_pct REAL, alpha_pct REAL,
    avg_mae REAL, avg_mfe REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS system_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT, severity TEXT DEFAULT 'INFO',
    message TEXT, details TEXT);
"""

MACRO_EVENTS_2026 = [
    # RBI MPC Meetings 2026
    ('2026-02-05', 'RBI_MPC', 'RBI Monetary Policy Committee', 2),
    ('2026-04-07', 'RBI_MPC', 'RBI Monetary Policy Committee', 2),
    ('2026-06-05', 'RBI_MPC', 'RBI Monetary Policy Committee', 2),
    ('2026-08-05', 'RBI_MPC', 'RBI Monetary Policy Committee', 2),
    ('2026-10-07', 'RBI_MPC', 'RBI Monetary Policy Committee', 2),
    ('2026-12-04', 'RBI_MPC', 'RBI Monetary Policy Committee', 2),
    # Union Budget
    ('2026-02-01', 'BUDGET', 'Union Budget 2026-27', 3),
    # US FOMC Meetings 2026 (affects FII flows)
    ('2026-01-28', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-03-18', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-05-06', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-06-17', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-07-29', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-09-16', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-11-04', 'FOMC', 'US Federal Reserve FOMC', 1),
    ('2026-12-16', 'FOMC', 'US Federal Reserve FOMC', 1),
    # NSE Monthly F&O Expiry (last Thursday — approximate, major ones)
    ('2026-01-29', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-02-26', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-03-26', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-04-30', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-05-28', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-06-25', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-07-30', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-08-27', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-09-24', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-10-29', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-11-26', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
    ('2026-12-31', 'FO_EXPIRY', 'NSE Monthly F&O Expiry', 1),
]


class MKKDatabase:
    def __init__(self, path: str):
        self.db_path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate()
        self._seed_macro_events()

    def _init_schema(self):
        for stmt in SCHEMA.strip().split(';'):
            s = stmt.strip()
            if s:
                try:
                    self.conn.execute(s)
                except Exception as e:
                    log.debug(f'Schema stmt skipped: {e}')
        self.conn.commit()

    def _migrate(self):
        """Add any missing columns from v6.0 → v6.1 migration."""
        cur = self.conn.cursor()
        # universe columns
        existing = {r[1] for r in cur.execute("PRAGMA table_info(universe)")}
        for col, td in [('macro_sector', 'TEXT'), ('sector', 'TEXT'),
                         ('industry', 'TEXT'), ('ns_ticker', 'TEXT')]:
            if col not in existing:
                cur.execute(f'ALTER TABLE universe ADD COLUMN {col} {td}')
                log.info(f'Migration: added universe.{col}')
        # scan_results — atr_mult column
        sr_cols = {r[1] for r in cur.execute("PRAGMA table_info(scan_results)")}
        if 'atr_mult' not in sr_cols:
            try:
                cur.execute('ALTER TABLE scan_results ADD COLUMN atr_mult REAL DEFAULT 2.0')
            except Exception:
                pass
        # Fix ns_ticker nulls
        cur.execute("UPDATE universe SET ns_ticker = symbol || '.NS' "
                    "WHERE ns_ticker IS NULL OR ns_ticker = ''")
        self.conn.commit()

    def _seed_macro_events(self):
        cur = self.conn.cursor()
        existing = cur.execute("SELECT COUNT(*) FROM macro_events").fetchone()[0]
        if existing == 0:
            cur.executemany(
                'INSERT OR IGNORE INTO macro_events'
                '(event_date, event_type, description, blackout_days) VALUES(?,?,?,?)',
                MACRO_EVENTS_2026)
            self.conn.commit()
            log.info(f'Seeded {len(MACRO_EVENTS_2026)} macro events for 2026')

    def q(self, sql: str, p: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, p)

    def qdf(self, sql: str, p: tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.conn, params=p)

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass

    # ── Universe ──────────────────────────────────────────────────────
    def load_csv(self, path: str) -> int:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        today = date.today().isoformat()
        rows = []
        for _, r in df.iterrows():
            sym = str(r.get('Symbol', '')).strip()
            if not sym:
                continue
            cname = str(r.get('NAME OF COMPANY', '') or '').strip()
            mac, sec, ind = classify_stock(sym, cname)
            rows.append((sym, cname,
                str(r.get('SERIES', '') or '').strip(),
                str(r.get('DATE OF LISTING', '') or '').strip(),
                str(r.get('ISIN NUMBER', '') or '').strip(),
                float(r.get('FACE VALUE', 0) or 0),
                int(r.get('MARKET LOT', 1) or 1),
                f'{sym}.NS', mac, sec, ind, 1, 0, 0, today))
        self.conn.executemany(
            'INSERT OR REPLACE INTO universe(symbol,company_name,series,'
            'listing_date,isin,face_value,market_lot,ns_ticker,macro_sector,'
            'sector,industry,is_active,on_asm,on_gsm,last_updated) VALUES'
            '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        self.conn.commit()
        log.info(f'Universe loaded: {len(rows)} symbols')
        return len(rows)

    def tickers_with_sectors(self, exclude_asm: bool = True) -> List[tuple]:
        asm = "AND on_asm=0 AND on_gsm=0" if exclude_asm else ""
        rows = self.q(
            f"SELECT ns_ticker, macro_sector, sector, industry FROM universe "
            f"WHERE is_active=1 AND series IN ('EQ','BE') {asm}").fetchall()
        return [(r[0], r[1] or 'Other', r[2] or 'Unclassified', r[3] or 'Unclassified')
                for r in rows]

    # ── Macro event guard (Gap 5) ──────────────────────────────────────
    def is_macro_blackout(self, check_date: str) -> Tuple[bool, str]:
        cd = date.fromisoformat(check_date)
        rows = self.q(
            "SELECT event_date, event_type, blackout_days FROM macro_events "
            "WHERE date(event_date) BETWEEN date(?) AND date(?)",
            ((cd - timedelta(days=3)).isoformat(),
             (cd + timedelta(days=3)).isoformat())).fetchall()
        for r in rows:
            ed = date.fromisoformat(r[0])
            delta = abs((cd - ed).days)
            if delta <= r[2]:
                return True, f"{r[1]} on {r[0]} (±{r[2]}d blackout)"
        return False, ''

    # ── Earnings calendar (Gap 7) ──────────────────────────────────────
    def get_earnings_date(self, ticker: str) -> Tuple[Optional[str], str]:
        """Returns (estimated_date_str_or_None, source)."""
        row = self.q(
            "SELECT estimated_date, source FROM earnings_calendar "
            "WHERE ticker=? ORDER BY estimated_date DESC LIMIT 1",
            (ticker,)).fetchone()
        if row:
            return row[0], row[1]
        return None, 'NONE'

    def save_earnings_date(self, ticker: str, est_date: str, source: str, confidence: str):
        self.q('INSERT OR REPLACE INTO earnings_calendar'
               '(ticker,estimated_date,source,confidence) VALUES(?,?,?,?)',
               (ticker, est_date, source, confidence))
        self.conn.commit()

    def fetch_earnings_date(self, ticker: str) -> Tuple[Optional[str], str]:
        """3-layer earnings fetch (Gap 7). Returns (date_str, source)."""
        cached, src = self.get_earnings_date(ticker)
        if cached:
            return cached, src

        # Layer 1: yfinance calendar
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is not None and not (isinstance(cal, pd.DataFrame) and cal.empty):
                if isinstance(cal, pd.DataFrame):
                    dates = [str(v) for v in cal.values.flatten()
                             if v and str(v) not in ('nan', 'None')]
                else:
                    dates = [str(cal.get('Earnings Date', ''))]
                if dates and dates[0]:
                    est = dates[0][:10]
                    self.save_earnings_date(ticker, est, 'YF_CALENDAR', 'HIGH')
                    return est, 'YF_CALENDAR'
        except Exception:
            pass

        # Layer 2: quarterly_earnings inference
        try:
            qe = yf.Ticker(ticker).quarterly_earnings
            if qe is not None and not qe.empty:
                last_q = pd.to_datetime(qe.index[-1])
                next_est = (last_q + timedelta(days=91)).strftime('%Y-%m-%d')
                self.save_earnings_date(ticker, next_est, 'QE_INFERRED', 'LOW')
                return next_est, 'QE_INFERRED'
        except Exception:
            pass

        # Layer 3: log for manual update
        self.q("INSERT OR IGNORE INTO system_events(event_type,severity,message) VALUES(?,?,?)",
               ('EARNINGS_UNKNOWN', 'LOW', f'{ticker}: earnings date unknown'))
        self.conn.commit()
        return None, 'UNKNOWN'

    # ── Scan session ──────────────────────────────────────────────────
    def new_session(self, regime: str, score: int, nifty_close: float,
                    cfg: Config) -> str:
        sid = f"SCAN_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.q('INSERT INTO scan_sessions(session_id,scan_date,scan_start,'
               'regime,regime_score,nifty_close,config_snapshot) VALUES(?,?,?,?,?,?,?)',
               (sid, date.today().isoformat(), datetime.now().isoformat(),
                regime, score, nifty_close, json.dumps(cfg.to_dict())))
        self.conn.commit()
        return sid

    def close_session(self, sid: str, st: dict):
        self.q('UPDATE scan_sessions SET scan_end=?,duration_min=?,total_scanned=?,'
               'data_failed=?,sector_filtered=?,price_vol_pass=?,trend_pass=?,'
               'consol_pass=?,momentum_pass=?,rs_pass=?,rs_slope_pass=?,vcp_pass=?,'
               'corr_filtered=?,elite_setups=? WHERE session_id=?',
               (datetime.now().isoformat(), st.get('dur', 0), st.get('total', 0),
                st.get('fail', 0), st.get('sect', 0), st.get('pv', 0),
                st.get('tr', 0), st.get('co', 0), st.get('mo', 0),
                st.get('rs', 0), st.get('rss', 0), st.get('vcp', 0),
                st.get('corr', 0), st.get('elite', 0), sid))
        self.conn.commit()

    def save_results(self, results: list, sid: str):
        today = date.today().isoformat()
        SQL = (
            'INSERT OR REPLACE INTO scan_results('
            'result_id,session_id,scan_date,ticker,price,score,priority_score,'
            'priority_rank,trade_type,pattern,rsi,rs_3m,rs_6m,rs_rank,rs_improving,'
            'vcp_quality,vol_contraction,pct_from_high,to_resistance,stop_loss,atr_mult,'
            'risk_pct,target_t1,target_t2,target_t3,shares_suggested,capital_required,'
            'risk_inr,slippage_est,tc_all_in,above_200ma,macd_positive,ema_cross,regime,'
            'avg_volume,avg_val,near_earnings,macro_sector,sector,industry,'
            'weekly_above_ma20,portfolio_heat_contrib) VALUES'
            '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
        for r in results:
            self.q(SQL, (
                f"{sid}_{r['Ticker']}", sid, today,
                r.get('Ticker'), r.get('Price'), r.get('Score'),
                r.get('Priority_Score', 0), r.get('Priority_Rank', 0),
                r.get('TradeType'), r.get('Pattern'), r.get('RSI'),
                r.get('RS_3M') if r.get('RS_3M') != 'N/A' else None,
                r.get('RS_6M') if r.get('RS_6M') != 'N/A' else None,
                r.get('RS_Rank'), 1 if r.get('RS_Improving') == '✓' else 0,
                r.get('VCP_Quality'), r.get('Vol_Contraction'),
                r.get('Pct_From_High'), r.get('To_Resistance%'),
                r.get('Stop_Loss'), r.get('ATR_Mult', 2.0), r.get('Risk_%'),
                r.get('T1'), r.get('T2'), r.get('T3'),
                r.get('Shares'), r.get('Capital'), r.get('Risk_INR'),
                r.get('Slippage', 0), r.get('TC_AllIn', 0),
                1 if r.get('Above_200MA') == '✓' else 0,
                1 if r.get('MACD_Pos') == '✓' else 0,
                1 if r.get('EMA_Cross') == '✓' else 0,
                r.get('Regime'), r.get('Avg_Vol'), r.get('Avg_Val', 0),
                r.get('Near_Earnings', 0),
                r.get('Macro_Sector'), r.get('Sector'), r.get('Industry'),
                r.get('Weekly_MA20', 0), r.get('Heat_Contrib', 0)))
        self.conn.commit()

    def save_sector_snapshot(self, rows: list):
        today = date.today().isoformat()
        for r in rows:
            sid = f"SECT_{today}_{r['macro_sector'][:6]}_{r['sector'][:6]}"
            self.q('INSERT OR REPLACE INTO sector_snapshots'
                   '(snap_id,snap_date,macro_sector,sector,n_stocks,rs_3m,'
                   'trend_score,pct_above_50ma,scan_hit_rate,portfolio_exposure,sector_gate)'
                   ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (sid, today, r['macro_sector'], r['sector'], r.get('n_stocks', 0),
                    r.get('rs_3m'), r.get('trend_score', 0), r.get('pct_above_50ma', 0),
                    r.get('scan_hit_rate', 0), r.get('portfolio_exposure', 0),
                    1 if r.get('gate_open') else 0))
        self.conn.commit()

    # ── Paper trades ──────────────────────────────────────────────────
    def open_paper_trades(self) -> pd.DataFrame:
        return self.qdf(
            "SELECT * FROM paper_trades WHERE status IN ('OPEN','PARTIAL') "
            "ORDER BY entry_date")

    def log_paper_entry(self, t: dict) -> str:
        tid = f"PAPER_{t['ticker']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        rps = t.get('entry_price', 0) - t.get('stop_loss', 0)
        self.q(
            'INSERT OR IGNORE INTO paper_trades(trade_id,ticker,trade_type,direction,'
            'entry_date,entry_price,shares,shares_remaining,capital_invested,stop_loss,'
            'risk_per_share,risk_amount,heat_contribution,target_t1,target_t2,target_t3,'
            'pattern,score,priority_score,regime,rs_3m,rs_rank,vcp_quality,rsi_at_entry,'
            'atr_at_entry,atr_mult_used,transaction_cost,slippage_est,'
            'macro_sector,sector,status,session_id,trade_source) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, t.get('ticker'), t.get('trade_type', 'SWING'), 'LONG',
             t.get('entry_date', date.today().isoformat()),
             t.get('entry_price'), t.get('shares'), t.get('shares'),
             t.get('capital_invested'), t.get('stop_loss'),
             rps, rps * t.get('shares', 0), t.get('heat_contribution', 0),
             t.get('target_t1'), t.get('target_t2'), t.get('target_t3'),
             t.get('pattern'), t.get('score'), t.get('priority_score', 0),
             t.get('regime'), t.get('rs_3m'), t.get('rs_rank'),
             t.get('vcp_quality'), t.get('rsi_at_entry'),
             t.get('atr_at_entry', 0), t.get('atr_mult_used', 2.0),
             t.get('transaction_cost', 0), t.get('slippage_est', 0),
             t.get('macro_sector'), t.get('sector'),
             'OPEN', t.get('session_id'), 'PAPER'))
        self.conn.commit()
        log.info(f'Paper entry: {tid} @ ₹{t.get("entry_price")}')
        return tid

    def log_paper_exit(self, trade_id: str, e: dict):
        tr = self.q('SELECT * FROM paper_trades WHERE trade_id=?',
                    (trade_id,)).fetchone()
        if not tr:
            log.warning(f'Paper trade {trade_id} not found')
            return
        eid = f"EXIT_{trade_id}_{datetime.now().strftime('%H%M%S')}"
        ep = e.get('exit_price', 0)
        sx = e.get('shares_exited', tr['shares'])
        rps = tr['risk_per_share'] or 1
        tc = e.get('transaction_cost', 0)
        pg = (ep - tr['entry_price']) * sx
        pn = pg - tc
        pp = pg / tr['capital_invested'] * 100 if tr['capital_invested'] else 0
        rm = pn / (rps * sx) if rps * sx else 0
        hd = (date.fromisoformat(e.get('exit_date', date.today().isoformat()))
              - date.fromisoformat(tr['entry_date'])).days
        rem = (tr['shares_remaining'] or tr['shares']) - sx
        st = 'CLOSED' if rem <= 0 else 'PARTIAL'
        self.q('INSERT INTO paper_exits(exit_id,trade_id,exit_date,exit_price,'
               'shares_exited,exit_type,pnl_gross,pnl_net,pnl_pct,r_multiple,'
               'holding_days,mae,mfe,transaction_cost,notes) VALUES'
               '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (eid, trade_id, e.get('exit_date', date.today().isoformat()),
                ep, sx, e.get('exit_type', 'MANUAL'),
                round(pg, 2), round(pn, 2), round(pp, 2), round(rm, 3),
                hd, e.get('mae'), e.get('mfe'), tc, e.get('notes', '')))
        updates = {'status': st, 'shares_remaining': max(0, rem)}
        if e.get('exit_type') == 'T1_HIT':
            updates['t1_hit'] = 1
            updates['stop_loss'] = tr['entry_price']   # move to breakeven
            updates['be_stop_active'] = 1
        if e.get('exit_type') == 'T2_HIT':
            updates['t2_hit'] = 1
        if e.get('new_stop'):
            updates['stop_loss'] = e['new_stop']
        set_clause = ', '.join(f'{k}=?' for k in updates)
        self.q(f'UPDATE paper_trades SET {set_clause} WHERE trade_id=?',
               (*updates.values(), trade_id))
        self.conn.commit()
        log.info(f'Paper exit: {eid} | {e.get("exit_type")} | R={rm:.2f}')

    def paper_portfolio_heat(self) -> float:
        ot = self.open_paper_trades()
        if ot.empty:
            return 0.0
        return float(ot['heat_contribution'].fillna(0).sum())

    def paper_sector_exposure(self, cfg: Config) -> Dict[str, float]:
        ot = self.open_paper_trades()
        if ot.empty:
            return {}
        ot['wt'] = ot['capital_invested'] / cfg.TOTAL_CAPITAL
        return ot.groupby('macro_sector')['wt'].sum().to_dict()

    def save_paper_snapshot(self, cap: float, deployed: float,
                            unreal: float, n_open: int,
                            regime: str, heat: float):
        peak = max(cap + unreal,
                   self.q("SELECT COALESCE(MAX(portfolio_peak),0) "
                           "FROM paper_snapshots").fetchone()[0])
        dd = (peak - (cap + unreal)) / peak * 100 if peak > 0 else 0
        ytd = self.qdf(
            "SELECT COALESCE(SUM(pnl_net),0) as s FROM paper_exits "
            "WHERE strftime('%Y',exit_date)=?",
            (str(date.today().year),))['s'].iloc[0]
        self.q('INSERT OR REPLACE INTO paper_snapshots(snap_date,total_capital,'
               'deployed,cash,open_positions,unrealized_pnl,realized_pnl_ytd,'
               'portfolio_peak,drawdown_pct,portfolio_heat,regime) '
               'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               (date.today().isoformat(), round(cap + unreal, 2),
                round(deployed, 2), round(cap - deployed, 2), n_open,
                round(unreal, 2), round(ytd, 2), round(peak, 2),
                round(dd, 2), round(heat * 100, 2), regime))
        self.conn.commit()

    def paper_perf_summary(self) -> dict:
        df = self.qdf(
            'SELECT pe.*, pt.macro_sector, pt.pattern, pt.regime '
            'FROM paper_exits pe JOIN paper_trades pt ON pe.trade_id=pt.trade_id')
        if df.empty:
            return {}
        n = len(df); w = (df['pnl_net'] > 0).sum(); l = n - w
        aw = df[df['pnl_net'] > 0]['pnl_net'].mean() if w else 0
        al = df[df['pnl_net'] <= 0]['pnl_net'].mean() if l else -1
        return {
            'total': n, 'wins': int(w), 'losses': int(l),
            'win_rate': round(w / n * 100, 1),
            'total_pnl': round(df['pnl_net'].sum(), 2),
            'avg_r': round(df['r_multiple'].mean(), 3),
            'pf': round(abs(aw / al), 2) if al else 0,
            'avg_win': round(aw, 2), 'avg_loss': round(al, 2),
        }

    def log_event(self, etype: str, sev: str, msg: str, det: str = ''):
        self.q('INSERT INTO system_events(event_type,severity,message,details) '
               'VALUES(?,?,?,?)', (etype, sev, msg, det))
        self.conn.commit()

    def integrity_check(self) -> List[str]:
        issues = []
        o = self.qdf(
            'SELECT exit_id FROM paper_exits WHERE trade_id NOT IN '
            '(SELECT trade_id FROM paper_trades)')
        if not o.empty:
            issues.append(f'{len(o)} orphan paper exits')
        return issues or ['OK']


# ══════════════════════════════════════════════════════════════════════
# INDEX CACHE
# ══════════════════════════════════════════════════════════════════════
class IndexCache:
    _store: Dict[str, pd.DataFrame] = {}

    @classmethod
    def get(cls, sym: str, start) -> pd.DataFrame:
        if sym in cls._store and len(cls._store[sym]) > 50:
            return cls._store[sym]
        try:
            df = yf.download(sym, start=start, progress=False, timeout=20)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                df = df[df['Close'] > 0].dropna(subset=['Close'])
                cls._store[sym] = df
                return df
        except Exception as e:
            log.debug(f'IndexCache {sym}: {e}')
        return pd.DataFrame()

    @classmethod
    def clear(cls):
        cls._store = {}


# ══════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════════════
class TI:
    @staticmethod
    def prep(raw: pd.DataFrame) -> Optional[pd.DataFrame]:
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        if not all(c in raw.columns for c in ['Open', 'High', 'Low', 'Close', 'Volume']):
            return None
        df = raw.copy()
        df = df[df['Close'] > 0]
        df = df[df['Close'].pct_change().abs().fillna(0) < 0.50]
        return df if len(df) > 10 else None

    @staticmethod
    def rsi(p: pd.Series, n: int = 14) -> pd.Series:
        d = p.diff()
        g = d.where(d > 0, 0).rolling(n).mean()
        l = (-d.where(d < 0, 0)).rolling(n).mean()
        return (100 - 100 / (1 + g / l.replace(0, np.nan))).fillna(50)

    @staticmethod
    def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
        h, l, c = df['High'], df['Low'], df['Close']
        tr = pd.concat([h - l, (h - c.shift()).abs(),
                        (l - c.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(n).mean()

    @staticmethod
    def atr_percentile(df: pd.DataFrame, n: int = 14, lb: int = 63) -> float:
        """Gap 6: returns current ATR percentile over lb-day history."""
        atr_series = TI.atr(df, n).dropna()
        if len(atr_series) < lb:
            return 50.0
        hist = atr_series.iloc[-lb:]
        cur = float(atr_series.iloc[-1])
        return float((hist < cur).mean() * 100)

    @staticmethod
    def vol_adj_atr_mult(df: pd.DataFrame, n: int = 14, lb: int = 63) -> float:
        """Gap 6: volatility-adjusted ATR multiplier (1.5 / 2.0 / 2.5)."""
        pct = TI.atr_percentile(df, n, lb)
        if pct > 80:
            return 2.5   # elevated volatility — widen stop
        if pct < 20:
            return 1.5   # unusually quiet — tighten stop
        return 2.0        # normal

    @staticmethod
    def macd(p: pd.Series, f: int = 12, s: int = 26, sig: int = 9):
        ef = p.ewm(span=f, adjust=False).mean()
        es = p.ewm(span=s, adjust=False).mean()
        m = ef - es
        sg = m.ewm(span=sig, adjust=False).mean()
        return m, sg, m - sg

    @staticmethod
    def rs(stock: pd.DataFrame, idx: pd.DataFrame, days: int) -> Optional[float]:
        try:
            s = stock['Close'].dropna()
            i = idx['Close'].dropna()
            c = s.index.intersection(i.index)
            if len(c) < days:
                return None
            sc = s.loc[c].iloc[-1] / s.loc[c].iloc[-days] - 1
            ic = i.loc[c].iloc[-1] / i.loc[c].iloc[-days] - 1
            return None if ic == 0 else (1 + sc) / (1 + ic)
        except Exception:
            return None

    @staticmethod
    def rs_slope(stock: pd.DataFrame, idx: pd.DataFrame,
                 per: int = 63, lb: int = 20) -> Tuple:
        try:
            s = stock['Close'].dropna()
            i = idx['Close'].dropna()
            c = s.index.intersection(i.index)
            if len(c) < per + lb:
                return None, None, False
            s, i = s.loc[c], i.loc[c]

            def _r(o):
                sc = s.iloc[-o] / s.iloc[-per - o] - 1
                ic = i.iloc[-o] / i.iloc[-per - o] - 1
                return (1 + sc) / (1 + ic) if ic != 0 else None

            rn, rp = _r(1), _r(lb)
            return rn, rp, bool(rn and rp and rn > rp)
        except Exception:
            return None, None, False

    @staticmethod
    def vcp(df: pd.DataFrame, lb: int = 15) -> Tuple[bool, float]:
        if len(df) < lb:
            return False, 0
        r = (df['High'] - df['Low']).rolling(5).mean()
        if len(r) < lb:
            return False, 0
        t1, t2, t3 = lb, int(lb * 2 / 3), int(lb / 3)
        s1 = r.iloc[-t1:-t2].mean()
        s2 = r.iloc[-t2:-t3].mean()
        s3 = r.iloc[-t3:].mean()
        if not (s1 > s2 > s3 and s1 > 0):
            return False, 0
        return True, (1 - s3 / s1) * 100

    @staticmethod
    def consolidating(df: pd.DataFrame, days: int, max_r: float) -> bool:
        if len(df) < days:
            return False
        r = df['Close'].iloc[-days:]
        lo = r.min()
        return lo > 0 and (r.max() - lo) / lo <= max_r

    @staticmethod
    def pattern(df: pd.DataFrame, lb: int = 20) -> str:
        if len(df) < lb:
            return 'Insufficient Data'
        c = df['Close'].iloc[-lb:]
        if (c.iloc[-10:].max() - c.iloc[-10:].min()) / c.iloc[-10:].min() < 0.06:
            return 'Flat Base'
        adv = (c.max() - c.min()) / c.min()
        pb = (c.max() - c.iloc[-1]) / c.max()
        if adv > 0.25 and pb < 0.08:
            return 'High Tight Flag'
        if len(c) >= 21:
            l2, m, r2 = c[:7].mean(), c[7:14].min(), c[14:21].mean()
            if m < l2 * 0.92 and r2 >= l2 * 0.95:
                return 'Cup Pattern'
        return 'Consolidation'

    @staticmethod
    def weekly_above_ma(daily_df: pd.DataFrame, n: int = 20) -> bool:
        try:
            weekly = daily_df['Close'].resample('W').last().dropna()
            if len(weekly) < n:
                return False
            return float(weekly.iloc[-1]) > float(weekly.rolling(n).mean().iloc[-1])
        except Exception:
            return False

    @staticmethod
    def correlation(stock_df: pd.DataFrame, ref_dfs: list, days: int = 60) -> float:
        if not ref_dfs:
            return 0.0
        try:
            sr = stock_df['Close'].iloc[-days:].pct_change().dropna()
            mx = 0.0
            for ref in ref_dfs:
                rr = ref['Close'].iloc[-days:].pct_change().dropna()
                cm = sr.index.intersection(rr.index)
                if len(cm) < 20:
                    continue
                mx = max(mx, abs(sr.loc[cm].corr(rr.loc[cm])))
            return mx
        except Exception:
            return 0.0


# ══════════════════════════════════════════════════════════════════════
# MARKET REGIME ENGINE
# ══════════════════════════════════════════════════════════════════════
class MarketRegimeEngine:
    RM = {
        'BULL':     {'pm': 1.0, 'sm': 1.0, 'ae': True,  'max_pos': 8},
        'BULL_WK':  {'pm': 0.8, 'sm': 1.1, 'ae': True,  'max_pos': 6},
        'NEUTRAL':  {'pm': 0.7, 'sm': 1.2, 'ae': True,  'max_pos': 4},
        'BEAR_WK':  {'pm': 0.5, 'sm': 1.3, 'ae': True,  'max_pos': 2},
        'BEAR':     {'pm': 0.0, 'sm': 1.5, 'ae': False, 'max_pos': 0},
        'VOLATILE': {'pm': 0.4, 'sm': 1.5, 'ae': True,  'max_pos': 2},
    }

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.regime = 'NEUTRAL'
        self.score = 50
        self.details: dict = {}
        start = datetime.today() - timedelta(days=cfg.LOOKBACK + 100)
        self.n50  = IndexCache.get(cfg.NIFTY50,   start)
        self.n500 = IndexCache.get(cfg.NIFTY500,  start)
        self.mid  = IndexCache.get(cfg.MIDCAP150, start)
        log.info(f'Benchmarks loaded: n50={not self.n50.empty} '
                 f'n500={not self.n500.empty} mid={not self.mid.empty}')

    def detect(self) -> str:
        if self.n50.empty or len(self.n50) < 50:
            self.regime = 'NEUTRAL'
            return self.regime
        df = self.n50
        sc = 0
        det: dict = {}
        c = float(df['Close'].iloc[-1])
        ma50  = float(df['Close'].rolling(50).mean().iloc[-1])
        ma200 = float(df['Close'].rolling(200).mean().iloc[-1]) if len(df) >= 200 else ma50
        p = (15 if c > ma200 else 0) + (10 if c > ma50 else 0) + (10 if ma50 > ma200 else 0)
        sc += p; det['price_vs_ma'] = p
        ago = float(df['Close'].rolling(50).mean().iloc[-10]) if len(df) > 60 else ma50
        sl = (ma50 - ago) / ago if ago > 0 else 0
        ss = 15 if sl > 0.01 else (8 if sl > 0 else (3 if sl > -0.01 else 0))
        sc += ss; det['ma50_slope_pct'] = round(sl * 100, 3)
        r1 = (c / float(df['Close'].iloc[-21]) - 1) if len(df) > 21 else 0
        r3 = (c / float(df['Close'].iloc[-63]) - 1) if len(df) > 63 else 0
        ms = (10 if r1 > 0.03 else (5 if r1 > 0 else 0)) + \
             (10 if r3 > 0.05 else (5 if r3 > 0 else 0))
        sc += ms; det['ret_1m_pct'] = round(r1 * 100, 2); det['ret_3m_pct'] = round(r3 * 100, 2)
        bs = 0
        if not self.n500.empty and len(self.n500) >= 63:
            nr = float(self.n500['Close'].iloc[-1]) / float(self.n500['Close'].iloc[-63]) - 1
            bs = 15 if nr > 0.05 else (8 if nr > 0 else (3 if nr > -0.05 else 0))
            det['n500_3m_pct'] = round(nr * 100, 2)
        sc += bs
        h, l2, cl = df['High'], df['Low'], df['Close']
        tr = pd.concat([h - l2, (h - cl.shift()).abs(),
                        (l2 - cl.shift()).abs()], axis=1).max(axis=1)
        a14 = tr.rolling(14).mean().iloc[-1]
        a50 = tr.rolling(50).mean().iloc[-1] if len(df) >= 50 else a14
        vr = float(a14 / a50) if a50 > 0 else 1.0
        iv = vr > 1.5
        sc += (0 if iv else 15)
        det['vol_ratio'] = round(vr, 2)
        self.score = sc
        self.details = {**det, 'total': sc}
        if iv and sc < 60:
            self.regime = 'VOLATILE'
        elif sc >= 75:
            self.regime = 'BULL'
        elif sc >= 58:
            self.regime = 'BULL_WK'
        elif sc >= 42:
            self.regime = 'NEUTRAL'
        elif sc >= 25:
            self.regime = 'BEAR_WK'
        else:
            self.regime = 'BEAR'
        log.info(f'Regime: {self.regime} (score={sc})')
        return self.regime

    @property
    def p(self) -> dict:
        return self.RM.get(self.regime, self.RM['NEUTRAL'])

    def pos_mult(self) -> float:  return self.p['pm']
    def stop_mult(self) -> float: return self.p['sm']
    def allow_entry(self) -> bool: return self.p['ae']
    def max_positions(self) -> int: return self.p['max_pos']

    def nifty_close(self) -> float:
        return float(self.n50['Close'].iloc[-1]) if not self.n50.empty else 0.0

    def bench_for(self, avg_val: float) -> pd.DataFrame:
        if avg_val >= self.cfg.MIN_VAL_LARGE:
            return self.n50
        if avg_val >= self.cfg.MIN_VAL_MID:
            return self.n500 if not self.n500.empty else self.n50
        return self.mid if not self.mid.empty else (
            self.n500 if not self.n500.empty else self.n50)


# ══════════════════════════════════════════════════════════════════════
# TC MODEL + RISK MANAGER
# ══════════════════════════════════════════════════════════════════════
class TCModel:
    @staticmethod
    def calc(price: float, shares: int, cfg: Config, avg_val: float = 0) -> dict:
        tv = price * shares
        if tv == 0:
            return {'total_explicit': 0, 'slippage': 0, 'total_allin': 0, 'pct': 0}
        br = cfg.BROKERAGE_FLAT * 2
        st = tv * 2 * cfg.STT_DELIVERY_PCT
        ex = tv * 2 * cfg.EXCHANGE_CHARGES_PCT
        se = tv * 2 * cfg.SEBI_CHARGES_PCT
        sd = tv * cfg.STAMP_DUTY_PCT
        gst = (br + ex) * cfg.GST_RATE
        tot = br + st + ex + se + sd + gst
        sp = (cfg.SLIPPAGE_LARGE if avg_val >= cfg.MIN_VAL_LARGE else
              cfg.SLIPPAGE_MID   if avg_val >= cfg.MIN_VAL_MID   else
              cfg.SLIPPAGE_SMALL)
        slip = tv * sp * 2
        return {
            'total_explicit': round(tot, 2),
            'slippage': round(slip, 2),
            'total_allin': round(tot + slip, 2),
            'pct': round((tot + slip) / tv * 100, 3),
        }


class RiskManager:
    def __init__(self, cfg: Config, re: MarketRegimeEngine, db: MKKDatabase):
        self.cfg = cfg
        self.re = re
        self.db = db
        self._peak = cfg.TOTAL_CAPITAL

    def _streak(self) -> Tuple[int, int]:
        df = self.db.qdf(
            'SELECT pnl_net FROM paper_exits ORDER BY created_at DESC LIMIT 10')
        if df.empty:
            return 0, 0
        cl = cw = 0
        for pnl in df['pnl_net']:
            if pnl > 0:
                cl = 0; cw += 1
            else:
                cw = 0; cl += 1
            break
        return cl, cw

    def _loss_mult(self, cl: int) -> Tuple[float, str]:
        if cl >= self.cfg.LOSS_PAUSE_AT:  return 0.0, f'PAUSED ({cl} losses)'
        if cl >= self.cfg.LOSS_HALF_AT:   return 0.5, f'Half size ({cl} losses)'
        if cl >= self.cfg.LOSS_REDUCE_AT: return 0.75, f'Reduced ({cl} losses)'
        return 1.0, 'Normal'

    def kelly(self, wr: float, rr: float) -> float:
        return max(0.0, min((wr - (1 - wr) / rr) * 0.5, 0.25)) if rr > 0 else 0.0

    def min_score(self) -> int:
        cl, cw = self._streak()
        return self.cfg.MIN_SCORE_CONS if cl >= 3 or cw >= self.cfg.WIN_TIGHTEN_AT \
            else self.cfg.MIN_SCORE

    def size(self, capital: float, entry: float, stop: float,
             trade_type: str = 'SWING', avg_val: float = 0) -> dict:
        if entry <= 0 or stop <= 0 or entry <= stop:
            return {'shares': 0, 'invested': 0, 'reason': 'Invalid entry/stop'}
        rm = self.re.pos_mult()
        if rm == 0:
            return {'shares': 0, 'invested': 0, 'reason': 'Bear — blocked'}
        cl, _ = self._streak()
        lm, lr = self._loss_mult(cl)
        if lm == 0:
            return {'shares': 0, 'invested': 0, 'reason': lr}
        base = capital * self.cfg.MAX_RISK_PER_TRADE * rm * lm
        if trade_type == 'POSITIONAL':
            base *= 0.75
        rps = entry - stop
        raw = int(base / rps) if rps > 0 else 0
        perf = self.db.paper_perf_summary()
        if perf and perf.get('total', 0) >= 20:
            wr = perf['win_rate'] / 100
            arr = abs(perf['avg_win'] / perf['avg_loss']) \
                if perf.get('avg_loss') and perf['avg_loss'] != 0 else 2.0
            ks = int((capital * self.kelly(wr, arr)) / entry)
            if ks > 0:
                raw = min(raw, ks)
        cap_sh = int((capital * self.cfg.MAX_SINGLE_POS) / entry)
        # Liquidity stress: max 10% of daily volume
        daily_vol_shares = int(avg_val / entry) if entry > 0 else 0
        liq_max = int(daily_vol_shares * 0.10) if daily_vol_shares > 0 else raw
        sh = max(0, min(raw, cap_sh, liq_max if liq_max > 0 else raw))
        inv = sh * entry
        risk = sh * rps
        heat_ok = True
        cur_heat = self.db.paper_portfolio_heat()
        new_heat = cur_heat + risk / capital if capital > 0 else 0
        heat_cap = self.re.p.get('pm', 0.5) * 0.12   # approx
        if new_heat > self.cfg.heat_cap(self.re.regime):
            heat_ok = False
        tc = TCModel.calc(entry, sh, self.cfg, avg_val)
        return {
            'shares': sh, 'invested': round(inv, 2),
            'risk_amount': round(risk, 2),
            'risk_pct': round(risk / capital * 100, 2) if capital else 0,
            'heat_contrib': round(risk / capital, 4) if capital else 0,
            'pct_port': round(inv / capital * 100, 2) if capital else 0,
            'tc': tc, 'heat_ok': heat_ok,
            'portfolio_heat_after': round(new_heat * 100, 2),
            'cl': cl, 'loss_reason': lr, 'reason': 'OK',
        }

    def targets(self, entry: float, stop: float, tt: str) -> dict:
        r = entry - stop
        rr = self.cfg.POSITIONAL_RR if tt == 'POSITIONAL' else self.cfg.SWING_RR
        t1 = round(entry + 1.5 * r, 2)
        t2 = round(entry + 2.5 * r, 2)
        t3 = round(entry + rr * r, 2)
        if t3 <= t2:
            t3 = round(entry + max(rr, 3.0) * r, 2)
        return {'T1': t1, 'T2': t2, 'T3': t3, 'rps': round(r, 2)}


class PriorityScorer:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def compute(self, r: dict, sector_gate_open: bool) -> int:
        s = 0
        rk = r.get('RS_Rank', 0)
        s += 25 if rk >= 90 else (18 if rk >= 80 else (10 if rk >= 70 else 0))
        vq = r.get('VCP_Quality', 0); vc = r.get('Vol_Contraction', 1)
        s += (20 if vq > 60 else (13 if vq > 40 else (6 if vq > 20 else 0)))
        s += (-5 if vc > 0.60 else 0)
        s += 20 if sector_gate_open else 0
        dist = r.get('To_Resistance%', 99)
        s += 15 if dist < 1 else (10 if dist < 2 else (6 if dist < 3 else 0))
        ep = r.get('Price', 1); sl = r.get('Stop_Loss', 0); t3 = r.get('T3', 0)
        rr = (t3 - ep) / (ep - sl) if ep > sl and ep > 0 else 0
        s += (10 if rr >= 4 else (7 if rr >= 3 else (4 if rr >= 2 else 0)))
        av = r.get('Avg_Val', 0)
        s += (5 if av >= 100_000_000 else (3 if av >= 30_000_000 else
              (1 if av >= 10_000_000 else 0)))
        s += 0 if r.get('Near_Earnings') else 5
        return int(min(max(s, 0), 100))
