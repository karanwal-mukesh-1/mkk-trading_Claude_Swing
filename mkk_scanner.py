"""
mkk_scanner.py — Elite Swing Scanner + Sector Heatmap + Bulk Backtest
"""
import logging, time
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

from mkk_core import (Config, MKKDatabase, IndexCache, TI,
                      MarketRegimeEngine, RiskManager, TCModel,
                      PriorityScorer, classify_stock)

log = logging.getLogger('mkk')


# ══════════════════════════════════════════════════════════════════════
# SECTOR HEATMAP
# ══════════════════════════════════════════════════════════════════════
SECTOR_ETFS = {
    'BFSI':           '^NSEBANK',
    'Technology':     '^CNXIT',
    'Healthcare':     '^CNXPHARMA',
    'Auto & Mobility':'^CNXAUTO',
    'Energy & Power': '^CNXENERGY',
    'Consumer':       '^CNXFMCG',
    'Industrials':    '^CNXINFRA',
    'Materials':      '^CNXMETAL',
    'Real Estate':    '^CNXREALTY',
}


class SectorHeatmap:
    def __init__(self, cfg: Config, re: MarketRegimeEngine, db: MKKDatabase):
        self.cfg = cfg
        self.re  = re
        self.db  = db
        self._start = datetime.today() - timedelta(days=150)
        self._results: List[dict] = []
        self._gate_cache: Dict[str, bool] = {}

    def _sector_rs(self, macro_sector: str):
        import logging as _lg
        etf = SECTOR_ETFS.get(macro_sector)
        if not etf:
            return None
        yf_log = _lg.getLogger('yfinance'); prev = yf_log.level
        yf_log.setLevel(_lg.CRITICAL)
        df = IndexCache.get(etf, self._start)
        yf_log.setLevel(prev)
        if df.empty or len(df) < 63:
            return None
        bench = self.re.n50
        return TI.rs(df, bench, 63)

    def _trend_score(self, tickers: List[str]) -> Tuple[float, float]:
        if not tickers:
            return 0.0, 0.0
        sample = tickers[:40]
        above50 = []
        try:
            import logging as _lg
            yf_log = _lg.getLogger('yfinance'); prev = yf_log.level
            yf_log.setLevel(_lg.CRITICAL)
            raw = yf.download(sample, period='3mo', progress=False, timeout=20)
            yf_log.setLevel(prev)
            if isinstance(raw.columns, pd.MultiIndex):
                closes = raw['Close']
            elif 'Close' in raw.columns:
                closes = raw[['Close']]
            else:
                closes = pd.DataFrame()
            if not closes.empty:
                for col in closes.columns:
                    ser = closes[col].dropna()
                    if len(ser) >= 50:
                        ma50 = ser.rolling(50).mean().iloc[-1]
                        above50.append(1 if float(ser.iloc[-1]) > float(ma50) else 0)
        except Exception as e:
            log.debug(f'Trend score batch download: {e}')
        if not above50:
            return 0.0, 0.0
        pct = sum(above50) / len(above50) * 100
        return round(pct, 1), round(pct, 1)

    def compute(self, scan_results: List[dict] = [],
                portfolio_exposure: Dict[str, float] = {}) -> List[dict]:
        log.info('Computing sector heatmap...')
        rows = []
        sector_dist = self.db.qdf(
            "SELECT macro_sector, sector, ns_ticker FROM universe "
            "WHERE is_active=1 AND series IN ('EQ','BE') "
            "ORDER BY macro_sector, sector")
        if sector_dist.empty:
            return rows
        sector_groups = sector_dist.groupby(['macro_sector', 'sector'])

        # Hit rate from scan results
        hit_map: Dict[tuple, int] = {}
        for r in scan_results:
            k = (r.get('Macro_Sector', 'Other'), r.get('Sector', 'Unclassified'))
            hit_map[k] = hit_map.get(k, 0) + 1

        for (ms, sc), grp in sector_groups:
            tickers = grp['ns_ticker'].tolist()
            n = len(tickers)
            rs = self._sector_rs(ms)
            pct50, tscore = self._trend_score(tickers[:30])
            hits = hit_map.get((ms, sc), 0)
            hit_rate = hits / n * 100 if n > 0 else 0
            exp = portfolio_exposure.get(ms, 0) * 100
            gate = ((tscore >= self.cfg.SECTOR_TREND_MIN) and
                    (rs is None or rs >= self.cfg.SECTOR_RS_MIN))
            rows.append({
                'macro_sector': ms, 'sector': sc, 'n_stocks': n,
                'rs_3m': round(rs, 3) if rs else None,
                'trend_score': round(tscore, 1),
                'pct_above_50ma': round(pct50, 1),
                'scan_hit_rate': round(hit_rate, 1),
                'portfolio_exposure': round(exp, 1),
                'gate_open': gate,
            })
        self._results = rows
        self._gate_cache = {f"{r['macro_sector']}|{r['sector']}": r['gate_open']
                            for r in rows}
        try:
            self.db.save_sector_snapshot(rows)
        except Exception as e:
            log.warning(f'Sector snapshot save: {e}')
        self._log_heatmap()
        return rows

    def _log_heatmap(self):
        if not self._results:
            return
        df = pd.DataFrame(self._results).sort_values(
            'rs_3m', ascending=False, na_position='last')
        log.info('── SECTOR HEATMAP ──────────────────────────────────────')
        log.info(f"  {'Macro Sector':<22} {'Sector':<22} {'RS3M':>8} "
                 f"{'Trend%':>7} {'Hit%':>6} {'Gate':>5}")
        for _, r in df.iterrows():
            rs_s = f"{r['rs_3m']:.3f}" if r['rs_3m'] else '  N/A'
            gate = 'OPEN' if r['gate_open'] else 'SHUT'
            log.info(f"  {r['macro_sector']:<22} {r['sector']:<22} "
                     f"{rs_s:>8} {r['trend_score']:>6.0f}% "
                     f"{r['scan_hit_rate']:>5.1f}% {gate:>5}")
        log.info('────────────────────────────────────────────────────────')

    def gate_open(self, macro_sector: str, sector: str) -> bool:
        return self._gate_cache.get(f'{macro_sector}|{sector}', True)

    def top_sectors(self, n: int = 5) -> List[dict]:
        df = pd.DataFrame(self._results).dropna(subset=['rs_3m'])
        df = df.sort_values('rs_3m', ascending=False)
        return df.head(n).to_dict('records')


# ══════════════════════════════════════════════════════════════════════
# ELITE SWING SCANNER
# ══════════════════════════════════════════════════════════════════════
class EliteSwingScanner:
    def __init__(self, cfg: Config, re: MarketRegimeEngine,
                 risk: RiskManager, db: MKKDatabase, hm: SectorHeatmap):
        self.cfg  = cfg
        self.re   = re
        self.risk = risk
        self.db   = db
        self.hm   = hm
        self.ps   = PriorityScorer(cfg)
        self.results: List[dict] = []
        self.rs_pool: List[dict] = []
        self.st = {k: 0 for k in [
            'total', 'fail', 'sect', 'pv', 'tr', 'co',
            'mo', 'rs', 'rss', 'vcp', 'corr', 'score',
            'heat', 'macro', 'elite', 'dur']}
        self._open_dfs = self._load_open_position_dfs()
        self._t0 = datetime.now()

    def _load_open_position_dfs(self) -> List[pd.DataFrame]:
        out = []
        start = datetime.today() - timedelta(days=self.cfg.CORR_LB + 10)
        try:
            ot = self.db.open_paper_trades()
            if ot.empty:
                return out
            for _, row in ot.iterrows():
                try:
                    ns = row['ticker']
                    if '.NS' not in ns:
                        ns += '.NS'
                    raw = yf.download(ns, start=start, progress=False, timeout=10)
                    df = TI.prep(raw)
                    if df is not None:
                        out.append(df)
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def _dl(self, ticker: str) -> Optional[pd.DataFrame]:
        for attempt in range(2):
            try:
                start = datetime.today() - timedelta(days=self.cfg.LOOKBACK + 50)
                raw = yf.download(ticker, start=start, progress=False, timeout=15)
                df = TI.prep(raw)
                if df is not None and len(df) >= self.cfg.MIN_BARS:
                    return df
                return None
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)
                else:
                    log.debug(f'{ticker} download failed: {e}')
        return None

    def _indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['MA21']   = df['Close'].rolling(self.cfg.MA_FAST).mean()
        df['MA50']   = df['Close'].rolling(self.cfg.MA_MED).mean()
        df['MA200']  = df['Close'].rolling(self.cfg.MA_SLOW).mean()
        df['EMA9']   = df['Close'].ewm(span=self.cfg.EMA_S).mean()
        df['EMA21']  = df['Close'].ewm(span=self.cfg.EMA_M).mean()
        df['RSI']    = TI.rsi(df['Close'], self.cfg.RSI_PERIOD)
        df['ATR']    = TI.atr(df, self.cfg.ATR_PERIOD)
        m, s, _ = TI.macd(df['Close'], self.cfg.MACD_FAST,
                           self.cfg.MACD_SLOW, self.cfg.MACD_SIG)
        df['MACD'] = m; df['MACD_S'] = s
        return df

    def _check_earnings(self, ticker: str) -> int:
        """Returns 1 if within earnings blackout, 0 otherwise."""
        try:
            est_date, _ = self.db.fetch_earnings_date(ticker)
            if est_date:
                days_to = (date.fromisoformat(est_date) - date.today()).days
                if abs(days_to) <= self.cfg.EARNINGS_BK:
                    return 1
        except Exception:
            pass
        return 0

    def _scan_one(self, ticker: str, macro_sector: str,
                  sector: str, industry: str) -> Optional[dict]:
        df = self._dl(ticker)
        if df is None:
            self.st['fail'] += 1
            return None

        df = self._indicators(df)
        cur = df.iloc[-1]
        if pd.isna(cur['ATR']) or float(cur['ATR']) <= 0:
            return None

        price    = float(cur['Close'])
        avg_vol  = float(df['Volume'].rolling(20).mean().iloc[-1])
        avg_val  = avg_vol * price
        min_av   = self.cfg.min_avg_val()

        # ── S1: Price & Liquidity ──────────────────────────────────
        if (price < self.cfg.MIN_PRICE or pd.isna(avg_vol)
                or avg_vol < self.cfg.MIN_AVG_VOL or avg_val < min_av):
            return None
        self.st['pv'] += 1

        # ── S2: Volume Contraction ─────────────────────────────────
        v5  = df['Volume'].iloc[-5:].mean()
        v25 = df['Volume'].iloc[-25:-5].mean()
        vc  = float(v5 / v25) if v25 > 0 else 999
        if vc > self.cfg.VOL_CONTR_LIM:
            return None

        # ── S3: Trend (daily + weekly) ─────────────────────────────
        if pd.isna(cur['MA21']) or pd.isna(cur['MA50']):
            return None
        if price < float(cur['MA21']) or float(cur['MA21']) < float(cur['MA50']):
            return None
        if not TI.weekly_above_ma(df, self.cfg.WEEKLY_MA):
            return None
        a200 = (not pd.isna(cur.get('MA200', float('nan'))) and
                price > float(cur['MA200']))
        self.st['tr'] += 1

        # ── S4: Consolidation ──────────────────────────────────────
        if not TI.consolidating(df, self.cfg.CONSOL_DAYS,
                                 self.cfg.MAX_CONSOL_RANGE):
            return None
        pat = TI.pattern(df, 20)
        self.st['co'] += 1

        # ── S5: Momentum ───────────────────────────────────────────
        rsi = float(cur['RSI'])
        if rsi < self.cfg.RSI_MIN or rsi > self.cfg.RSI_HARD:
            return None
        hi60    = float(df['High'].iloc[-self.cfg.SWING_HI_LB:].max())
        pct_hi  = (hi60 - price) / hi60 * 100
        if pct_hi > self.cfg.SWING_HI_THR * 100:
            return None
        self.st['mo'] += 1

        # ── S6: Relative Strength (multi-benchmark) ────────────────
        bench = self.re.bench_for(avg_val)
        rs3 = rs6 = None
        rsi_ok = False
        if not bench.empty:
            rs3 = TI.rs(df, bench, 63)
            rs6 = TI.rs(df, bench, 126)
            if rs3 is None or rs3 < self.cfg.RS_3M_MIN:
                return None
            if rs6 is None or rs6 < self.cfg.RS_6M_MIN:
                return None
            self.st['rs'] += 1
            _, _, rsi_ok = TI.rs_slope(df, bench, 63, self.cfg.RS_SLOPE_LB)
            if not rsi_ok:
                return None
            self.st['rss'] += 1
            self.rs_pool.append({'t': ticker, 'rs3': rs3})

        # Sector gate — bypass allowed if RS very strong
        gate_ok = self.hm.gate_open(macro_sector, sector)
        if not gate_ok:
            if rs3 and rs3 > 1.15:
                pass   # high-RS bypass
            else:
                self.st['sect'] += 1
                return None

        # ── S7: VCP ────────────────────────────────────────────────
        vcp_ok = False; vq = 0
        if self.cfg.VCP_ENABLE:
            for lb in self.cfg.VCP_LOOKBACKS:
                ok, q = TI.vcp(df, lb)
                if ok and q > vq:
                    vcp_ok = True; vq = q
            if not vcp_ok:
                return None
        self.st['vcp'] += 1

        # ── S8: Correlation filter ─────────────────────────────────
        if (self._open_dfs and
                TI.correlation(df, self._open_dfs, self.cfg.CORR_LB)
                > self.cfg.MAX_CORR):
            self.st['corr'] += 1
            return None

        # ── Macro event guard (Gap 5) ──────────────────────────────
        is_blackout, blackout_reason = self.db.is_macro_blackout(
            date.today().isoformat())
        if is_blackout:
            self.st['macro'] = self.st.get('macro', 0) + 1
            log.debug(f'{ticker} skipped: macro blackout — {blackout_reason}')
            return None

        # ── Breakout proximity ─────────────────────────────────────
        res      = float(df['Close'].rolling(self.cfg.RES_PERIOD).max().iloc[-1])
        dist_res = (res - price) / price * 100
        vi       = (float(cur['Volume']) >
                    float(df['Volume'].iloc[-10:-1].mean()) * 1.1)
        macd_pos = (float(cur['MACD']) > float(cur['MACD_S']) and
                    float(cur['MACD']) > 0)
        ema_cross = float(cur['EMA9']) > float(cur['EMA21'])

        # ── Gap 6: volatility-adjusted ATR multiplier ──────────────
        atr_mult = TI.vol_adj_atr_mult(df, self.cfg.ATR_PERIOD)
        atr_val  = float(cur['ATR'])
        stop     = price - atr_mult * atr_val * self.re.stop_mult()
        risk_pct = (price - stop) / price * 100

        # ── Gap 7: earnings check ──────────────────────────────────
        ne = self._check_earnings(ticker)

        # ── Score ──────────────────────────────────────────────────
        rs3_v = rs3 or 0
        sc = 0
        sc += (15 if a200 else 0)
        sc += (15 if vc < 0.50 else 10 if vc < 0.65 else 3)
        sc += (10 if 50 < rsi < 65 else 5 if 40 <= rsi <= 72 else 0)
        sc += (12 if pat == 'High Tight Flag' else
               10 if pat == 'Cup Pattern'     else
                9 if pat == 'Flat Base'       else 4)
        sc += (5 if vi else 0) + (5 if macd_pos else 0) + (5 if ema_cross else 0)
        sc += (8 if rsi_ok else 0)
        sc += (15 if rs3_v > 1.10 else 5)
        sc += (7 if vq > 60 else 4 if vq > 40 else 0)
        sc += (15 if dist_res < self.cfg.BO_PROX else 5)
        sc = int(min(sc, 100))

        ms = self.risk.min_score()
        if sc < ms:
            self.st['score'] += 1
            return None

        # ── Trade type ─────────────────────────────────────────────
        tt = ('POSITIONAL'
              if rs3_v > self.cfg.POS_RS_3M_MIN and vq > self.cfg.POS_VCP_MIN
              else 'SWING')
        tgts = self.risk.targets(price, stop, tt)
        ps   = self.risk.size(self.cfg.TOTAL_CAPITAL, price, stop, tt, avg_val)

        if not ps.get('heat_ok', True):
            self.st['heat'] += 1
            return None

        tc = ps.get('tc', {})
        self.st['elite'] += 1

        nm = ticker.replace(self.cfg.EXCHANGE, '')
        return {
            'Ticker': nm, 'Price': round(price, 2), 'Score': sc,
            'TradeType': tt, 'Pattern': pat,
            'RSI': round(rsi, 1),
            'RS_3M': round(rs3, 3) if rs3 else 'N/A',
            'RS_6M': round(rs6, 3) if rs6 else 'N/A',
            'RS_Improving': '✓' if rsi_ok else '✗', 'RS_Rank': 0,
            'VCP_Quality': round(vq, 1), 'Vol_Contraction': round(vc, 2),
            'Pct_From_High': round(pct_hi, 2), 'To_Resistance%': round(dist_res, 2),
            'Stop_Loss': round(stop, 2), 'ATR_Mult': atr_mult, 'Risk_%': round(risk_pct, 2),
            'T1': tgts['T1'], 'T2': tgts['T2'], 'T3': tgts['T3'],
            'Shares': ps['shares'], 'Capital': ps['invested'],
            'Risk_INR': ps['risk_amount'],
            'Slippage': tc.get('slippage', 0), 'TC_AllIn': tc.get('total_allin', 0),
            'Above_200MA': '✓' if a200 else '✗',
            'MACD_Pos': '✓' if macd_pos else '✗',
            'EMA_Cross': '✓' if ema_cross else '✗',
            'Near_Earnings': ne, 'Regime': self.re.regime,
            'Avg_Vol': int(avg_vol), 'Avg_Val': avg_val,
            'Heat_Contrib': ps.get('heat_contrib', 0),
            'Sector_Gate': gate_ok,
            'Macro_Sector': macro_sector, 'Sector': sector, 'Industry': industry,
            'Weekly_MA20': 1,
            'ATR_Val': atr_val,
            '_df': df,   # carry for correlation; stripped before DB save
        }

    def _assign_rs_ranks(self):
        if not self.results or not self.rs_pool:
            return
        all_rs = sorted([x['rs3'] for x in self.rs_pool if x['rs3']], reverse=True)
        for r in self.results:
            v = r.get('RS_3M')
            if v and v != 'N/A':
                pos = len([x for x in all_rs if x > float(v)])
                r['RS_Rank'] = int((1 - pos / len(all_rs)) * 100) if all_rs else 0

    def _assign_priority(self):
        for r in self.results:
            gate = r.get('Sector_Gate', True)
            r['Priority_Score'] = self.ps.compute(r, gate)
        self.results.sort(key=lambda x: x['Priority_Score'], reverse=True)
        for i, r in enumerate(self.results, 1):
            r['Priority_Rank'] = i

    def scan(self, tickers_with_sectors: list) -> List[dict]:
        self._t0 = datetime.now()
        log.info(f'Scan start: {len(tickers_with_sectors)} stocks | {self.re.regime}')
        for i, (ns_ticker, mac, sec, ind) in enumerate(tickers_with_sectors, 1):
            self.st['total'] += 1
            if i % 250 == 0:
                el = (datetime.now() - self._t0).seconds / 60
                log.info(f'  Progress: {i}/{len(tickers_with_sectors)} '
                         f'setups={self.st["elite"]} {el:.1f}min')
            r = self._scan_one(ns_ticker, mac, sec, ind)
            if r:
                self.results.append(r)

        self._assign_rs_ranks()
        self._assign_priority()
        el = (datetime.now() - self._t0).seconds / 60
        self.st['dur'] = round(el, 2)
        log.info(f'Scan done: {self.st["elite"]} setups in {el:.1f}min')
        self._log_funnel()
        return self.results

    def _log_funnel(self):
        s = self.st
        log.info('── SCAN FUNNEL ─────────────────────────────────────────')
        log.info(f'  Total scanned    : {s["total"]}')
        log.info(f'  Data failed      : {s["fail"]}')
        log.info(f'  Price/vol pass   : {s["pv"]}')
        log.info(f'  Trend pass       : {s["tr"]}')
        log.info(f'  Consolidation    : {s["co"]}')
        log.info(f'  Momentum         : {s["mo"]}')
        log.info(f'  RS pass          : {s["rs"]}')
        log.info(f'  RS slope pass    : {s["rss"]}')
        log.info(f'  VCP pass         : {s["vcp"]}')
        log.info(f'  Corr filtered    : {s["corr"]}')
        log.info(f'  Sector blocked   : {s["sect"]}')
        log.info(f'  Macro blackout   : {s.get("macro",0)}')
        log.info(f'  Score filtered   : {s["score"]}')
        log.info(f'  Heat blocked     : {s["heat"]}')
        log.info(f'  ELITE SETUPS     : {s["elite"]}')
        log.info('────────────────────────────────────────────────────────')

    def save(self, sid: str):
        # Strip internal df references before saving
        clean = [{k: v for k, v in r.items() if k != '_df'}
                 for r in self.results]
        if clean:
            try:
                self.db.save_results(clean, sid)
            except Exception as e:
                log.error(f'save_results: {e}')
        log.info(f'Saved {len(clean)} results to DB')
        return clean


# ══════════════════════════════════════════════════════════════════════
# BULK BACKTEST (Gap 1)
# ══════════════════════════════════════════════════════════════════════
class BulkBacktest:
    """
    Walk-forward OOS backtest across multiple stocks.
    60% in-sample warmup, 40% out-of-sample scored.
    Stores per-stock results in bulk_backtest_results table.
    """
    def __init__(self, cfg: Config, db: MKKDatabase):
        self.cfg = cfg
        self.db  = db

    def _run_one(self, ticker: str, years: int = 3,
                 capital: float = None) -> Optional[dict]:
        cap = capital or self.cfg.TOTAL_CAPITAL
        start = datetime.today() - timedelta(days=years * 365 + 60)
        try:
            raw = yf.download(ticker, start=start, progress=False, timeout=20)
            df = TI.prep(raw)
        except Exception as e:
            log.debug(f'BT {ticker}: {e}')
            return None
        if df is None or len(df) < 200:
            return None

        bench = IndexCache.get(self.cfg.NIFTY50, start)
        df['MA21']  = df['Close'].rolling(21).mean()
        df['MA50']  = df['Close'].rolling(50).mean()
        df['MA200'] = df['Close'].rolling(200).mean()
        df['RSI']   = TI.rsi(df['Close'])
        df['ATR']   = TI.atr(df)
        df = df.dropna()

        split_pt = int(len(df) * 0.60)
        oos = df.iloc[split_pt:].copy().reset_index(drop=False)

        cap2 = float(cap)
        pos = entry_p = stop_p = shares = entry_i = 0
        hi_p = lo_p = 0.0
        trades = []
        equity = [cap2]

        for i in range(10, len(oos)):
            row   = oos.iloc[i]
            price = float(row['Close'])

            if pos:
                hi_p = max(hi_p, float(row['High']))
                lo_p = min(lo_p, float(row['Low']))

            if pos == 1:
                mfe = hi_p - entry_p
                mae = entry_p - lo_p
                tgt = entry_p + 2.5 * (entry_p - stop_p)
                xp = xt = None
                if float(row['Low']) <= stop_p:
                    xp = stop_p; xt = 'STOP'
                elif float(row['High']) >= tgt:
                    xp = tgt; xt = 'TARGET'
                elif (i - entry_i) >= self.cfg.MAX_HOLD_DAYS:
                    xp = price; xt = 'TIME'
                if xp:
                    pnl = (xp - entry_p) * shares
                    cap2 += pnl
                    rps = entry_p - stop_p
                    rm  = pnl / (rps * shares) if rps * shares else 0
                    trades.append({
                        't': xt, 'pnl': round(pnl, 2),
                        'r': round(rm, 3), 'hd': i - entry_i,
                        'mae': round(mae, 2), 'mfe': round(mfe, 2),
                    })
                    pos = shares = 0
                else:
                    # Trail stop
                    atr_v = float(row['ATR'])
                    new_stop = float(row['High']) - self.cfg.TRAIL_ATR * atr_v
                    if new_stop > stop_p:
                        stop_p = new_stop

            if pos == 0:
                trend = (price > float(row['MA21']) > float(row['MA50']))
                rsi_ok = 40 <= float(row['RSI']) <= 70
                v5  = oos['Volume'].iloc[max(0, i-5):i].mean()
                v20 = oos['Volume'].iloc[max(0, i-25):max(0, i-5)].mean()
                vc_ok = float(v5 / v20) < 0.70 if v20 > 0 else False
                h60 = oos['High'].iloc[max(0, i-60):i].max()
                nh  = (h60 - price) / h60 < 0.08 if h60 > 0 else False
                c8  = oos['Close'].iloc[max(0, i-8):i]
                base_ok = ((c8.max() - c8.min()) / c8.min() <= 0.06
                           if len(c8) > 0 and c8.min() > 0 else False)
                if all([trend, rsi_ok, vc_ok, nh, base_ok]):
                    # Vol-adjusted ATR for stop
                    atr_pct = TI.atr_percentile(oos.iloc[max(0,i-63):i+1]
                                                 .rename(columns={'index':'Date'})
                                                 if 'index' in oos.columns
                                                 else oos.iloc[max(0,i-63):i+1])
                    atr_mult = (2.5 if atr_pct > 80 else
                                1.5 if atr_pct < 20 else 2.0)
                    atr_v    = float(row['ATR'])
                    stop_p   = price - atr_mult * atr_v
                    rps      = price - stop_p
                    s2       = int((cap2 * 0.015) / rps) if rps > 0 else 0
                    if s2 > 0 and s2 * price <= cap2 * 0.90:
                        entry_p = price; shares = s2
                        cap2   -= s2 * price
                        pos = 1; entry_i = i
                        hi_p = lo_p = price

            equity.append(cap2 + (pos * shares * price))

        if not trades:
            return None

        df2  = pd.DataFrame(trades)
        n    = len(df2); w = (df2['pnl'] > 0).sum(); wr = w / n
        aw   = df2[df2['pnl'] > 0]['pnl'].mean() if w else 0
        al   = df2[df2['pnl'] <= 0]['pnl'].mean() if (n - w) else -1
        cagr = ((cap2 / cap) ** (1 / years) - 1) * 100 if cap > 0 else 0
        eq   = np.array(equity)
        rm_arr = np.maximum.accumulate(eq)
        mdd  = float(((rm_arr - eq) / rm_arr).max() * 100)

        bcagr = 0.0
        if not bench.empty and len(bench) > 252:
            bc    = (float(bench['Close'].iloc[-1]) /
                     float(bench['Close'].iloc[-int(years * 252)]) - 1)
            bcagr = round(((1 + bc) ** (1 / years) - 1) * 100, 2)

        return {
            'ticker': ticker, 'years': years,
            'cagr_pct': round(cagr, 2), 'max_dd_pct': round(mdd, 2),
            'trades': n, 'win_rate_pct': round(wr * 100, 1),
            'avg_r': round(df2['r'].mean(), 3),
            'profit_factor': round(abs(aw / al), 2) if al else 0,
            'bench_cagr_pct': bcagr, 'alpha_pct': round(cagr - bcagr, 2),
            'avg_mae': round(df2['mae'].mean(), 2),
            'avg_mfe': round(df2['mfe'].mean(), 2),
        }

    def run(self, tickers: List[str], years: int = 3) -> pd.DataFrame:
        log.info(f'Bulk backtest: {len(tickers)} stocks | {years}Y')
        results = []
        run_id_base = f"BT_{date.today().isoformat()}"
        for i, t in enumerate(tickers, 1):
            log.info(f'  BT {i}/{len(tickers)}: {t}')
            r = self._run_one(t, years)
            if r:
                results.append(r)
                try:
                    self.db.q(
                        'INSERT OR REPLACE INTO bulk_backtest_results'
                        '(run_id,run_date,ticker,years,cagr_pct,max_dd_pct,'
                        'trades,win_rate_pct,avg_r,profit_factor,'
                        'bench_cagr_pct,alpha_pct,avg_mae,avg_mfe) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (f"{run_id_base}_{t}", date.today().isoformat(),
                         r['ticker'], r['years'], r['cagr_pct'], r['max_dd_pct'],
                         r['trades'], r['win_rate_pct'], r['avg_r'],
                         r['profit_factor'], r['bench_cagr_pct'],
                         r['alpha_pct'], r['avg_mae'], r['avg_mfe']))
                    self.db.conn.commit()
                except Exception as e:
                    log.warning(f'BT save {t}: {e}')

        if not results:
            log.warning('Bulk backtest: no valid results')
            return pd.DataFrame()

        df = pd.DataFrame(results).sort_values('alpha_pct', ascending=False)

        log.info('── BULK BACKTEST AGGREGATE STATS ───────────────────────')
        log.info(f'  Stocks completed     : {len(df)}')
        log.info(f'  Median CAGR          : {df["cagr_pct"].median():+.1f}%')
        log.info(f'  Median Alpha         : {df["alpha_pct"].median():+.1f}%')
        log.info(f'  Positive Alpha       : '
                 f'{(df["alpha_pct"]>0).sum()}/{len(df)} '
                 f'({(df["alpha_pct"]>0).mean()*100:.0f}%)')
        log.info(f'  Avg Win Rate         : {df["win_rate_pct"].mean():.1f}%')
        log.info(f'  Avg Profit Factor    : {df["profit_factor"].mean():.2f}')
        log.info(f'  Avg Max Drawdown     : {df["max_dd_pct"].mean():.1f}%')
        log.info(f'  Avg MAE / MFE        : '
                 f'{df["avg_mae"].mean():,.0f} / {df["avg_mfe"].mean():,.0f}')
        log.info('────────────────────────────────────────────────────────')
        log.info('\n  Top 10 by Alpha:')
        for _, row in df.head(10).iterrows():
            log.info(f'  {row["ticker"]:<15} CAGR={row["cagr_pct"]:+.1f}%  '
                     f'Alpha={row["alpha_pct"]:+.1f}%  '
                     f'WR={row["win_rate_pct"]:.0f}%  '
                     f'PF={row["profit_factor"]:.2f}  '
                     f'N={row["trades"]}')
        return df
