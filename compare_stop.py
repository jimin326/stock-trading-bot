from src.backtest import run_scanner_backtest, BacktestResult
from src.indicators import add_indicators
from src.config import (POSITION_SIZE_TIERS, SCAN_UNIVERSE, GAP_THRESHOLD, VOL_RATIO_MIN,
                        SCAN_TOP_N, EMA_TOUCH_PCT, PULLBACK_LOWER_PCT, VWAP_TOUCH_PCT,
                        PREMARKET_TOUCH_PCT, SIDEWAYS_WINDOW, SIDEWAYS_CROSSES,
                        COOLDOWN_BARS, HARD_STOP_PCT)
from src.risk import position_size
from src.backtest import _check_entry, _is_sideways, Trade
from dataclasses import dataclass, field
import numpy as np

# ── 종가 기준 하드손절 버전 ───────────────────────────────────
def check_exit_long_close(close, open_, low, ema9, entry, strict=False):
    stop_price = entry * (1 - HARD_STOP_PCT)
    if close <= stop_price:
        return True, close, f"하드손절(-{HARD_STOP_PCT*100:.0f}%)[종가]"
    if max(open_, close) < ema9:
        return True, close, "EMA8하향이탈"
    return False, close, ""

def check_exit_short_close(close, open_, high, ema9, entry, strict=False):
    stop_price = entry * (1 + HARD_STOP_PCT)
    if close >= stop_price:
        return True, close, f"하드손절(-{HARD_STOP_PCT*100:.0f}%)[종가]"
    if min(open_, close) > ema9:
        return True, close, "EMA8상향이탈"
    return False, close, ""

# ── 공통 백테스트 로직 (stop_mode 파라미터) ──────────────────
def run_with_stop_mode(stop_mode='high_low'):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from datetime import datetime, timedelta
    import src.config as _cfg
    import pandas as pd

    days = 120
    client = StockHistoricalDataClient(_cfg.ALPACA_API_KEY, _cfg.ALPACA_SECRET_KEY)
    end         = datetime.now()
    start_intra = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_daily = end - timedelta(days=days + 35)

    daily_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SCAN_UNIVERSE, timeframe=TimeFrame.Day,
        start=start_daily, feed=DataFeed.IEX,
    )).data

    intraday_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SCAN_UNIVERSE,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start_intra, feed=DataFeed.IEX, extended_hours=True,
    )).data

    daily_dfs = {}
    for sym, bars in daily_bars.items():
        df = pd.DataFrame([{"date": b.timestamp.date(), "open": b.open, "high": b.high,
                             "low": b.low, "close": b.close, "volume": b.volume}
                           for b in bars]).set_index("date")
        daily_dfs[sym] = df

    intraday_dfs = {}
    for sym, bars in intraday_bars.items():
        df = pd.DataFrame([{"timestamp": b.timestamp, "open": b.open, "high": b.high,
                             "low": b.low, "close": b.close, "volume": b.volume}
                           for b in bars]).set_index("timestamp")
        intraday_dfs[sym] = df

    all_dates = sorted(set(
        d for sym_df in daily_dfs.values()
        for d in sym_df.index if d >= start_intra.date()
    ))

    from src.broker import get_shortable_set
    shortable = get_shortable_set(SCAN_UNIVERSE)

    result = BacktestResult(symbol="SCANNER", initial_equity=10000.0)
    equity = 10000.0

    check_long  = check_exit_long_close  if stop_mode == 'close' else __import__('src.risk', fromlist=['check_exit_long']).check_exit_long
    check_short = check_exit_short_close if stop_mode == 'close' else __import__('src.risk', fromlist=['check_exit_short']).check_exit_short

    for date in all_dates:
        candidates = []
        for sym, ddf in daily_dfs.items():
            date_idx = ddf.index.tolist()
            if date not in date_idx: continue
            pos = date_idx.index(date)
            if pos < 21: continue
            today_bar = ddf.loc[date]; prev_bar = ddf.iloc[pos-1]
            hist_bars = ddf.iloc[pos-21:pos-1]
            if prev_bar["close"] == 0 or hist_bars["volume"].mean() == 0: continue
            gap_pct   = (today_bar["open"] - prev_bar["close"]) / prev_bar["close"] * 100
            vol_ratio = today_bar["volume"] / hist_bars["volume"].mean()
            if abs(gap_pct) >= GAP_THRESHOLD and vol_ratio >= VOL_RATIO_MIN:
                candidates.append((sym, abs(gap_pct) * vol_ratio))

        candidates.sort(key=lambda x: x[1], reverse=True)
        today_symbols = [s for s, _ in candidates[:SCAN_TOP_N]]
        if not today_symbols: continue

        for sym in today_symbols:
            if sym not in intraday_dfs: continue
            idf = intraday_dfs[sym]
            day_mask = pd.to_datetime(idf.index).date == date
            day_df   = idf[day_mask].copy()
            if len(day_df) < 10: continue
            try:
                day_df = add_indicators(day_df).dropna(subset=["ema9", "vwap"])
            except: continue

            position = None
            cooldown_until = -1
            for i in range(2, len(day_df)):
                row = day_df.iloc[i]; prev = day_df.iloc[i-1]; prev2 = day_df.iloc[i-2]
                close=row["close"]; open_=row["open"]; high=row["high"]; low=row["low"]; ema8=row["ema9"]

                if position:
                    if position.side == "long":
                        do_exit, exit_price, reason = check_long(close, open_, low, ema8, position.entry_price)
                    else:
                        do_exit, exit_price, reason = check_short(close, open_, high, ema8, position.entry_price)
                    if do_exit:
                        position.exit_time=row.name; position.exit_price=exit_price; position.reason=reason
                        equity += position.pnl
                        result.trades.append(position); result.equity_curve.append(equity)
                        position=None; cooldown_until=i+COOLDOWN_BARS
                    continue

                if i <= cooldown_until: continue
                if _is_sideways(day_df, i): continue
                side, confidence = _check_entry(row, prev, prev2, day_df=day_df.iloc[:i+1], use_vp=True)
                if side:
                    entry_price = row["open"]
                    qty = position_size(equity, entry_price, confidence)
                    if side == "long" and equity >= entry_price * qty:
                        position = Trade(symbol=sym, side="long", entry_time=row.name,
                                        entry_price=entry_price, qty=qty, confidence=confidence)
                    elif side == "short" and sym in shortable:
                        position = Trade(symbol=sym, side="short", entry_time=row.name,
                                        entry_price=entry_price, qty=qty, confidence=confidence)

            if position:
                last=day_df.iloc[-1]; position.exit_time=last.name; position.exit_price=last["close"]
                position.reason="장마감청산"; equity+=position.pnl
                result.trades.append(position); result.equity_curve.append(equity)

    result.equity_curve.append(equity)
    return result

print("데이터 수집 중 (1회만 수집)...")
# 고가/저가 기준
print("\n[고가/저가 기준 하드손절] 시뮬레이션 중...")
r1 = run_with_stop_mode('high_low')

print("\n[종가 기준 하드손절] 시뮬레이션 중...")
r2 = run_with_stop_mode('close')

def summary(r, label):
    trades = r.trades
    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    wr     = len(wins)/len(trades)*100
    avg_win  = np.mean([t.pnl for t in wins])   if wins   else 0
    avg_loss = abs(np.mean([t.pnl for t in losses])) if losses else 0
    pf = sum(t.pnl for t in wins)/abs(sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses)!=0 else 0
    hard_stops = [t for t in trades if '하드손절' in t.reason]
    streak_l=max_l=0
    for t in trades:
        if t.pnl<=0: streak_l+=1; max_l=max(max_l,streak_l)
        else: streak_l=0
    return dict(label=label, n=len(trades), wr=wr, pf=pf,
                total=r.total_return_pct, mdd=r.mdd, sharpe=r.sharpe,
                payoff=avg_win/avg_loss if avg_loss>0 else 0,
                hard_stops=len(hard_stops), mcl=max_l)

s1 = summary(r1, '고가/저가 기준')
s2 = summary(r2, '종가 기준')

print()
print('='*58)
print('  하드손절 방식 비교 (2026 YTD, 82거래일)')
print('='*58)
metrics = [
    ('총 거래 수',    f'{s1["n"]}건',              f'{s2["n"]}건'),
    ('총 수익률',     f'{s1["total"]:+.2f}%',      f'{s2["total"]:+.2f}%'),
    ('MDD',          f'{s1["mdd"]:.2f}%',          f'{s2["mdd"]:.2f}%'),
    ('샤프',         f'{s1["sharpe"]:.2f}',        f'{s2["sharpe"]:.2f}'),
    ('승률',         f'{s1["wr"]:.1f}%',           f'{s2["wr"]:.1f}%'),
    ('손익비',       f'{s1["payoff"]:.2f}',        f'{s2["payoff"]:.2f}'),
    ('프로핏팩터',   f'{s1["pf"]:.2f}',            f'{s2["pf"]:.2f}'),
    ('하드손절 횟수', f'{s1["hard_stops"]}건',      f'{s2["hard_stops"]}건'),
    ('최대연속손실', f'{s1["mcl"]}회',              f'{s2["mcl"]}회'),
]
print(f'  {"지표":14s}  {"고가/저가 기준":>14}  {"종가 기준":>14}')
print(f'  {"-"*48}')
for label, v1, v2 in metrics:
    print(f'  {label:14s}  {v1:>14}  {v2:>14}')
