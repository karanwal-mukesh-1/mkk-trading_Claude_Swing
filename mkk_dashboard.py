"""
mkk_dashboard.py — MKK Institutional Trading System Dashboard
Production-ready Streamlit UI for monitoring the MKK trading system.

Usage:
  streamlit run mkk_dashboard.py

Architecture:
  - READ-ONLY visualization layer
  - Uses @st.cache_data for performance
  - Dark-themed institutional layout
  - Real-time metrics from SQLite database
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import sqlite3
from datetime import datetime, timedelta, date
import numpy as np
import sys
import os
import re
from typing import Dict, List, Tuple, Optional

# ──────────────────────────────────────────────────────────────────────────────
# IMPORT CORE MODULES (READ-ONLY — NO MODIFICATIONS)
# ──────────────────────────────────────────────────────────────────────────────
# These are your existing modules — imported as-is
from mkk_core import Config, MKKDatabase, MarketRegimeEngine, SectorHeatmap
from mkk_core import TI, RiskManager, PriorityScorer, TCModel

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MKK Institutional Trading System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS — Institutional Dark Theme
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp {
        background-color: #0e1117;
    }
    
    /* Card styling */
    .metric-card {
        background: linear-gradient(145deg, #1a1f2e, #13182b);
        border-radius: 12px;
        padding: 18px 22px;
        border: 1px solid #2a3350;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        margin: 4px 0;
    }
    .metric-card .label {
        font-size: 12px;
        color: #8b92b0;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 500;
    }
    .metric-card .value {
        font-size: 28px;
        font-weight: 700;
        color: #e8edf5;
        margin-top: 4px;
    }
    .metric-card .sub {
        font-size: 14px;
        color: #6b7390;
        margin-top: 2px;
    }
    
    /* Regime badges */
    .regime-bull {
        color: #00c853;
        font-weight: 700;
        background: rgba(0,200,83,0.12);
        padding: 4px 14px;
        border-radius: 20px;
        border: 1px solid rgba(0,200,83,0.25);
    }
    .regime-bear {
        color: #ff1744;
        font-weight: 700;
        background: rgba(255,23,68,0.12);
        padding: 4px 14px;
        border-radius: 20px;
        border: 1px solid rgba(255,23,68,0.25);
    }
    .regime-neutral {
        color: #ffd740;
        font-weight: 700;
        background: rgba(255,215,64,0.12);
        padding: 4px 14px;
        border-radius: 20px;
        border: 1px solid rgba(255,215,64,0.25);
    }
    .regime-volatile {
        color: #ff9100;
        font-weight: 700;
        background: rgba(255,145,0,0.12);
        padding: 4px 14px;
        border-radius: 20px;
        border: 1px solid rgba(255,145,0,0.25);
    }
    
    /* Log styling */
    .log-info {
        color: #b0bec5;
        font-family: 'Consolas', monospace;
        font-size: 12px;
        padding: 2px 0;
        border-bottom: 1px solid rgba(255,255,255,0.03);
    }
    .log-warning {
        color: #ffd740;
        font-family: 'Consolas', monospace;
        font-size: 12px;
        padding: 2px 0;
        border-bottom: 1px solid rgba(255,215,64,0.08);
    }
    .log-error {
        color: #ff5252;
        font-family: 'Consolas', monospace;
        font-size: 12px;
        padding: 2px 0;
        border-bottom: 1px solid rgba(255,82,82,0.08);
    }
    .log-success {
        color: #69f0ae;
        font-family: 'Consolas', monospace;
        font-size: 12px;
        padding: 2px 0;
        border-bottom: 1px solid rgba(105,240,174,0.08);
    }
    
    /* Dataframe styling */
    .stDataFrame {
        background: #0e1117;
    }
    .stDataFrame thead tr th {
        background: #1a1f2e !important;
        color: #8b92b0 !important;
        font-size: 11px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
    }
    .stDataFrame tbody tr td {
        font-size: 13px !important;
        color: #c5cbe0 !important;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: #13182b;
        padding: 6px 8px;
        border-radius: 10px;
        border: 1px solid #1e2640;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 18px;
        font-weight: 500;
        font-size: 13px;
        color: #6b7390;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(145deg, #1e2a4a, #162040);
        color: #e8edf5 !important;
        border: 1px solid #3a4a7a;
    }
    
    /* Headers */
    h1, h2, h3, h4 {
        color: #e8edf5 !important;
        font-weight: 600 !important;
    }
    .stMarkdown p {
        color: #b0bec5;
    }
    
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0b0f1a;
        border-right: 1px solid #1a1f2e;
    }
    section[data-testid="stSidebar"] .stMarkdown {
        color: #b0bec5;
    }
    
    /* Divider */
    hr {
        border-color: #1e2640 !important;
        margin: 18px 0 !important;
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background: #13182b !important;
        border-color: #1e2640 !important;
        color: #e8edf5 !important;
        font-weight: 500 !important;
    }
    .streamlit-expanderContent {
        background: #0e1117 !important;
        border-color: #1e2640 !important;
    }
    
    /* Plotly container */
    .js-plotly-plot .plotly .main-svg {
        background: transparent !important;
    }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# CACHED DATABASE CONNECTION
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_db():
    """Singleton database connection with caching."""
    cfg = Config()
    return MKKDatabase(cfg.DB_PATH)


@st.cache_data(ttl=60)
def get_config() -> Config:
    """Cached Config instance."""
    return Config()


@st.cache_data(ttl=60)
def get_regime() -> Dict:
    """Get current market regime with caching."""
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
    }


@st.cache_data(ttl=60)
def get_last_run() -> Optional[Dict]:
    """Get the most recent paper session record."""
    db = get_db()
    row = db.q(
        "SELECT run_date, run_start, run_end, duration_sec, mode, regime, "
        "exits_processed, entries_taken, scan_setups, email_sent "
        "FROM paper_sessions ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row:
        return dict(row)
    return None


@st.cache_data(ttl=60)
def get_portfolio_snapshot() -> Dict:
    """Get latest portfolio snapshot."""
    db = get_db()
    row = db.q(
        "SELECT * FROM paper_snapshots ORDER BY snap_date DESC LIMIT 1"
    ).fetchone()
    if row:
        return dict(row)
    return {}


@st.cache_data(ttl=60)
def get_open_trades() -> pd.DataFrame:
    """Get all open paper trades."""
    db = get_db()
    return db.open_paper_trades()


@st.cache_data(ttl=60)
def get_recent_exits(limit: int = 50) -> pd.DataFrame:
    """Get recent exits with trade context."""
    db = get_db()
    return db.qdf(
        "SELECT pe.*, pt.ticker, pt.macro_sector, pt.pattern, pt.entry_price "
        "FROM paper_exits pe "
        "JOIN paper_trades pt ON pe.trade_id = pt.trade_id "
        "ORDER BY pe.created_at DESC LIMIT ?",
        (limit,)
    )


@st.cache_data(ttl=60)
def get_performance_summary() -> Dict:
    """Get performance metrics."""
    db = get_db()
    return db.paper_perf_summary()


@st.cache_data(ttl=60)
def get_latest_scan_results(limit: int = 20) -> pd.DataFrame:
    """Get the most recent scan results with priority ranking."""
    db = get_db()
    return db.qdf(
        "SELECT ticker, price, score, priority_score, priority_rank, "
        "trade_type, pattern, rs_3m, rs_rank, vcp_quality, to_resistance, "
        "stop_loss, target_t1, target_t2, target_t3, shares_suggested, "
        "capital_required, risk_inr, macro_sector, sector, above_200ma, "
        "macd_positive, ema_cross "
        "FROM scan_results "
        "WHERE scan_date = (SELECT MAX(scan_date) FROM scan_results) "
        "ORDER BY priority_rank LIMIT ?",
        (limit,)
    )


@st.cache_data(ttl=60)
def get_scan_funnel_stats(session_id: str = None) -> Dict:
    """Get funnel statistics from the latest scan session."""
    db = get_db()
    if session_id is None:
        row = db.q(
            "SELECT session_id FROM scan_sessions "
            "ORDER BY scan_start DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {}
        session_id = row[0]
    row = db.q(
        "SELECT total_scanned, data_failed, sector_filtered, price_vol_pass, "
        "trend_pass, consol_pass, momentum_pass, rs_pass, rs_slope_pass, "
        "vcp_pass, corr_filtered, elite_setups, duration_min "
        "FROM scan_sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    if row:
        return dict(row)
    return {}


@st.cache_data(ttl=60)
def get_sector_snapshots() -> pd.DataFrame:
    """Get latest sector heatmap snapshot."""
    db = get_db()
    return db.qdf(
        "SELECT * FROM sector_snapshots "
        "WHERE snap_date = (SELECT MAX(snap_date) FROM sector_snapshots) "
        "ORDER BY rs_3m DESC"
    )


@st.cache_data(ttl=60)
def get_macro_blackout_today() -> Tuple[bool, str]:
    """Check if today is a macro blackout day."""
    db = get_db()
    today = date.today().isoformat()
    return db.is_macro_blackout(today)


@st.cache_data(ttl=60)
def get_equity_curve() -> pd.DataFrame:
    """Get the full equity curve."""
    db = get_db()
    return db.qdf(
        "SELECT snap_date, total_capital, deployed, cash, open_positions, "
        "unrealized_pnl, realized_pnl_ytd, drawdown_pct, portfolio_heat "
        "FROM paper_snapshots ORDER BY snap_date"
    )


@st.cache_data(ttl=60)
def get_sector_exposure() -> Dict:
    """Get current sector exposure percentages."""
    cfg = get_config()
    db = get_db()
    return db.paper_sector_exposure(cfg)


@st.cache_data(ttl=60)
def parse_log_file(log_path: str = "run_log.txt", max_lines: int = 500) -> List[Dict]:
    """Parse the run_log.txt file with color coding."""
    logs = []
    if not os.path.exists(log_path):
        return logs
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-max_lines:]
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Parse timestamp and level
            level = "INFO"
            if "[WARNING]" in line or "[WARN]" in line:
                level = "WARNING"
            elif "[ERROR]" in line or "[FATAL]" in line:
                level = "ERROR"
            elif "success=True" in line or "COMPLETE" in line:
                level = "SUCCESS"
            elif "PAPER ENTRY" in line or "Paper entry" in line:
                level = "SUCCESS"
            elif "EXIT" in line and "STOPPED" in line:
                level = "WARNING"
            
            logs.append({
                'raw': line,
                'level': level,
                'timestamp': line[:19] if len(line) > 19 else line
            })
    except Exception as e:
        logs.append({'raw': f"Error reading log: {e}", 'level': 'ERROR', 'timestamp': ''})
    
    return logs


# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR — System Status & Meta Header
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 16px 0 10px 0;">
        <span style="font-size:28px; font-weight:700; color:#e8edf5;">📊 MKK</span>
        <span style="font-size:14px; font-weight:400; color:#6b7390; display:block; margin-top:-4px;">
            Institutional Trading System
        </span>
        <span style="font-size:11px; color:#4a5370; display:block; margin-top:2px;">
            v6.1 · Paper Trading
        </span>
    </div>
    <hr>
    """, unsafe_allow_html=True)

    # ── Config Metrics ──
    cfg = get_config()
    st.markdown("### ⚙️ System Parameters")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("💰 Capital", f"₹{cfg.TOTAL_CAPITAL:,.0f}")
    with col2:
        st.metric("📈 Max Positions", cfg.MAX_POSITIONS)

    # ── Regime Status ──
    regime_data = get_regime()
    regime = regime_data['regime']
    regime_class = {
        'BULL': 'regime-bull',
        'BULL_WK': 'regime-bull',
        'NEUTRAL': 'regime-neutral',
        'BEAR_WK': 'regime-bear',
        'BEAR': 'regime-bear',
        'VOLATILE': 'regime-volatile'
    }.get(regime, 'regime-neutral')
    
    st.markdown(f"""
    <div style="margin-top:10px;">
        <span style="color:#6b7390; font-size:12px; text-transform:uppercase; letter-spacing:1px;">
            Market Regime
        </span>
        <div style="display:flex; align-items:center; gap:10px; margin-top:4px;">
            <span class="{regime_class}">{regime}</span>
            <span style="color:#6b7390; font-size:13px;">Score: {regime_data['score']}/100</span>
        </div>
        <div style="font-size:12px; color:#6b7390; margin-top:4px;">
            Nifty 50: ₹{regime_data['nifty_close']:,.2f}
            { '🔓 Entries Open' if regime_data['allow_entry'] else '🔒 Entries Blocked' }
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Blackout Check ──
    is_bo, bo_reason = get_macro_blackout_today()
    if is_bo:
        st.warning(f"🚫 {bo_reason}")
    else:
        st.success("✅ No macro blackout today")

    # ── Last Run ──
    last_run = get_last_run()
    if last_run:
        st.markdown("### 🕐 Last Execution")
        run_date = last_run.get('run_date', 'Unknown')
        dur = last_run.get('duration_sec', 0)
        dur_str = f"{dur//60}m {dur%60}s" if dur else "N/A"
        st.markdown(f"""
        <div style="font-size:13px; color:#b0bec5; line-height:1.6;">
            <span style="color:#6b7390;">Date:</span> {run_date}<br>
            <span style="color:#6b7390;">Duration:</span> {dur_str}<br>
            <span style="color:#6b7390;">Mode:</span> {last_run.get('mode', 'N/A')}<br>
            <span style="color:#6b7390;">Entries:</span> {last_run.get('entries_taken', 0)} &nbsp;|&nbsp;
            <span style="color:#6b7390;">Exits:</span> {last_run.get('exits_processed', 0)}
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.caption("📌 Data refreshes every 60 seconds · Read-only dashboard")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN HEADER — Meta Header with Key Metrics
# ──────────────────────────────────────────────────────────────────────────────
regime_data = get_regime()
snapshot = get_portfolio_snapshot()
perf = get_performance_summary()

# Top bar metrics
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Total Capital</div>
        <div class="value">₹{cfg.TOTAL_CAPITAL:,.0f}</div>
        <div class="sub">Paper trading</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    deployed = snapshot.get('deployed', 0)
    pct_deployed = (deployed / cfg.TOTAL_CAPITAL * 100) if cfg.TOTAL_CAPITAL > 0 else 0
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Deployed</div>
        <div class="value">₹{deployed:,.0f}</div>
        <div class="sub">{pct_deployed:.1f}% of capital</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    n_open = snapshot.get('open_positions', 0)
    max_pos = regime_data.get('max_positions', cfg.MAX_POSITIONS)
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Open Positions</div>
        <div class="value">{n_open} / {max_pos}</div>
        <div class="sub">{'Fully allocated' if n_open >= max_pos else f'{max_pos - n_open} slots available'}</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    heat = snapshot.get('portfolio_heat', 0)
    heat_cap = cfg.heat_cap(regime_data['regime']) * 100
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Portfolio Heat</div>
        <div class="value">{heat:.1f}%</div>
        <div class="sub">Cap: {heat_cap:.1f}% · {'✓' if heat <= heat_cap else '⚠️ Over'}</div>
    </div>
    """, unsafe_allow_html=True)

with col5:
    total_pnl = perf.get('total_pnl', 0) if perf else 0
    win_rate = perf.get('win_rate', 0) if perf else 0
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">Closed P&L</div>
        <div class="value" style="color:{'#69f0ae' if total_pnl >= 0 else '#ff5252'}">
            ₹{total_pnl:+,.0f}
        </div>
        <div class="sub">Win Rate: {win_rate:.1f}% · {perf.get('total', 0) if perf else 0} trades</div>
    </div>
    """, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# TABS
# ──────────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Scanner Funnel",
    "⚠️ Risk Engine & Sizing",
    "📈 Historical Audit",
    "📋 Log Stream"
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: SCANNER FUNNEL
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### 🔍 Scanner Funnel — Elite Setup Pipeline")
    st.caption("Visualizes how the system filters 2,200+ NSE stocks down to elite setups")
    
    # ── Funnel Stats ──
    funnel = get_scan_funnel_stats()
    
    if funnel:
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("📊 Total Scanned", f"{funnel.get('total_scanned', 0):,}")
        with col2:
            st.metric("📉 Data Failed", f"{funnel.get('data_failed', 0)}")
        with col3:
            pass_pv = funnel.get('price_vol_pass', 0)
            pct = (pass_pv / funnel.get('total_scanned', 1) * 100) if funnel.get('total_scanned', 0) > 0 else 0
            st.metric("✅ Price/Vol Pass", f"{pass_pv:,} ({pct:.0f}%)")
        with col4:
            elite = funnel.get('elite_setups', 0)
            pct_elite = (elite / funnel.get('total_scanned', 1) * 100) if funnel.get('total_scanned', 0) > 0 else 0
            st.metric("🌟 Elite Setups", f"{elite} ({pct_elite:.2f}%)")
        with col5:
            dur = funnel.get('duration_min', 0)
            st.metric("⏱️ Scan Time", f"{dur:.1f} min")
        
        # ── Funnel Visualization ──
        st.markdown("#### Funnel Pipeline")
        
        stages = [
            ("Total Scanned", funnel.get('total_scanned', 0)),
            ("Price/Vol Pass", funnel.get('price_vol_pass', 0)),
            ("Trend Pass", funnel.get('trend_pass', 0)),
            ("Consolidation", funnel.get('consol_pass', 0)),
            ("Momentum", funnel.get('momentum_pass', 0)),
            ("RS Pass", funnel.get('rs_pass', 0)),
            ("RS Slope", funnel.get('rs_slope_pass', 0)),
            ("VCP Pass", funnel.get('vcp_pass', 0)),
            ("Elite Setups", funnel.get('elite_setups', 0)),
        ]
        
        fig = go.Figure()
        
        # Build funnel trace
        values = [s[1] for s in stages]
        labels = [s[0] for s in stages]
        
        fig.add_trace(go.Funnel(
            name="Scan Pipeline",
            y=labels,
            x=values,
            textinfo="value+percent initial",
            textposition="inside",
            marker=dict(
                color=["#1a3a5c", "#1e4a6a", "#2a5a7a", "#3a6a8a", "#4a7a9a", 
                       "#5a8aaa", "#6a9aba", "#7aaaca", "#8aba5a"],
                line=dict(width=1, color='#0e1117')
            ),
            connector=dict(line=dict(color="#2a3350", width=2)),
        ))
        
        fig.update_layout(
            height=500,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#b0bec5', size=13),
            margin=dict(l=20, r=20, t=20, b=20),
        )
        
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        
        # ── Rejection Log ──
        with st.expander("📋 Rejection Log — Filter Breakdown", expanded=False):
            reject_data = {
                "Filter Stage": ["Data Failed", "Sector Blocked", "Trend Pass", "Consolidation", 
                                 "Momentum", "RS Pass", "RS Slope", "VCP Pass", 
                                 "Correlation", "Score Filter", "Heat Blocked", "Macro Blackout"],
                "Count": [
                    funnel.get('data_failed', 0),
                    funnel.get('sector_filtered', 0),
                    funnel.get('trend_pass', 0),  # These are passes, not rejections
                    funnel.get('consol_pass', 0),
                    funnel.get('momentum_pass', 0),
                    funnel.get('rs_pass', 0),
                    funnel.get('rs_slope_pass', 0),
                    funnel.get('vcp_pass', 0),
                    funnel.get('corr_filtered', 0),
                    funnel.get('score_filtered', 0) if 'score_filtered' in funnel else 0,
                    funnel.get('heat_blocked', 0) if 'heat_blocked' in funnel else 0,
                    funnel.get('macro_blackout', 0) if 'macro_blackout' in funnel else 0,
                ]
            }
            reject_df = pd.DataFrame(reject_data)
            reject_df = reject_df[reject_df['Count'] > 0].sort_values('Count', ascending=False)
            if not reject_df.empty:
                st.dataframe(
                    reject_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Filter Stage": st.column_config.TextColumn("Filter Stage", width="medium"),
                        "Count": st.column_config.NumberColumn("Rejected", width="small"),
                    }
                )
            else:
                st.info("No stocks rejected at this stage.")
    
    # ── Elite Setups Table ──
    st.markdown("#### ⭐ Final Elite Setups")
    elite_df = get_latest_scan_results()
    
    if not elite_df.empty:
        # Format columns for display
        display_df = elite_df.copy()
        display_df['Price'] = display_df['price'].apply(lambda x: f"₹{x:,.2f}")
        display_df['Score'] = display_df['score'].astype(str)
        display_df['RS_3M'] = display_df['rs_3m'].apply(lambda x: f"{x:.3f}" if x and x != 'N/A' else 'N/A')
        display_df['RS_Rank'] = display_df['rs_rank'].astype(str) + '%'
        display_df['VCP'] = display_df['vcp_quality'].apply(lambda x: f"{x:.1f}" if x else 'N/A')
        display_df['Stop'] = display_df['stop_loss'].apply(lambda x: f"₹{x:,.2f}")
        display_df['T1'] = display_df['target_t1'].apply(lambda x: f"₹{x:,.2f}")
        display_df['T2'] = display_df['target_t2'].apply(lambda x: f"₹{x:,.2f}")
        display_df['T3'] = display_df['target_t3'].apply(lambda x: f"₹{x:,.2f}")
        display_df['Cap Req'] = display_df['capital_required'].apply(lambda x: f"₹{x:,.0f}")
        
        # Select columns for display
        display_cols = ['Ticker', 'Price', 'Score', 'Pattern', 'Trade_Type', 
                        'RS_3M', 'RS_Rank', 'VCP', 'Stop', 'T1', 'T2', 'T3', 'Cap Req']
        display_df = display_df.rename(columns={
            'ticker': 'Ticker',
            'trade_type': 'Trade_Type',
            'pattern': 'Pattern',
        })
        
        # Only show available columns
        available_cols = [c for c in display_cols if c in display_df.columns]
        display_df = display_df[available_cols]
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                "Price": st.column_config.TextColumn("Price", width="small"),
                "Score": st.column_config.TextColumn("Score", width="small"),
                "Pattern": st.column_config.TextColumn("Pattern", width="small"),
                "Trade_Type": st.column_config.TextColumn("Type", width="small"),
                "RS_3M": st.column_config.TextColumn("RS 3M", width="small"),
                "RS_Rank": st.column_config.TextColumn("RS Rank", width="small"),
                "VCP": st.column_config.TextColumn("VCP", width="small"),
                "Stop": st.column_config.TextColumn("Stop", width="small"),
                "T1": st.column_config.TextColumn("T1", width="small"),
                "T2": st.column_config.TextColumn("T2", width="small"),
                "T3": st.column_config.TextColumn("T3", width="small"),
                "Cap Req": st.column_config.TextColumn("Capital Req.", width="small"),
            }
        )
        
        # ── Sector Heatmap ──
        st.markdown("#### 📊 Sector Heatmap")
        sector_df = get_sector_snapshots()
        if not sector_df.empty:
            # Create a bar chart
            fig_sector = go.Figure()
            
            # RS 3M bars
            fig_sector.add_trace(go.Bar(
                x=sector_df['macro_sector'],
                y=sector_df['rs_3m'],
                name='RS 3M',
                marker_color='#4a7a9a',
                yaxis='y',
            ))
            
            # Gate status overlay
            gate_colors = ['#69f0ae' if g else '#ff5252' for g in sector_df['sector_gate']]
            
            fig_sector.update_layout(
                barmode='group',
                height=350,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#b0bec5'),
                yaxis=dict(title='RS 3M', gridcolor='#1a1f2e'),
                xaxis=dict(tickangle=45),
                margin=dict(l=40, r=20, t=20, b=80),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            )
            
            # Add annotations for gate status
            for i, (row, color) in enumerate(zip(sector_df.iterrows(), gate_colors)):
                idx, data = row
                status = 'OPEN' if data['sector_gate'] else 'SHUT'
                fig_sector.add_annotation(
                    x=i,
                    y=0.05,
                    text=status,
                    showarrow=False,
                    font=dict(size=10, color='#b0bec5'),
                    yref='paper',
                )
            
            st.plotly_chart(fig_sector, use_container_width=True, config={'displayModeBar': False})
            
            # Sector data table
            with st.expander("📊 Sector Details", expanded=False):
                sector_display = sector_df.copy()
                sector_display['rs_3m'] = sector_display['rs_3m'].apply(lambda x: f"{x:.3f}" if x else 'N/A')
                sector_display['trend_score'] = sector_display['trend_score'].apply(lambda x: f"{x:.0f}%")
                sector_display['scan_hit_rate'] = sector_display['scan_hit_rate'].apply(lambda x: f"{x:.1f}%")
                sector_display['gate_open'] = sector_display['sector_gate'].apply(lambda x: '✅ OPEN' if x else '🔒 SHUT')
                
                st.dataframe(
                    sector_display[['macro_sector', 'sector', 'rs_3m', 'trend_score', 
                                    'scan_hit_rate', 'portfolio_exposure', 'gate_open']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "macro_sector": "Macro Sector",
                        "sector": "Sector",
                        "rs_3m": "RS 3M",
                        "trend_score": "Trend Score",
                        "scan_hit_rate": "Hit Rate",
                        "portfolio_exposure": "Exp %",
                        "gate_open": "Gate",
                    }
                )
    else:
        st.info("No scan results available yet. Run a scan to populate this view.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: RISK ENGINE & LIVE POSITION SIZING
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### ⚠️ Risk Engine & Position Sizing")
    st.caption("Live position sizing based on ATR rules, sector exposure limits, and regime constraints")
    
    # ── Position Sizing Engine ──
    st.markdown("#### 📐 Position Sizing Calculator")
    
    open_trades = get_open_trades()
    latest_scan = get_latest_scan_results()
    
    if not latest_scan.empty:
        # Calculate position sizes for elite setups
        sizing_data = []
        cfg = get_config()
        re = MarketRegimeEngine(cfg)
        re.detect()
        risk = RiskManager(cfg, re, get_db())
        sector_exp = get_sector_exposure()
        
        for _, row in latest_scan.iterrows():
            entry = float(row['price'])
            stop = float(row['stop_loss'])
            if entry <= 0 or stop <= 0 or entry <= stop:
                continue
            
            # Get risk sizing
            ps = risk.size(cfg.TOTAL_CAPITAL, entry, stop, row['trade_type'], 
                          float(row.get('avg_val', 0) or 0))
            
            if ps['shares'] > 0 and ps.get('heat_ok', True):
                ms = row['macro_sector']
                current_exp = sector_exp.get(ms, 0)
                new_exp = current_exp + (ps['invested'] / cfg.TOTAL_CAPITAL)
                sector_ok = new_exp <= cfg.MAX_SECTOR_EXP
                
                sizing_data.append({
                    'Ticker': row['ticker'],
                    'Entry': entry,
                    'Stop': stop,
                    'Shares': ps['shares'],
                    'Invested': ps['invested'],
                    'Risk Amount': ps['risk_amount'],
                    'Risk %': ps['risk_pct'],
                    'Heat Contrib %': ps['heat_contrib'] * 100,
                    'Sector': ms,
                    'Sector Exp %': current_exp * 100,
                    'New Sector Exp %': new_exp * 100,
                    'Sector OK': sector_ok,
                    'Trade Type': row['trade_type'],
                })
        
        if sizing_data:
            sizing_df = pd.DataFrame(sizing_data)
            sizing_df = sizing_df.sort_values('Priority_Rank' if 'Priority_Rank' in sizing_df.columns else 'Invested', 
                                             ascending=False)
            
            # Display sizing table
            display_sizing = sizing_df.copy()
            display_sizing['Entry'] = display_sizing['Entry'].apply(lambda x: f"₹{x:,.2f}")
            display_sizing['Stop'] = display_sizing['Stop'].apply(lambda x: f"₹{x:,.2f}")
            display_sizing['Invested'] = display_sizing['Invested'].apply(lambda x: f"₹{x:,.0f}")
            display_sizing['Risk Amount'] = display_sizing['Risk Amount'].apply(lambda x: f"₹{x:,.0f}")
            display_sizing['Sector OK'] = display_sizing['Sector OK'].apply(lambda x: '✅' if x else '❌')
            
            st.dataframe(
                display_sizing,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                    "Entry": st.column_config.TextColumn("Entry", width="small"),
                    "Stop": st.column_config.TextColumn("Stop", width="small"),
                    "Shares": st.column_config.NumberColumn("Shares", width="small"),
                    "Invested": st.column_config.TextColumn("Invested", width="small"),
                    "Risk Amount": st.column_config.TextColumn("Risk", width="small"),
                    "Risk %": st.column_config.NumberColumn("Risk %", width="small", format="%.2f"),
                    "Heat Contrib %": st.column_config.NumberColumn("Heat %", width="small", format="%.2f"),
                    "Sector": st.column_config.TextColumn("Sector", width="small"),
                    "Sector Exp %": st.column_config.NumberColumn("Curr Exp %", width="small", format="%.2f"),
                    "New Sector Exp %": st.column_config.NumberColumn("New Exp %", width="small", format="%.2f"),
                    "Sector OK": st.column_config.TextColumn("OK", width="small"),
                    "Trade Type": st.column_config.TextColumn("Type", width="small"),
                }
            )
            
            # ── Sector Concentration (Treemap) ──
            st.markdown("#### 📊 Sector & Sub-sector Concentration")
            
            # Get positions with sector data
            if not open_trades.empty:
                sector_data = open_trades.groupby('macro_sector')['capital_invested'].sum().reset_index()
                sector_data['Pct'] = sector_data['capital_invested'] / cfg.TOTAL_CAPITAL * 100
                
                # Treemap
                fig_treemap = go.Figure(go.Treemap(
                    labels=sector_data['macro_sector'],
                    values=sector_data['capital_invested'],
                    text=sector_data['Pct'].apply(lambda x: f"{x:.1f}%"),
                    textinfo="label+text",
                    marker=dict(
                        colors=sector_data['Pct'] / sector_data['Pct'].max() if sector_data['Pct'].max() > 0 else [1] * len(sector_data),
                        colorscale='Blues',
                        showscale=False,
                    ),
                    hovertemplate='<b>%{label}</b><br>Invested: ₹%{value:,.0f}<br>%{text}<extra></extra>',
                ))
                
                fig_treemap.update_layout(
                    height=400,
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#b0bec5', size=13),
                    margin=dict(l=10, r=10, t=10, b=10),
                )
                
                st.plotly_chart(fig_treemap, use_container_width=True, config={'displayModeBar': False})
                
                # ── Sector Exposure Alert ──
                st.markdown("#### ⚠️ Sector Exposure Alerts")
                
                exp_df = pd.DataFrame(list(sector_exp.items()), columns=['Sector', 'Exposure'])
                exp_df['Exposure Pct'] = exp_df['Exposure'] * 100
                exp_df['Limit'] = cfg.MAX_SECTOR_EXP * 100
                exp_df['Status'] = exp_df.apply(
                    lambda x: '⚠️ Near Limit' if x['Exposure Pct'] > x['Limit'] * 0.8 else '✅ Safe',
                    axis=1
                )
                
                if not exp_df.empty:
                    st.dataframe(
                        exp_df[['Sector', 'Exposure Pct', 'Limit', 'Status']],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Sector": st.column_config.TextColumn("Sector", width="medium"),
                            "Exposure Pct": st.column_config.NumberColumn("Current Exposure", width="small", format="%.2f%%"),
                            "Limit": st.column_config.NumberColumn("Limit", width="small", format="%.2f%%"),
                            "Status": st.column_config.TextColumn("Status", width="small"),
                        }
                    )
                else:
                    st.info("No open positions — sector exposure is 0%")
            else:
                st.info("No open positions — sector concentration view will populate when trades exist.")
        else:
            st.info("No valid position sizing data available from scan results.")
    else:
        st.info("No scan results available. Run a scan to see position sizing recommendations.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: HISTORICAL AUDIT
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 📈 Historical Audit & Performance")
    
    # ── Performance Metrics ──
    perf = get_performance_summary()
    if perf:
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Trades", perf.get('total', 0))
        with col2:
            st.metric("Win Rate", f"{perf.get('win_rate', 0):.1f}%")
        with col3:
            st.metric("Avg R", f"{perf.get('avg_r', 0):.3f}")
        with col4:
            pf = perf.get('pf', 0)
            st.metric("Profit Factor", f"{pf:.2f}", 
                     delta="+" if pf > 1 else "-" if pf < 1 else "0",
                     delta_color="normal")
        with col5:
            st.metric("Total P&L", f"₹{perf.get('total_pnl', 0):+,.0f}",
                     delta_color="normal")
    
    # ── Equity Curve ──
    st.markdown("#### 📉 Equity Curve")
    equity_df = get_equity_curve()
    
    if not equity_df.empty:
        fig_equity = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Total capital
        fig_equity.add_trace(
            go.Scatter(
                x=equity_df['snap_date'],
                y=equity_df['total_capital'],
                name='Total Capital',
                line=dict(color='#69f0ae', width=2),
                fill='tonexty',
                fillcolor='rgba(105,240,174,0.1)',
            ),
            secondary_y=False,
        )
        
        # Drawdown
        fig_equity.add_trace(
            go.Scatter(
                x=equity_df['snap_date'],
                y=equity_df['drawdown_pct'],
                name='Drawdown',
                line=dict(color='#ff5252', width=1.5, dash='dash'),
                fill='tozeroy',
                fillcolor='rgba(255,82,82,0.1)',
            ),
            secondary_y=True,
        )
        
        fig_equity.update_layout(
            height=350,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#b0bec5'),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            margin=dict(l=20, r=40, t=20, b=40),
        )
        fig_equity.update_yaxes(title_text="Capital (₹)", gridcolor='#1a1f2e', secondary_y=False)
        fig_equity.update_yaxes(title_text="Drawdown %", gridcolor='#1a1f2e', secondary_y=True)
        
        st.plotly_chart(fig_equity, use_container_width=True, config={'displayModeBar': False})
    
    # ── Open Trades ──
    st.markdown("#### 🔓 Open Trades")
    open_df = get_open_trades()
    if not open_df.empty:
        display_open = open_df.copy()
        display_open['entry_price'] = display_open['entry_price'].apply(lambda x: f"₹{x:,.2f}")
        display_open['stop_loss'] = display_open['stop_loss'].apply(lambda x: f"₹{x:,.2f}")
        display_open['capital_invested'] = display_open['capital_invested'].apply(lambda x: f"₹{x:,.0f}")
        
        st.dataframe(
            display_open[['ticker', 'entry_date', 'entry_price', 'shares', 'capital_invested', 
                         'stop_loss', 'pattern', 'macro_sector', 'status']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "ticker": "Ticker",
                "entry_date": "Entry Date",
                "entry_price": "Entry Price",
                "shares": "Shares",
                "capital_invested": "Invested",
                "stop_loss": "Stop Loss",
                "pattern": "Pattern",
                "macro_sector": "Sector",
                "status": "Status",
            }
        )
    else:
        st.info("No open trades.")
    
    # ── Recent Exits ──
    st.markdown("#### 📤 Recent Exits")
    exits_df = get_recent_exits(30)
    if not exits_df.empty:
        display_exits = exits_df.copy()
        display_exits['exit_price'] = display_exits['exit_price'].apply(lambda x: f"₹{x:,.2f}")
        display_exits['pnl_net'] = display_exits['pnl_net'].apply(lambda x: f"₹{x:+,.2f}")
        display_exits['r_multiple'] = display_exits['r_multiple'].apply(lambda x: f"{x:+.2f}R")
        display_exits['holding_days'] = display_exits['holding_days'].fillna(0).astype(int)
        
        st.dataframe(
            display_exits[['ticker', 'exit_date', 'exit_type', 'exit_price', 
                          'pnl_net', 'r_multiple', 'holding_days', 'macro_sector']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "ticker": "Ticker",
                "exit_date": "Exit Date",
                "exit_type": "Exit Type",
                "exit_price": "Exit Price",
                "pnl_net": "P&L",
                "r_multiple": "R-Multiple",
                "holding_days": "Hold Days",
                "macro_sector": "Sector",
            }
        )
    else:
        st.info("No exits recorded yet.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: LOG STREAM
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 📋 Live Log Stream")
    st.caption("Colour-coded logs from the latest run")
    
    # ── Log Controls ──
    col1, col2 = st.columns([2, 1])
    with col1:
        log_path = st.text_input("Log File Path", value="run_log.txt", label_visibility="collapsed")
    with col2:
        max_lines = st.selectbox("Max Lines", [100, 250, 500, 1000], index=2)
    
    # ── Parse and Display Logs ──
    logs = parse_log_file(log_path, max_lines)
    
    if logs:
        # Filter controls
        log_levels = st.multiselect(
            "Filter by Level",
            options=["INFO", "WARNING", "ERROR", "SUCCESS"],
            default=["INFO", "WARNING", "ERROR", "SUCCESS"],
        )
        
        filtered = [l for l in logs if l['level'] in log_levels]
        
        # Display logs
        log_container = st.container()
        with log_container:
            for log_entry in filtered:
                level = log_entry['level']
                css_class = {
                    'INFO': 'log-info',
                    'WARNING': 'log-warning',
                    'ERROR': 'log-error',
                    'SUCCESS': 'log-success'
                }.get(level, 'log-info')
                
                st.markdown(
                    f'<div class="{css_class}">{log_entry["raw"]}</div>',
                    unsafe_allow_html=True
                )
        
        # Auto-refresh option
        if st.button("🔄 Refresh Logs"):
            st.cache_data.clear()
            st.rerun()
    else:
        st.info("No log file found. Please run the system to generate logs.")


# ──────────────────────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<hr>
<div style="display:flex; justify-content:space-between; padding: 8px 0; color:#4a5370; font-size:11px;">
    <span>MKK Institutional Trading System v6.1</span>
    <span>Paper Trading · Educational Use Only</span>
    <span>Data refreshes every 60s · Last updated: {}</span>
</div>
""".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)