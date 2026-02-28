"""
mkk_paper.py — Paper Trading Engine
Processes exits on previous day's OHLC, then enters new signals at open.
Swing trading protocol — daily timeframe only.
"""
import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

from mkk_core import (Config, MKKDatabase, TI, MarketRegimeEngine,
                      RiskManager, TCModel)

log = logging.getLogger('mkk')


def _fetch_ohlc(tickers: List[str], period: str = '5d') -> pd.DataFrame:
    """Batch fetch OHLC. Returns MultiIndex DataFrame or empty."""
    if not tickers:
        return pd.DataFrame()
    clean = [t if '.NS' in t else t + '.NS' for t in tickers]
    try:
        raw = yf.download(clean, period=period, progress=False,
                          timeout=20, group_by='ticker')
        return raw
    except Exception as e:
        log.warning(f'OHLC fetch failed: {e}')
        return pd.DataFrame()


def _get_ticker_ohlc(raw: pd.DataFrame, ticker: str) -> Optional[pd.Series]:
    """Extract last row for one ticker from batch download."""
    ns = ticker if '.NS' in ticker else ticker + '.NS'
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if ns in raw.columns.get_level_values(0):
                sub = raw[ns]
            elif ticker in raw.columns.get_level_values(0):
                sub = raw[ticker]
            else:
                return None
        else:
            sub = raw
        sub = sub.dropna(how='all')
        return sub.iloc[-2] if len(sub) >= 2 else None   # previous day
    except Exception:
        return None


def _get_open_price(raw: pd.DataFrame, ticker: str) -> Optional[float]:
    """Get today's open or yesterday's close as proxy."""
    ns = ticker if '.NS' in ticker else ticker + '.NS'
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw[ns] if ns in raw.columns.get_level_values(0) else raw
        else:
            sub = raw
        sub = sub.dropna(how='all')
        if len(sub) == 0:
            return None
        last = sub.iloc[-1]
        # Prefer Open if available and reasonable
        op = float(last.get('Open', 0) or 0)
        cl = float(last.get('Close', 0) or 0)
        return op if op > 0 else (cl if cl > 0 else None)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
# PAPER TRADING ENGINE
# ══════════════════════════════════════════════════════════════════════
class PaperTradingEngine:
    """
    Daily protocol (swing — no intraday monitoring):

    Step 1: Process exits on all open paper trades using
            previous day's OHLC from yfinance.

    Step 2: Enter new signals from scanner results using
            today's open price (or prev close as proxy).

    All state is persisted in SQLite.
    """

    def __init__(self, cfg: Config, re: MarketRegimeEngine,
                 risk: RiskManager, db: MKKDatabase):
        self.cfg  = cfg
        self.re   = re
        self.risk = risk
        self.db   = db
        self._today = date.today().isoformat()

    # ─────────────────────────────────────────────────────────────────
    # STEP 1: PROCESS EXITS
    # ─────────────────────────────────────────────────────────────────
    def process_exits(self) -> List[dict]:
        """
        Check all open paper trades against previous day's OHLC.
        Returns list of exit records processed.
        """
        ot = self.db.open_paper_trades()
        if ot.empty:
            log.info('No open paper trades to check for exits.')
            return []

        tickers = ot['ticker'].tolist()
        log.info(f'Processing exits for {len(tickers)} open trades...')

        # Fetch last 5 days so we reliably get yesterday's data
        raw = _fetch_ohlc(tickers, period='5d')

        exits_processed = []
        for _, trade in ot.iterrows():
            try:
                exit_record = self._check_exit(trade, raw)
                if exit_record:
                    exits_processed.append(exit_record)
            except Exception as e:
                log.error(f'Exit check failed for {trade["trade_id"]}: {e}')

        log.info(f'Exits processed: {len(exits_processed)}')
        return exits_processed

    def _check_exit(self, trade: pd.Series, raw: pd.DataFrame) -> Optional[dict]:
        tid    = trade['trade_id']
        ticker = trade['ticker']
        ep     = float(trade['entry_price'])
        sl     = float(trade['stop_loss'])
        t1     = float(trade['target_t1'] or 0)
        t2     = float(trade['target_t2'] or 0)
        t3     = float(trade['target_t3'] or 0)
        shares = int(trade['shares_remaining'] or trade['shares'])
        t1_hit = bool(trade['t1_hit'])
        t2_hit = bool(trade['t2_hit'])
        atr_v  = float(trade.get('atr_at_entry') or 0)

        entry_dt = date.fromisoformat(trade['entry_date'])
        hold_days = (date.today() - entry_dt).days

        prev = _get_ticker_ohlc(raw, ticker)
        if prev is None:
            log.warning(f'{ticker}: no OHLC data for exit check')
            return None

        prev_high  = float(prev.get('High', 0)  or 0)
        prev_low   = float(prev.get('Low', 0)   or 0)
        prev_close = float(prev.get('Close', 0) or 0)

        if prev_high == 0 and prev_low == 0:
            log.warning(f'{ticker}: zero OHLC — skipping')
            return None

        tc = TCModel.calc(sl, shares, self.cfg, 0)

        # ── Priority order: STOP first (protects capital) ──────────
        if prev_low > 0 and prev_low <= sl:
            exit_price = sl
            self.db.log_paper_exit(tid, {
                'exit_date': self._today,
                'exit_price': exit_price,
                'shares_exited': shares,
                'exit_type': 'STOPPED_OUT',
                'transaction_cost': tc['total_allin'],
                'notes': f'Low={prev_low:.2f} breached stop={sl:.2f}',
            })
            return {'ticker': ticker, 'exit_type': 'STOPPED_OUT',
                    'exit_price': exit_price, 'shares': shares,
                    'entry_price': ep, 'pnl': (exit_price - ep) * shares}

        # ── T3: full exit ──────────────────────────────────────────
        if t3 > 0 and prev_high >= t3 and not t2_hit:
            # If we haven't hit T2 yet, check if T1 and T2 are also hit
            pass  # fall through to T1 check first

        # ── T1: partial exit (30%) ─────────────────────────────────
        if t1 > 0 and prev_high >= t1 and not t1_hit:
            t1_shares = max(1, int(shares * 0.30))
            tc1 = TCModel.calc(t1, t1_shares, self.cfg, 0)
            self.db.log_paper_exit(tid, {
                'exit_date': self._today,
                'exit_price': t1,
                'shares_exited': t1_shares,
                'exit_type': 'T1_HIT',
                'transaction_cost': tc1['total_allin'],
                'notes': f'T1={t1:.2f} hit | stop moved to BE={ep:.2f}',
            })
            exits_processed_inner = [{
                'ticker': ticker, 'exit_type': 'T1_HIT',
                'exit_price': t1, 'shares': t1_shares, 'entry_price': ep,
                'pnl': (t1 - ep) * t1_shares}]
            # Refresh trade state for T2 check
            trade_updated = self.db.q(
                'SELECT * FROM paper_trades WHERE trade_id=?',
                (tid,)).fetchone()
            if trade_updated:
                t1_hit = True
                shares = int(trade_updated['shares_remaining'] or 0)

        # ── T2: partial exit (40% of original) ────────────────────
        if t2 > 0 and prev_high >= t2 and t1_hit and not t2_hit:
            # Refetch remaining shares
            trade_now = self.db.q(
                'SELECT shares_remaining,t2_hit FROM paper_trades WHERE trade_id=?',
                (tid,)).fetchone()
            if trade_now and not trade_now['t2_hit']:
                rem = int(trade_now['shares_remaining'] or 0)
                t2_shares = max(1, int(rem * 0.57))   # ~40% of original
                tc2 = TCModel.calc(t2, t2_shares, self.cfg, 0)
                self.db.log_paper_exit(tid, {
                    'exit_date': self._today,
                    'exit_price': t2,
                    'shares_exited': t2_shares,
                    'exit_type': 'T2_HIT',
                    'transaction_cost': tc2['total_allin'],
                })
                shares = rem - t2_shares
                t2_hit = True

        # ── T3: full exit of remaining ─────────────────────────────
        if t3 > 0 and prev_high >= t3 and t1_hit:
            trade_now = self.db.q(
                'SELECT shares_remaining FROM paper_trades WHERE trade_id=?',
                (tid,)).fetchone()
            if trade_now:
                rem = int(trade_now['shares_remaining'] or 0)
                if rem > 0:
                    tc3 = TCModel.calc(t3, rem, self.cfg, 0)
                    self.db.log_paper_exit(tid, {
                        'exit_date': self._today,
                        'exit_price': t3,
                        'shares_exited': rem,
                        'exit_type': 'T3_HIT',
                        'transaction_cost': tc3['total_allin'],
                    })
                    return {'ticker': ticker, 'exit_type': 'T3_HIT',
                            'exit_price': t3, 'shares': rem,
                            'entry_price': ep, 'pnl': (t3 - ep) * rem}

        # ── Time exit ──────────────────────────────────────────────
        if hold_days >= self.cfg.MAX_HOLD_DAYS and prev_close > 0:
            trade_now = self.db.q(
                'SELECT shares_remaining,status FROM paper_trades WHERE trade_id=?',
                (tid,)).fetchone()
            if trade_now and trade_now['status'] in ('OPEN', 'PARTIAL'):
                rem = int(trade_now['shares_remaining'] or 0)
                if rem > 0:
                    tc_t = TCModel.calc(prev_close, rem, self.cfg, 0)
                    self.db.log_paper_exit(tid, {
                        'exit_date': self._today,
                        'exit_price': prev_close,
                        'shares_exited': rem,
                        'exit_type': 'TIME_EXIT',
                        'transaction_cost': tc_t['total_allin'],
                        'notes': f'Max hold days={self.cfg.MAX_HOLD_DAYS} reached',
                    })
                    return {'ticker': ticker, 'exit_type': 'TIME_EXIT',
                            'exit_price': prev_close, 'shares': rem,
                            'entry_price': ep, 'pnl': (prev_close - ep) * rem}

        # ── Update trailing stop ───────────────────────────────────
        if prev_high > 0 and atr_v > 0:
            new_trail = prev_high - self.cfg.TRAIL_ATR * atr_v
            current_sl = float(self.db.q(
                'SELECT stop_loss FROM paper_trades WHERE trade_id=?',
                (tid,)).fetchone()[0] or sl)
            if new_trail > current_sl:
                self.db.q(
                    'UPDATE paper_trades SET stop_loss=? WHERE trade_id=?',
                    (round(new_trail, 2), tid))
                self.db.conn.commit()
                log.debug(f'{ticker}: trailing stop updated '
                          f'{current_sl:.2f} → {new_trail:.2f}')

        return None   # no exit triggered today

    # ─────────────────────────────────────────────────────────────────
    # STEP 2: PROCESS ENTRIES
    # ─────────────────────────────────────────────────────────────────
    def process_entries(self, scan_results: List[dict],
                        session_id: str) -> List[dict]:
        """
        Enter top Priority-ranked setups from scanner.
        Entry price = today's open (or prev close as proxy).
        Returns list of trade records entered.
        """
        if not self.re.allow_entry():
            log.info(f'Entries blocked — regime {self.re.regime}')
            return []

        # How many slots available?
        ot = self.db.open_paper_trades()
        current_open = len(ot) if not ot.empty else 0
        max_pos = self.re.max_positions()
        slots = max(0, max_pos - current_open)

        if slots == 0:
            log.info(f'No position slots available '
                     f'({current_open}/{max_pos} filled)')
            return []

        # Check macro blackout for today
        is_bo, bo_reason = self.db.is_macro_blackout(self._today)
        if is_bo:
            log.info(f'All entries blocked: macro blackout — {bo_reason}')
            return []

        log.info(f'Entry slots available: {slots} | '
                 f'Evaluating {len(scan_results)} setups...')

        # Fetch open prices for top candidates (batch)
        candidates = scan_results[:min(len(scan_results), slots * 3)]
        tickers = [r['Ticker'] for r in candidates]
        price_raw = _fetch_ohlc(tickers, period='2d')

        entries_taken = []
        # Load open position DFs for correlation check
        open_dfs = self._load_open_dfs()

        for r in candidates:
            if len(entries_taken) >= slots:
                break

            ticker = r['Ticker']
            ns     = ticker if '.NS' in ticker else ticker + '.NS'

            # Get open price
            open_px = _get_open_price(price_raw, ticker)
            if open_px is None or open_px <= 0:
                log.debug(f'{ticker}: no open price — skipping')
                continue

            # Gap filter — skip if gap > MAX_GAP_PCT
            signal_price = float(r.get('Price', open_px))
            gap_pct = (open_px - signal_price) / signal_price * 100
            if gap_pct > self.cfg.MAX_GAP_PCT:
                log.info(f'{ticker}: gap too large ({gap_pct:.1f}%) — skip')
                continue
            if open_px < signal_price * 0.97:   # gap down through stop zone
                log.info(f'{ticker}: gap down ({gap_pct:.1f}%) — skip')
                continue

            # Recalculate stop/targets from actual open price
            atr_mult   = float(r.get('ATR_Mult', 2.0))
            atr_val    = float(r.get('ATR_Val', 0))
            if atr_val <= 0:
                continue
            stop  = round(open_px - atr_mult * atr_val * self.re.stop_mult(), 2)
            if stop >= open_px:
                continue

            tt    = r.get('TradeType', 'SWING')
            tgts  = self.risk.targets(open_px, stop, tt)
            ps    = self.risk.size(self.cfg.TOTAL_CAPITAL,
                                   open_px, stop, tt, r.get('Avg_Val', 0))

            if ps['shares'] <= 0 or not ps.get('heat_ok', True):
                log.debug(f'{ticker}: sizing blocked — {ps.get("reason")}')
                continue

            # Sector exposure check
            sec_exp = self.db.paper_sector_exposure(self.cfg)
            ms = r.get('Macro_Sector', 'Other')
            if sec_exp.get(ms, 0) + (ps['invested'] / self.cfg.TOTAL_CAPITAL) \
                    > self.cfg.MAX_SECTOR_EXP:
                log.info(f'{ticker}: sector {ms} exposure limit reached')
                continue

            # Live correlation check against open positions
            try:
                import yfinance as yf
                start = datetime.today() - timedelta(days=self.cfg.CORR_LB + 10)
                new_raw = yf.download(ns, start=start, progress=False, timeout=12)
                new_df  = TI.prep(new_raw)
                if new_df is not None and open_dfs:
                    if TI.correlation(new_df, open_dfs,
                                      self.cfg.CORR_LB) > self.cfg.MAX_CORR:
                        log.info(f'{ticker}: correlation too high — skip')
                        continue
                    open_dfs.append(new_df)
            except Exception:
                pass

            tc = ps.get('tc', {})
            trade = {
                'ticker': ns.replace('.NS', ''),
                'trade_type': tt,
                'entry_date': self._today,
                'entry_price': round(open_px, 2),
                'shares': ps['shares'],
                'capital_invested': ps['invested'],
                'stop_loss': stop,
                'heat_contribution': ps.get('heat_contrib', 0),
                'target_t1': tgts['T1'],
                'target_t2': tgts['T2'],
                'target_t3': tgts['T3'],
                'pattern': r.get('Pattern', ''),
                'score': r.get('Score', 0),
                'priority_score': r.get('Priority_Score', 0),
                'regime': self.re.regime,
                'rs_3m': r.get('RS_3M') if r.get('RS_3M') != 'N/A' else None,
                'rs_rank': r.get('RS_Rank', 0),
                'vcp_quality': r.get('VCP_Quality', 0),
                'rsi_at_entry': r.get('RSI', 0),
                'atr_at_entry': atr_val,
                'atr_mult_used': atr_mult,
                'transaction_cost': tc.get('total_allin', 0),
                'slippage_est': tc.get('slippage', 0),
                'macro_sector': r.get('Macro_Sector', ''),
                'sector': r.get('Sector', ''),
                'session_id': session_id,
                'gap_pct': round(gap_pct, 2),
            }
            tid = self.db.log_paper_entry(trade)
            entries_taken.append({**trade, 'trade_id': tid})
            log.info(f'PAPER ENTRY: {ticker} @ ₹{open_px:.2f} | '
                     f'Stop ₹{stop:.2f} | T3 ₹{tgts["T3"]:.2f} | '
                     f'Qty {ps["shares"]} | {tt}')

        log.info(f'Entries taken: {len(entries_taken)}')
        return entries_taken

    def _load_open_dfs(self):
        dfs = []
        start = datetime.today() - timedelta(days=self.cfg.CORR_LB + 10)
        try:
            ot = self.db.open_paper_trades()
            if ot.empty:
                return dfs
            for _, row in ot.iterrows():
                try:
                    ns = row['ticker']
                    if '.NS' not in ns:
                        ns += '.NS'
                    raw = yf.download(ns, start=start, progress=False, timeout=10)
                    df  = TI.prep(raw)
                    if df is not None:
                        dfs.append(df)
                except Exception:
                    pass
        except Exception:
            pass
        return dfs

    # ─────────────────────────────────────────────────────────────────
    # PORTFOLIO SNAPSHOT
    # ─────────────────────────────────────────────────────────────────
    def take_snapshot(self) -> dict:
        ot = self.db.open_paper_trades()
        deployed = 0.0
        unreal   = 0.0
        heat     = 0.0

        if not ot.empty:
            tickers = ot['ticker'].tolist()
            raw = _fetch_ohlc(tickers, period='2d')
            for _, row in ot.iterrows():
                cur = _get_open_price(raw, row['ticker'])
                if cur:
                    sh = int(row['shares_remaining'] or row['shares'])
                    unreal   += (cur - float(row['entry_price'])) * sh
                    deployed += float(row['capital_invested'])
                heat += float(row.get('heat_contribution') or 0)

        capital = self.cfg.TOTAL_CAPITAL
        n_open  = len(ot) if not ot.empty else 0
        self.db.save_paper_snapshot(
            capital, deployed, unreal, n_open, self.re.regime, heat)

        snap = {
            'capital': capital, 'deployed': round(deployed, 2),
            'cash': round(capital - deployed, 2),
            'unreal_pnl': round(unreal, 2), 'n_open': n_open,
            'portfolio_heat_pct': round(heat * 100, 2),
        }
        log.info(f'Portfolio snapshot: deployed=₹{deployed:,.0f} '
                 f'unreal=₹{unreal:,.0f} heat={heat*100:.1f}%')
        return snap

    # ─────────────────────────────────────────────────────────────────
    # OPEN POSITIONS SUMMARY (for email)
    # ─────────────────────────────────────────────────────────────────
    def open_positions_summary(self) -> List[dict]:
        ot = self.db.open_paper_trades()
        if ot.empty:
            return []
        tickers = ot['ticker'].tolist()
        raw = _fetch_ohlc(tickers, period='2d')
        rows = []
        for _, trade in ot.iterrows():
            cur = _get_open_price(raw, trade['ticker'])
            ep  = float(trade['entry_price'])
            sl  = float(trade['stop_loss'])
            sh  = int(trade['shares_remaining'] or trade['shares'])
            cur = cur or ep
            unr = (cur - ep) * sh
            rps = float(trade.get('risk_per_share') or (ep - sl))
            rm  = unr / (rps * sh) if rps * sh else 0
            dist_stop = (cur - sl) / cur * 100 if cur > 0 else 0
            hd = (date.today() - date.fromisoformat(trade['entry_date'])).days
            rows.append({
                'ticker': trade['ticker'],
                'entry_date': trade['entry_date'],
                'entry_price': ep,
                'current_price': round(cur, 2),
                'stop': sl,
                'shares': sh,
                'unreal_pnl': round(unr, 2),
                'r_mult': round(rm, 2),
                'hold_days': hd,
                'dist_stop_pct': round(dist_stop, 1),
                'sector': trade.get('macro_sector', ''),
                'pattern': trade.get('pattern', ''),
            })
        return rows
