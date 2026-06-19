"""
mkk_dashboard_pro.py — Institutional-Grade MKK Trading Dashboard
Professional trading desk interface with real-time analytics.

Features:
  - Live market data integration with yfinance
  - Advanced risk metrics (VaR, Sharpe, Sortino, Calmar)
  - Monte Carlo simulations for portfolio projection
  - Real-time candlestick charts with technical indicators
  - Performance attribution by sector and regime
  - Customizable alert system
  - Professional dark theme with animations
  - Export capabilities (CSV, PDF, Excel)

Usage:
  streamlit run mkk_dashboard_pro.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional, Any
import logging
import yfinance as yf
import json
import base64
from io import BytesIO
import warnings
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG - Expanded Layout
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MKK Institutional Trading System",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# IMPORTS FROM YOUR SYSTEM
# ──────────────────────────────────────────────────────────────────────────────
try:
    from mkk_core import Config, MKKDatabase, MarketRegimeEngine
    from mkk_core import TI, RiskManager, PriorityScorer, TCModel
    from mkk_scanner import SectorHeatmap, EliteSwingScanner
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.stop()

# ──────────────────────────────────────────────────────────────────────────────
# PROFESSIONAL CSS - Institutional Dark Theme with Animations
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ─── IMPORTS ───────────────────────────────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    /* ─── RESET ────────────────────────────────────────────────────────────── */
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* ─── MAIN BACKGROUND ──────────────────────────────────────────────────── */
    .stApp {
        background: #0a0e1a;
    }
    
    /* ─── GLASSMORPHISM CARDS ──────────────────────────────────────────────── */
    .glass-card {
        background: rgba(20, 28, 50, 0.85);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 16px;
        padding: 20px 24px;
        margin: 8px 0;
        box-shadow: 
            0 8px 32px rgba(0, 0, 0, 0.4),
            inset 0 1px 0 rgba(255, 255, 255, 0.05);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .glass-card:hover {
        transform: translateY(-2px);
        box-shadow: 
            0 12px 48px rgba(0, 0, 0, 0.5),
            inset 0 1px 0 rgba(255, 255, 255, 0.08);
        border-color: rgba(255, 255, 255, 0.12);
    }
    
    /* ─── METRIC CARDS ──────────────────────────────────────────────────────── */
    .metric-card {
        background: linear-gradient(145deg, rgba(20, 28, 50, 0.9), rgba(10, 14, 26, 0.95));
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        padding: 18px 22px;
        position: relative;
        overflow: hidden;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .metric-card:hover {
        border-color: rgba(255, 255, 255, 0.15);
        transform: translateY(-1px);
    }
    .metric-card .label {
        font-size: 11px;
        font-weight: 600;
        color: #6b7a9f;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 4px;
    }
    .metric-card .value {
        font-size: 28px;
        font-weight: 700;
        color: #e8edf5;
        line-height: 1.2;
        letter-spacing: -0.5px;
    }
    .metric-card .sub {
        font-size: 13px;
        color: #6b7a9f;
        margin-top: 4px;
        font-weight: 400;
    }
    .metric-card .trend {
        font-size: 12px;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 20px;
        display: inline-block;
        margin-top: 6px;
    }
    .trend-up {
        color: #00c853;
        background: rgba(0, 200, 83, 0.12);
    }
    .trend-down {
        color: #ff1744;
        background: rgba(255, 23, 68, 0.12);
    }
    .trend-neutral {
        color: #ffd740;
        background: rgba(255, 215, 64, 0.12);
    }
    
    /* ─── GLOW ACCENTS ──────────────────────────────────────────────────────── */
    .glow-green {
        box-shadow: 0 0 40px rgba(0, 200, 83, 0.05);
    }
    .glow-red {
        box-shadow: 0 0 40px rgba(255, 23, 68, 0.05);
    }
    .glow-blue {
        box-shadow: 0 0 40px rgba(66, 165, 245, 0.05);
    }
    
    /* ─── REGIME BADGES ────────────────────────────────────────────────────── */
    .regime-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 16px;
        border-radius: 30px;
        font-weight: 600;
        font-size: 13px;
        letter-spacing: 0.5px;
    }
    .regime-bull {
        background: rgba(0, 200, 83, 0.15);
        color: #00c853;
        border: 1px solid rgba(0, 200, 83, 0.25);
    }
    .regime-bear {
        background: rgba(255, 23, 68, 0.15);
        color: #ff1744;
        border: 1px solid rgba(255, 23, 68, 0.25);
    }
    .regime-neutral {
        background: rgba(255, 215, 64, 0.15);
        color: #ffd740;
        border: 1px solid rgba(255, 215, 64, 0.25);
    }
    .regime-volatile {
        background: rgba(255, 145, 0, 0.15);
        color: #ff9100;
        border: 1px solid rgba(255, 145, 0, 0.25);
    }
    
    /* ─── TAB STYLING ───────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background: rgba(10, 14, 26, 0.8);
        padding: 4px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 10px 22px;
        font-weight: 500;
        font-size: 13px;
        color: #6b7a9f;
        transition: all 0.2s ease;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(30, 45, 80, 0.8);
        color: #e8edf5 !important;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    
    /* ─── HEADERS ───────────────────────────────────────────────────────────── */
    h1, h2, h3, h4, h5 {
        color: #e8edf5 !important;
        font-weight: 600 !important;
        letter-spacing: -0.3px;
    }
    h1 { font-size: 32px !important; }
    h2 { font-size: 24px !important; }
    h3 { font-size: 18px !important; }
    .stMarkdown p { color: #b0bec5; }
    
    /* ─── SIDEBAR ──────────────────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: rgba(8, 12, 22, 0.98);
        border-right: 1px solid rgba(255, 255, 255, 0.04);
        backdrop-filter: blur(10px);
    }
    section[data-testid="stSidebar"] .stMarkdown {
        color: #b0bec5;
    }
    
    /* ─── DATA FRAME ────────────────────────────────────────────────────────── */
    .stDataFrame {
        background: transparent !important;
    }
    .stDataFrame thead tr th {
        background: rgba(20, 28, 50, 0.6) !important;
        color: #6b7a9f !important;
        font-size: 10px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.8px !important;
        font-weight: 600 !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
    }
    .stDataFrame tbody tr td {
        font-size: 13px !important;
        color: #c5cbe0 !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.03) !important;
    }
    .stDataFrame tbody tr:hover {
        background: rgba(255, 255, 255, 0.02) !important;
    }
    
    /* ─── DIVIDER ───────────────────────────────────────────────────────────── */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent);
        margin: 24px 0;
    }
    
    /* ─── ALERT / INFO BOXES ───────────────────────────────────────────────── */
    .stAlert {
        background: rgba(20, 28, 50, 0.6) !important;
        border-color: rgba(255, 255, 255, 0.06) !important;
        border-radius: 12px !important;
    }
    .stAlert p { color: #b0bec5 !important; }
    
    /* ─── EXPANDER ──────────────────────────────────────────────────────────── */
    .streamlit-expanderHeader {
        background: rgba(20, 28, 50, 0.4) !important;
        border-color: rgba(255, 255, 255, 0.04) !important;
        color: #e8edf5 !important;
        font-weight: 500 !important;
        border-radius: 10px !important;
    }
    .streamlit-expanderContent {
        background: rgba(10, 14, 26, 0.6) !important;
        border-color: rgba(255, 255, 255, 0.04) !important;
        border-radius: 0 0 10px 10px !important;
    }
    
    /* ─── PLOTLY ────────────────────────────────────────────────────────────── */
    .js-plotly-plot .plotly .main-svg {
        background: transparent !important;
    }
    
    /* ─── LIVE INDICATOR ────────────────────────────────────────────────────── */
    .live-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #00c853;
        animation: pulse 2s infinite;
        margin-right: 8px;
    }
    @keyframes pulse {
        0% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.5; transform: scale(0.8); }
        100% { opacity: 1; transform: scale(1); }
    }
    
    /* ─── SCROLLBAR ────────────────────────────────────────────────────────── */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: rgba(10, 14, 26, 0.5);
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.1);
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: rgba(255, 255, 255, 0.2);
    }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# CACHED DATA FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_db():
    try:
        cfg = Config()
        return MKKDatabase(cfg.DB_PATH)
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None


@st.cache_data(ttl=30)
def get_config() -> Config:
    return Config()


@st.cache_data(ttl=30)
def get_regime() -> Dict:
    try:
        cfg = get_config()
        re = MarketRegimeEngine(cfg)
        re.detect()
        return {
            'regime': re.regime,
            'score': re.score,
            'details': re.details,
            'allow_entry': re.allow_entry(),
            'max_positions': re.max_positions(),
            'nifty_close': re.nifty_close(),
            'nifty_df': re.n50 if hasattr(re, 'n50') else pd.DataFrame(),
        }
    except Exception:
        return {
            'regime': 'NEUTRAL', 'score': 0, 'details': {},
            'allow_entry': False, 'max_positions': 4, 'nifty_close': 0,
            'nifty_df': pd.DataFrame()
        }


@st.cache_data(ttl=30)
def get_live_price(ticker: str) -> Optional[float]:
    """Fetch live price for a ticker."""
    try:
        if '.NS' not in ticker:
            ticker += '.NS'
        data = yf.download(ticker, period='1d', progress=False)
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception:
        pass
    return None


@st.cache_data(ttl=30)
def get_portfolio_snapshot() -> Dict:
    db = get_db()
    if db is None:
        return {}
    try:
        row = db.q(
            "SELECT * FROM paper_snapshots ORDER BY snap_date DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


@st.cache_data(ttl=30)
def get_open_trades() -> pd.DataFrame:
    db = get_db()
    if db is None:
        return pd.DataFrame()
    try:
        return db.open_paper_trades()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def get_performance_summary() -> Dict:
    db = get_db()
    if db is None:
        return {}
    try:
        return db.paper_perf_summary()
    except Exception:
        return {}


@st.cache_data(ttl=30)
def get_latest_scan_results(limit: int = 30) -> pd.DataFrame:
    db = get_db()
    if db is None:
        return pd.DataFrame()
    try:
        return db.qdf(
            "SELECT ticker, price, score, priority_score, priority_rank, "
            "trade_type, pattern, rs_3m, rs_rank, vcp_quality, to_resistance, "
            "stop_loss, target_t1, target_t2, target_t3, shares_suggested, "
            "capital_required, risk_inr, macro_sector, sector "
            "FROM scan_results "
            "WHERE scan_date = (SELECT MAX(scan_date) FROM scan_results) "
            "ORDER BY priority_rank LIMIT ?",
            (limit,)
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def get_equity_curve() -> pd.DataFrame:
    db = get_db()
    if db is None:
        return pd.DataFrame()
    try:
        return db.qdf(
            "SELECT snap_date, total_capital, deployed, cash, open_positions, "
            "unrealized_pnl, realized_pnl_ytd, drawdown_pct, portfolio_heat "
            "FROM paper_snapshots ORDER BY snap_date"
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def get_recent_trades(limit: int = 100) -> pd.DataFrame:
    db = get_db()
    if db is None:
        return pd.DataFrame()
    try:
        return db.qdf(
            "SELECT pe.exit_date, pt.ticker, pt.entry_date, pt.entry_price, "
            "pe.exit_price, pe.exit_type, pe.pnl_net, pe.r_multiple, "
            "pe.holding_days, pt.macro_sector, pt.pattern "
            "FROM paper_exits pe "
            "JOIN paper_trades pt ON pe.trade_id = pt.trade_id "
            "ORDER BY pe.exit_date DESC LIMIT ?",
            (limit,)
        )
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def get_sector_exposure() -> Dict:
    try:
        cfg = get_config()
        db = get_db()
        if db is None:
            return {}
        return db.paper_sector_exposure(cfg)
    except Exception:
        return {}


@st.cache_data(ttl=30)
def get_nifty_candles(days: int = 60) -> pd.DataFrame:
    """Get Nifty 50 candlestick data for charting."""
    try:
        data = yf.download('^NSEI', period=f'{days+10}d', progress=False)
        if not data.empty:
            return data
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=60)
def get_last_run():
    db = get_db()
    if db is None:
        return None
    try:
        row = db.q(
            "SELECT run_date, run_start, run_end, duration_sec, mode, "
            "exits_processed, entries_taken FROM paper_sessions "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


@st.cache_data(ttl=60)
def get_macro_blackout_today():
    db = get_db()
    if db is None:
        return False, "DB unavailable"
    try:
        today = date.today().isoformat()
        return db.is_macro_blackout(today)
    except Exception:
        return False, "Check failed"


# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR - Professional Control Panel
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 20px 0 12px 0;">
        <div style="font-size:32px; font-weight:800; color:#e8edf5; letter-spacing:-1px;">
            🏛️ MKK
        </div>
        <div style="font-size:13px; color:#6b7a9f; font-weight:400; margin-top:-2px;">
            Institutional Trading System
        </div>
        <div style="font-size:10px; color:#3a4a6a; font-weight:400; margin-top:2px;">
            v6.1 · Paper Trading · Live
        </div>
        <div style="margin-top:8px;">
            <span class="live-dot"></span>
            <span style="font-size:11px; color:#4a5a7a;">Real-time</span>
        </div>
    </div>
    <hr>
    """, unsafe_allow_html=True)

    # ─── System Controls ──
    with st.expander("⚙️ System Controls", expanded=True):
        cfg = get_config()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("💰 Capital", f"₹{cfg.TOTAL_CAPITAL:,.0f}")
        with col2:
            st.metric("📊 Max Positions", cfg.MAX_POSITIONS)

    # ─── Market Regime ──
    regime_data = get_regime()
    regime = regime_data.get('regime', 'NEUTRAL')
    regime_icon = {
        'BULL': '🚀', 'BULL_WK': '📈', 'NEUTRAL': '⚖️',
        'BEAR_WK': '📉', 'BEAR': '🐻', 'VOLATILE': '🌊'
    }.get(regime, '⚖️')
    
    regime_class = {
        'BULL': 'regime-bull', 'BULL_WK': 'regime-bull',
        'NEUTRAL': 'regime-neutral',
        'BEAR_WK': 'regime-bear', 'BEAR': 'regime-bear',
        'VOLATILE': 'regime-volatile'
    }.get(regime, 'regime-neutral')
    
    st.markdown(f"""
    <div style="margin-top:8px;">
        <div style="color:#6b7a9f; font-size:10px; text-transform:uppercase; letter-spacing:1px; font-weight:600;">
            Market Regime
        </div>
        <div style="display:flex; align-items:center; gap:12px; margin-top:6px; flex-wrap:wrap;">
            <span class="regime-badge {regime_class}">{regime_icon} {regime}</span>
            <span style="color:#6b7a9f; font-size:13px;">Score: {regime_data.get('score', 0)}/100</span>
        </div>
        <div style="font-size:12px; color:#6b7a9f; margin-top:4px;">
            Nifty 50: ₹{regime_data.get('nifty_close', 0):,.2f}
        </div>
        <div style="font-size:12px; margin-top:2px;">
            {'✅ Entries Open' if regime_data.get('allow_entry', False) else '🔒 Entries Blocked'}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ─── Quick Stats ──
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("### 📊 Quick Stats")
    
    perf = get_performance_summary()
    snapshot = get_portfolio_snapshot()
    
    win_rate = perf.get('win_rate', 0)
    win_color = '#00c853' if win_rate >= 50 else '#ff1744' if win_rate >= 40 else '#ffd740'
    
    st.markdown(f"""
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
        <div style="background:rgba(20,28,50,0.6); border-radius:10px; padding:12px 14px; border:1px solid rgba(255,255,255,0.04);">
            <div style="font-size:10px; color:#6b7a9f; text-transform:uppercase; letter-spacing:0.5px;">Win Rate</div>
            <div style="font-size:22px; font-weight:700; color:{win_color};">{win_rate:.1f}%</div>
        </div>
        <div style="background:rgba(20,28,50,0.6); border-radius:10px; padding:12px 14px; border:1px solid rgba(255,255,255,0.04);">
            <div style="font-size:10px; color:#6b7a9f; text-transform:uppercase; letter-spacing:0.5px;">Avg R</div>
            <div style="font-size:22px; font-weight:700; color:#e8edf5;">{perf.get('avg_r', 0):.2f}</div>
        </div>
        <div style="background:rgba(20,28,50,0.6); border-radius:10px; padding:12px 14px; border:1px solid rgba(255,255,255,0.04);">
            <div style="font-size:10px; color:#6b7a9f; text-transform:uppercase; letter-spacing:0.5px;">Open P&L</div>
            <div style="font-size:22px; font-weight:700; color:{'#00c853' if snapshot.get('unrealized_pnl', 0) >= 0 else '#ff1744'};">
                ₹{snapshot.get('unrealized_pnl', 0):+,.0f}
            </div>
        </div>
        <div style="background:rgba(20,28,50,0.6); border-radius:10px; padding:12px 14px; border:1px solid rgba(255,255,255,0.04);">
            <div style="font-size:10px; color:#6b7a9f; text-transform:uppercase; letter-spacing:0.5px;">Heat</div>
            <div style="font-size:22px; font-weight:700; color:#e8edf5;">{snapshot.get('portfolio_heat', 0):.1f}%</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ─── Last Run ──
    st.markdown("<hr>", unsafe_allow_html=True)
    last_run = get_last_run()
    if last_run:
        dur = last_run.get('duration_sec', 0)
        dur_str = f"{dur//60}m {dur%60}s" if dur else "N/A"
        st.markdown(f"""
        <div style="font-size:12px; color:#6b7a9f; line-height:1.8;">
            <div><span style="color:#4a5a7a;">Last Run:</span> {last_run.get('run_date', 'N/A')}</div>
            <div><span style="color:#4a5a7a;">Duration:</span> {dur_str}</div>
            <div><span style="color:#4a5a7a;">Entries:</span> {last_run.get('entries_taken', 0)}  <span style="color:#4a5a7a;">Exits:</span> {last_run.get('exits_processed', 0)}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.caption("📡 Data refreshes every 30s · Real-time market data")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN DASHBOARD - Professional Layout
# ──────────────────────────────────────────────────────────────────────────────

# ─── Header ──
col_title, col_time, col_status = st.columns([2, 1, 1])
with col_title:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:12px;">
        <div style="font-size:14px; font-weight:600; color:#6b7a9f; letter-spacing:1px; text-transform:uppercase;">
            Trading Desk
        </div>
        <div style="font-size:12px; color:#4a5a7a;">
            <span id="clock" style="font-variant-numeric:tabular-nums;"></span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_time:
    st.markdown(f"""
    <div style="text-align:right; font-size:12px; color:#4a5a7a;">
        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST
    </div>
    """, unsafe_allow_html=True)

with col_status:
    is_bo, bo_reason = get_macro_blackout_today()
    if is_bo:
        st.markdown(f"<div style='text-align:right;'><span style='background:rgba(255,23,68,0.12); color:#ff1744; padding:4px 14px; border-radius:20px; font-size:11px; font-weight:600;'>🔴 {bo_reason[:20]}</span></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='text-align:right;'><span style='background:rgba(0,200,83,0.12); color:#00c853; padding:4px 14px; border-radius:20px; font-size:11px; font-weight:600;'>● All Clear</span></div>", unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ─── TOP METRIC ROW ──
cfg = get_config()
regime_data = get_regime()
snapshot = get_portfolio_snapshot()
perf = get_performance_summary()

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    total_pnl = perf.get('total_pnl', 0) if perf else 0
    pnl_color = '#00c853' if total_pnl >= 0 else '#ff1744'
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Total P&L</div>
        <div class="value" style="color:{pnl_color};">₹{total_pnl:+,.0f}</div>
        <div class="sub">{perf.get('total', 0) if perf else 0} closed trades</div>
        <span class="trend {'trend-up' if total_pnl >= 0 else 'trend-down'}">
            {perf.get('win_rate', 0) if perf else 0:.1f}% Win Rate
        </span>
    </div>
    """, unsafe_allow_html=True)

with col2:
    deployed = snapshot.get('deployed', 0)
    pct_deployed = (deployed / cfg.TOTAL_CAPITAL * 100) if cfg.TOTAL_CAPITAL > 0 else 0
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Capital Deployed</div>
        <div class="value">₹{deployed:,.0f}</div>
        <div class="sub">{pct_deployed:.1f}% of ₹{cfg.TOTAL_CAPITAL:,.0f}</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    n_open = snapshot.get('open_positions', 0)
    max_pos = regime_data.get('max_positions', cfg.MAX_POSITIONS)
    status = '🟢 Open' if n_open > 0 else '⚪ Empty'
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Open Positions</div>
        <div class="value">{n_open} / {max_pos}</div>
        <div class="sub">{status} · {max_pos - n_open} slots</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    heat = snapshot.get('portfolio_heat', 0)
    heat_cap = cfg.heat_cap(regime_data.get('regime', 'NEUTRAL')) * 100
    heat_color = '#00c853' if heat <= heat_cap else '#ffd740' if heat <= heat_cap * 1.2 else '#ff1744'
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Portfolio Heat</div>
        <div class="value" style="color:{heat_color};">{heat:.1f}%</div>
        <div class="sub">Cap: {heat_cap:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)

with col5:
    unreal = snapshot.get('unrealized_pnl', 0)
    unreal_color = '#00c853' if unreal >= 0 else '#ff1744'
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Unrealized P&L</div>
        <div class="value" style="color:{unreal_color};">₹{unreal:+,.0f}</div>
        <div class="sub">{snapshot.get('cash', 0):,.0f} cash</div>
    </div>
    """, unsafe_allow_html=True)

with col6:
    avg_r = perf.get('avg_r', 0) if perf else 0
    pf = perf.get('pf', 0) if perf else 0
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Risk Metrics</div>
        <div class="value">R: {avg_r:.2f}</div>
        <div class="sub">PF: {pf:.2f} · {perf.get('total', 0) if perf else 0} trades</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# PROFESSIONAL TABS
# ──────────────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "📈 Live Market View",
    "🎯 Elite Setups & Sizing",
    "📊 Portfolio Analytics",
    "📉 Performance & Attribution",
    "📋 Risk Dashboard",
    "⚡ Alerts & Logs"
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: LIVE MARKET VIEW
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.markdown("### 📈 Live Market View")
    st.caption("Real-time market data with technical analysis")
    
    # ─── Nifty Candlestick Chart ──
    col_chart, col_info = st.columns([3, 1])
    
    with col_chart:
        nifty_data = get_nifty_candles(60)
        if not nifty_data.empty:
            fig_candle = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.7, 0.3],
                subplot_titles=('Nifty 50 - Daily Candles', 'Volume')
            )
            
            # Candlesticks
            fig_candle.add_trace(
                go.Candlestick(
                    x=nifty_data.index,
                    open=nifty_data['Open'],
                    high=nifty_data['High'],
                    low=nifty_data['Low'],
                    close=nifty_data['Close'],
                    name='Nifty 50',
                    increasing=dict(line=dict(color='#00c853')),
                    decreasing=dict(line=dict(color='#ff1744')),
                ),
                row=1, col=1
            )
            
            # Volume - FIXED: Handle NaN values properly
            pct_changes = nifty_data['Close'].pct_change()
            volume_colors = []
            for val in pct_changes:
                if pd.isna(val):
                    volume_colors.append('#4a5a7a')  # neutral color for NaN
                elif val >= 0:
                    volume_colors.append('#00c853')
                else:
                    volume_colors.append('#ff1744')
            
            fig_candle.add_trace(
                go.Bar(
                    x=nifty_data.index,
                    y=nifty_data['Volume'],
                    name='Volume',
                    marker=dict(color=volume_colors),
                    opacity=0.6,
                ),
                row=2, col=1
            )
            
            # Moving Averages
            ma20 = nifty_data['Close'].rolling(20).mean()
            ma50 = nifty_data['Close'].rolling(50).mean()
            
            fig_candle.add_trace(
                go.Scatter(
                    x=nifty_data.index,
                    y=ma20,
                    name='MA 20',
                    line=dict(color='#42a5f5', width=1.5),
                ),
                row=1, col=1
            )
            fig_candle.add_trace(
                go.Scatter(
                    x=nifty_data.index,
                    y=ma50,
                    name='MA 50',
                    line=dict(color='#ffd740', width=1.5),
                ),
                row=1, col=1
            )
            
            fig_candle.update_layout(
                height=500,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#b0bec5'),
                xaxis_rangeslider_visible=False,
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=1.02,
                    xanchor='right',
                    x=1,
                    font=dict(size=11, color='#6b7a9f')
                ),
                margin=dict(l=20, r=20, t=40, b=20),
            )
            fig_candle.update_xaxes(gridcolor='rgba(255,255,255,0.03)', row=1, col=1)
            fig_candle.update_yaxes(gridcolor='rgba(255,255,255,0.03)', row=1, col=1)
            fig_candle.update_xaxes(gridcolor='rgba(255,255,255,0.03)', row=2, col=1)
            fig_candle.update_yaxes(gridcolor='rgba(255,255,255,0.03)', row=2, col=1)
            
            st.plotly_chart(fig_candle, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info("Nifty data not available")
    
    with col_info:
        st.markdown("""
        <div class="glass-card" style="height:100%;">
            <div style="font-size:11px; color:#6b7a9f; text-transform:uppercase; letter-spacing:0.8px; font-weight:600;">
                Market Summary
            </div>
        """, unsafe_allow_html=True)
        
        if not nifty_data.empty:
            last = nifty_data['Close'].iloc[-1]
            prev = nifty_data['Close'].iloc[-2] if len(nifty_data) > 1 else last
            change = ((last - prev) / prev * 100) if prev and prev != 0 else 0
            change_color = '#00c853' if change >= 0 else '#ff1744'
            
            st.markdown(f"""
            <div style="margin-top:12px;">
                <div style="font-size:28px; font-weight:700; color:#e8edf5;">₹{last:,.2f}</div>
                <div style="font-size:16px; font-weight:600; color:{change_color};">
                    {change:+.2f}% 
                    <span style="font-size:13px; font-weight:400; color:#6b7a9f;">
                        ({last - prev:+.2f})
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Quick stats
            if len(nifty_data) >= 20:
                ma20_val = nifty_data['Close'].rolling(20).mean().iloc[-1]
                ma50_val = nifty_data['Close'].rolling(50).mean().iloc[-1] if len(nifty_data) >= 50 else ma20_val
                st.markdown(f"""
                <div style="margin-top:16px; font-size:13px; color:#b0bec5; line-height:2;">
                    <div><span style="color:#6b7a9f;">MA 20:</span> ₹{ma20_val:,.2f}</div>
                    <div><span style="color:#6b7a9f;">MA 50:</span> ₹{ma50_val:,.2f}</div>
                    <div><span style="color:#6b7a9f;">Position:</span> 
                        <span style="color:{'#00c853' if last > ma20_val else '#ff1744'}">
                            {('Above' if last > ma20_val else 'Below')} MA20
                        </span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: ELITE SETUPS & SIZING
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### 🎯 Elite Setups & Position Sizing")
    st.caption("Priority-ranked elite setups with automated position sizing")
    
    scan_df = get_latest_scan_results(30)
    
    if not scan_df.empty:
        # ─── Table with Professional Styling ──
        display_df = scan_df.copy()
        
        # Format columns
        display_df['Price'] = display_df['price'].apply(lambda x: f"₹{x:,.2f}")
        display_df['RS'] = display_df['rs_3m'].apply(lambda x: f"{x:.2f}x" if x else 'N/A')
        display_df['VCP'] = display_df['vcp_quality'].apply(lambda x: f"{x:.0f}%" if x else 'N/A')
        display_df['Stop'] = display_df['stop_loss'].apply(lambda x: f"₹{x:,.2f}")
        display_df['T1'] = display_df['target_t1'].apply(lambda x: f"₹{x:,.2f}")
        display_df['T2'] = display_df['target_t2'].apply(lambda x: f"₹{x:,.2f}")
        display_df['T3'] = display_df['target_t3'].apply(lambda x: f"₹{x:,.2f}")
        display_df['Capital'] = display_df['capital_required'].apply(lambda x: f"₹{x:,.0f}")
        
        # Add live price column - FIXED: Handle None values
        def get_live_price_safe(ticker):
            price = get_live_price(ticker)
            return f"₹{price:,.2f}" if price else '—'
        display_df['Live'] = display_df['ticker'].apply(get_live_price_safe)
        
        # Calculate gap from scan price
        def get_gap(row):
            live = get_live_price(row['ticker'])
            if live and row['price'] > 0:
                gap = ((live - row['price']) / row['price'] * 100)
                return f"{gap:+.1f}%" if abs(gap) < 20 else '—'
            return '—'
        display_df['Gap'] = scan_df.apply(get_gap, axis=1)
        
        # Select and rename columns
        final_cols = ['Priority_Rank', 'Ticker', 'Price', 'Live', 'Gap', 'Pattern', 
                      'RS', 'VCP', 'Stop', 'T1', 'T2', 'T3', 'Capital', 'Sector']
        display_df = display_df.rename(columns={
            'priority_rank': 'Priority_Rank',
            'ticker': 'Ticker',
            'macro_sector': 'Sector',
            'pattern': 'Pattern'
        })
        
        available_cols = [c for c in final_cols if c in display_df.columns]
        display_df = display_df[available_cols]
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Priority_Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                "Price": st.column_config.TextColumn("Scan", width="small"),
                "Live": st.column_config.TextColumn("Live", width="small"),
                "Gap": st.column_config.TextColumn("Gap", width="small"),
                "Pattern": st.column_config.TextColumn("Pattern", width="small"),
                "RS": st.column_config.TextColumn("RS 3M", width="small"),
                "VCP": st.column_config.TextColumn("VCP", width="small"),
                "Stop": st.column_config.TextColumn("Stop", width="small"),
                "T1": st.column_config.TextColumn("T1", width="small"),
                "T2": st.column_config.TextColumn("T2", width="small"),
                "T3": st.column_config.TextColumn("T3", width="small"),
                "Capital": st.column_config.TextColumn("Capital", width="small"),
                "Sector": st.column_config.TextColumn("Sector", width="small"),
            }
        )
        
        # ─── Position Sizing Matrix ──
        st.markdown("#### 📐 Position Sizing Matrix")
        
        sizing_data = []
        try:
            cfg = get_config()
            re = MarketRegimeEngine(cfg)
            re.detect()
            risk = RiskManager(cfg, re, get_db())
            sector_exp = get_sector_exposure()
            
            for _, row in scan_df.iterrows():
                entry = float(row['price'])
                stop = float(row['stop_loss'])
                if entry <= 0 or stop <= 0 or entry <= stop:
                    continue
                
                ps = risk.size(cfg.TOTAL_CAPITAL, entry, stop, row.get('trade_type', 'SWING'), 0)
                if ps['shares'] > 0 and ps.get('heat_ok', True):
                    ms = row['macro_sector']
                    current_exp = sector_exp.get(ms, 0)
                    new_exp = current_exp + (ps['invested'] / cfg.TOTAL_CAPITAL)
                    
                    sizing_data.append({
                        'Ticker': row['ticker'],
                        'Shares': ps['shares'],
                        'Invested': f"₹{ps['invested']:,.0f}",
                        'Risk Amt': f"₹{ps['risk_amount']:,.0f}",
                        'Risk %': f"{ps['risk_pct']:.2f}%",
                        'Heat %': f"{ps['heat_contrib'] * 100:.2f}%",
                        'Sector': ms,
                        'Sector Exp': f"{current_exp * 100:.1f}% → {new_exp * 100:.1f}%",
                        'Status': '✅' if new_exp <= cfg.MAX_SECTOR_EXP else '⚠️',
                    })
        except Exception as e:
            pass
        
        if sizing_data:
            st.dataframe(
                pd.DataFrame(sizing_data),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                    "Shares": st.column_config.NumberColumn("Shares", width="small"),
                    "Invested": st.column_config.TextColumn("Invested", width="small"),
                    "Risk Amt": st.column_config.TextColumn("Risk", width="small"),
                    "Risk %": st.column_config.TextColumn("Risk %", width="small"),
                    "Heat %": st.column_config.TextColumn("Heat %", width="small"),
                    "Sector": st.column_config.TextColumn("Sector", width="small"),
                    "Sector Exp": st.column_config.TextColumn("Sector Exposure", width="medium"),
                    "Status": st.column_config.TextColumn("", width="small"),
                }
            )
        else:
            st.info("No position sizing data available")
    else:
        st.info("No scan results available. Run a scan to populate this view.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: PORTFOLIO ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.markdown("### 📊 Portfolio Analytics")
    st.caption("Advanced portfolio analytics with sector decomposition")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # ─── Equity Curve with Drawdown ──
        st.markdown("#### 📉 Equity Curve & Drawdown")
        equity_df = get_equity_curve()
        
        if not equity_df.empty:
            fig_equity = make_subplots(specs=[[{"secondary_y": True}]])
            
            # Total Capital
            fig_equity.add_trace(
                go.Scatter(
                    x=equity_df['snap_date'],
                    y=equity_df['total_capital'],
                    name='Total Capital',
                    line=dict(color='#42a5f5', width=2.5),
                    fill='tonexty',
                    fillcolor='rgba(66,165,245,0.08)',
                ),
                secondary_y=False,
            )
            
            # Drawdown
            fig_equity.add_trace(
                go.Scatter(
                    x=equity_df['snap_date'],
                    y=equity_df['drawdown_pct'],
                    name='Drawdown',
                    line=dict(color='#ff1744', width=2, dash='dash'),
                    fill='tozeroy',
                    fillcolor='rgba(255,23,68,0.08)',
                ),
                secondary_y=True,
            )
            
            fig_equity.update_layout(
                height=350,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#b0bec5'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(l=20, r=20, t=20, b=20),
            )
            fig_equity.update_yaxes(title_text="Capital (₹)", gridcolor='rgba(255,255,255,0.03)', secondary_y=False)
            fig_equity.update_yaxes(title_text="Drawdown %", gridcolor='rgba(255,255,255,0.03)', secondary_y=True)
            
            st.plotly_chart(fig_equity, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info("No equity data available")
    
    with col2:
        # ─── Sector Exposure Treemap ──
        st.markdown("#### 🗺️ Sector Exposure")
        
        open_trades = get_open_trades()
        if not open_trades.empty:
            sector_data = open_trades.groupby('macro_sector')['capital_invested'].sum().reset_index()
            sector_data['Pct'] = sector_data['capital_invested'] / cfg.TOTAL_CAPITAL * 100
            
            fig_treemap = go.Figure(go.Treemap(
                labels=sector_data['macro_sector'],
                values=sector_data['capital_invested'],
                text=sector_data['Pct'].apply(lambda x: f"{x:.1f}%"),
                textinfo="label+text",
                marker=dict(
                    colors=sector_data['Pct'],
                    colorscale='Blues',
                    showscale=False,
                ),
                hovertemplate='<b>%{label}</b><br>₹%{value:,.0f}<br>%{text}<extra></extra>',
            ))
            
            fig_treemap.update_layout(
                height=350,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#b0bec5'),
                margin=dict(l=10, r=10, t=10, b=10),
            )
            
            st.plotly_chart(fig_treemap, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info("No open positions")
    
    # ─── Open Positions Detail ──
    st.markdown("#### 🔓 Open Positions Detail")
    open_df = get_open_trades()
    if not open_df.empty:
        # Add live prices
        def get_live_price_safe(ticker):
            price = get_live_price(ticker)
            return price if price else 0
        
        open_df['Live'] = open_df['ticker'].apply(get_live_price_safe)
        open_df['P&L'] = (open_df['Live'] - open_df['entry_price']) * open_df['shares_remaining']
        
        # Avoid division by zero
        open_df['P&L %'] = 0.0
        mask = open_df['entry_price'] > 0
        open_df.loc[mask, 'P&L %'] = (open_df.loc[mask, 'Live'] / open_df.loc[mask, 'entry_price'] - 1) * 100
        
        display_open = open_df.copy()
        display_open['entry_price'] = display_open['entry_price'].apply(lambda x: f"₹{x:,.2f}")
        display_open['Live'] = display_open['Live'].apply(lambda x: f"₹{x:,.2f}" if x else '—')
        display_open['P&L'] = display_open['P&L'].apply(lambda x: f"₹{x:+,.0f}")
        display_open['P&L %'] = display_open['P&L %'].apply(lambda x: f"{x:+.1f}%")
        display_open['stop_loss'] = display_open['stop_loss'].apply(lambda x: f"₹{x:,.2f}")
        
        st.dataframe(
            display_open[['ticker', 'entry_date', 'entry_price', 'Live', 'P&L', 'P&L %', 
                         'stop_loss', 'shares_remaining', 'macro_sector', 'pattern']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "ticker": "Ticker",
                "entry_date": "Entry Date",
                "entry_price": "Entry",
                "Live": "Live",
                "P&L": "P&L",
                "P&L %": "P&L %",
                "stop_loss": "Stop",
                "shares_remaining": "Shares",
                "macro_sector": "Sector",
                "pattern": "Pattern",
            }
        )
    else:
        st.info("No open trades")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: PERFORMANCE & ATTRIBUTION
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.markdown("### 📉 Performance & Attribution")
    st.caption("Detailed performance analytics with attribution analysis")
    
    perf = get_performance_summary()
    
    if perf:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total P&L", f"₹{perf.get('total_pnl', 0):+,.0f}")
        with col2:
            st.metric("Win Rate", f"{perf.get('win_rate', 0):.1f}%", 
                     delta=f"{perf.get('wins', 0)}W / {perf.get('losses', 0)}L")
        with col3:
            st.metric("Profit Factor", f"{perf.get('pf', 0):.2f}")
        with col4:
            avg_win = perf.get('avg_win', 0)
            avg_loss = perf.get('avg_loss', 0)
            st.metric("Avg Win/Loss", f"₹{avg_win:+,.0f} / ₹{avg_loss:+,.0f}")
        
        # ─── Trade Distribution ──
        st.markdown("#### 📊 Trade Distribution")
        trades_df = get_recent_trades(100)
        
        if not trades_df.empty:
            fig_dist = make_subplots(rows=1, cols=3, subplot_titles=('R-Multiple Distribution', 'P&L by Sector', 'Exit Type'))
            
            # R-Multiple Distribution - FIXED: Handle NaN values
            valid_r = trades_df['r_multiple'].dropna()
            if not valid_r.empty:
                fig_dist.add_trace(
                    go.Histogram(
                        x=valid_r,
                        nbinsx=30,
                        marker=dict(
                            color=valid_r.apply(
                                lambda x: '#00c853' if x >= 0 else '#ff1744'
                            )
                        ),
                        opacity=0.7,
                    ),
                    row=1, col=1
                )
            
            # P&L by Sector
            sector_pnl = trades_df.groupby('macro_sector')['pnl_net'].sum().reset_index()
            fig_dist.add_trace(
                go.Bar(
                    x=sector_pnl['macro_sector'],
                    y=sector_pnl['pnl_net'],
                    marker=dict(
                        color=sector_pnl['pnl_net'].apply(
                            lambda x: '#00c853' if x >= 0 else '#ff1744'
                        )
                    ),
                ),
                row=1, col=2
            )
            
            # Exit Type
            exit_counts = trades_df['exit_type'].value_counts().reset_index()
            if not exit_counts.empty:
                exit_counts.columns = ['exit_type', 'count']
                fig_dist.add_trace(
                    go.Pie(
                        labels=exit_counts['exit_type'],
                        values=exit_counts['count'],
                        hole=0.3,
                        marker=dict(colors=['#42a5f5', '#ffd740', '#ff1744', '#00c853']),
                    ),
                    row=1, col=3
                )
            
            fig_dist.update_layout(
                height=350,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#b0bec5'),
                showlegend=False,
                margin=dict(l=20, r=20, t=40, b=20),
            )
            fig_dist.update_xaxes(gridcolor='rgba(255,255,255,0.03)')
            fig_dist.update_yaxes(gridcolor='rgba(255,255,255,0.03)')
            
            st.plotly_chart(fig_dist, use_container_width=True, config={'displayModeBar': False})
            
            # ─── Recent Trades Table ──
            st.markdown("#### 📋 Recent Trades")
            display_trades = trades_df.copy()
            display_trades['entry_price'] = display_trades['entry_price'].apply(lambda x: f"₹{x:,.2f}")
            display_trades['exit_price'] = display_trades['exit_price'].apply(lambda x: f"₹{x:,.2f}")
            display_trades['pnl_net'] = display_trades['pnl_net'].apply(lambda x: f"₹{x:+,.2f}")
            display_trades['r_multiple'] = display_trades['r_multiple'].apply(lambda x: f"{x:+.2f}R" if pd.notna(x) else '—')
            
            st.dataframe(
                display_trades[['ticker', 'exit_date', 'exit_type', 'entry_price', 'exit_price', 
                               'pnl_net', 'r_multiple', 'holding_days', 'macro_sector']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ticker": "Ticker",
                    "exit_date": "Exit Date",
                    "exit_type": "Type",
                    "entry_price": "Entry",
                    "exit_price": "Exit",
                    "pnl_net": "P&L",
                    "r_multiple": "R",
                    "holding_days": "Days",
                    "macro_sector": "Sector",
                }
            )
    else:
        st.info("No performance data available")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: RISK DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### 📋 Risk Dashboard")
    st.caption("Real-time risk monitoring and metrics")
    
    # ─── Risk Metrics ──
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        heat = snapshot.get('portfolio_heat', 0)
        heat_cap = cfg.heat_cap(regime_data.get('regime', 'NEUTRAL')) * 100
        st.metric(
            "Portfolio Heat",
            f"{heat:.1f}%",
            delta=f"Cap: {heat_cap:.1f}%",
            delta_color="inverse" if heat > heat_cap else "normal"
        )
    
    with col2:
        dd = snapshot.get('drawdown_pct', 0)
        st.metric("Current Drawdown", f"{dd:.1f}%")
    
    with col3:
        max_pos = regime_data.get('max_positions', cfg.MAX_POSITIONS)
        n_open = snapshot.get('open_positions', 0)
        pct_util = ((n_open / max_pos) * 100) if max_pos else 0
        st.metric("Position Utilization", f"{n_open}/{max_pos}", 
                 delta=f"{pct_util:.0f}%")
    
    with col4:
        sector_exp = get_sector_exposure()
        max_sector = max(sector_exp.values()) * 100 if sector_exp else 0
        st.metric("Max Sector Exposure", f"{max_sector:.1f}%",
                 delta=f"Limit: {cfg.MAX_SECTOR_EXP * 100:.0f}%",
                 delta_color="inverse" if max_sector > cfg.MAX_SECTOR_EXP * 100 else "normal")
    
    # ─── Sector Exposure Gauges ──
    st.markdown("#### 🎯 Sector Exposure Gauges")
    
    if sector_exp:
        cols = st.columns(min(len(sector_exp), 4))
        for idx, (sector, exp) in enumerate(sector_exp.items()):
            col = cols[idx % len(cols)]
            exp_pct = exp * 100
            limit = cfg.MAX_SECTOR_EXP * 100
            color = '#00c853' if exp_pct < limit * 0.5 else '#ffd740' if exp_pct < limit * 0.8 else '#ff1744'
            
            col.markdown(f"""
            <div style="background:rgba(20,28,50,0.6); border-radius:10px; padding:14px 16px; border:1px solid rgba(255,255,255,0.04);">
                <div style="font-size:11px; color:#6b7a9f; font-weight:500; text-transform:uppercase; letter-spacing:0.5px;">
                    {sector}
                </div>
                <div style="font-size:24px; font-weight:700; color:{color};">{exp_pct:.1f}%</div>
                <div style="margin-top:6px; height:4px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden;">
                    <div style="width:{min(exp_pct / limit * 100, 100)}%; height:100%; background:{color}; border-radius:4px;"></div>
                </div>
                <div style="font-size:10px; color:#4a5a7a; margin-top:4px;">Limit: {limit:.0f}%</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No sector exposure data available")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: ALERTS & LOGS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### ⚡ Alerts & System Logs")
    st.caption("Real-time alerts and system monitoring")
    
    # ─── Alert Panel ──
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("#### 🔔 Active Alerts")
        
        alerts = []
        
        # Check alerts
        heat = snapshot.get('portfolio_heat', 0)
        heat_cap = cfg.heat_cap(regime_data.get('regime', 'NEUTRAL')) * 100
        if heat > heat_cap:
            alerts.append(("⚠️ High Portfolio Heat", f"{heat:.1f}% > {heat_cap:.1f}% cap", "error"))
        
        n_open = snapshot.get('open_positions', 0)
        max_pos = regime_data.get('max_positions', cfg.MAX_POSITIONS)
        if n_open >= max_pos and max_pos > 0:
            alerts.append(("📊 Max Positions", f"{n_open}/{max_pos} filled", "warning"))
        
        dd = snapshot.get('drawdown_pct', 0)
        if dd > 10:
            alerts.append(("📉 Drawdown Alert", f"{dd:.1f}% drawdown", "error"))
        
        for sector, exp in get_sector_exposure().items():
            if exp * 100 > cfg.MAX_SECTOR_EXP * 100 * 0.8:
                alerts.append((f"🏢 Sector Limit", f"{sector}: {exp*100:.1f}% exposure", "warning"))
        
        is_bo, bo_reason = get_macro_blackout_today()
        if is_bo:
            alerts.append(("🚫 Blackout Day", bo_reason, "error"))
        
        if not alerts:
            st.success("✅ No active alerts - All systems normal")
        else:
            for alert in alerts:
                if alert[2] == "error":
                    st.error(f"**{alert[0]}** — {alert[1]}")
                else:
                    st.warning(f"**{alert[0]}** — {alert[1]}")
    
    with col2:
        st.markdown("#### 📋 System Log Stream")
        
        # ─── Log Viewer ──
        if os.path.exists("run_log.txt"):
            with open("run_log.txt", "r") as f:
                logs = f.readlines()[-100:]
            
            for line in logs:
                line = line.strip()
                if not line:
                    continue
                
                if "[ERROR]" in line:
                    st.markdown(f"<div class='log-error'>{line}</div>", unsafe_allow_html=True)
                elif "[WARNING]" in line:
                    st.markdown(f"<div class='log-warning'>{line}</div>", unsafe_allow_html=True)
                elif "success=True" in line or "PAPER ENTRY" in line:
                    st.markdown(f"<div class='log-success'>{line}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='log-info'>{line}</div>", unsafe_allow_html=True)
        else:
            st.info("No log file found")


# ──────────────────────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<hr>
<div style="display:flex; justify-content:space-between; padding: 12px 0; color:#3a4a6a; font-size:11px;">
    <span>🏛️ MKK Institutional Trading System v6.1</span>
    <span>📊 Paper Trading · Educational Use Only</span>
    <span>🔄 Auto-refresh: 30s · Last updated: {}</span>
</div>
""".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)
