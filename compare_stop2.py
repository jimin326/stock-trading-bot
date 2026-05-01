from src.backtest import run_scanner_backtest, BacktestResult, _check_entry, _is_sideways, Trade
from src.indicators import add_indicators
from src.config import (SCAN_UNIVERSE, GAP_THRESHOLD, VOL_RATIO_MIN, SCAN_TOP_N,
                        COOLDOWN_BARS, HARD_STOP_PCT)
from src.risk import position_size, check_exit_long, check_exit_short
import numpy as np

def check_exit_long_no_stop(close, open_, low, ema9, entry, strict=False):
    if max(open_, close) < ema9:
        return True, close, "EMA8하향이탈"
    return False, close, ""

def check_exit_short_no_stop(close, open_, high, ema9, entry, strict=False):
    if min(open_, close) > ema9:
        return True, close, "EMA8상향이탈"
    return False, close, ""

def run_custom(exit_long_fn, exit_short_fn, label):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from datetime import datetime, timedelta
    import pandas as pd
    import src.config as _cfg

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
                row=day_df.iloc[i]; prev=day_df.iloc[i-1]; prev2=day_df.iloc[i-2]
                close=row["close"]; open_=row["open"]; high=row["high"]; low=row["low"]; ema8=row["ema9"]

                if position:
                    if position.side == "long":
                        do_exit, exit_price, reason = exit_long_fn(close, open_, low, ema8, position.entry_price)
                    else:
                        do_exit, exit_price, reason = exit_short_fn(close, open_, high, ema8, position.entry_price)
                    if do_exit:
                        position.exit_time=row.name; position.exit_price=exit_price; position.reason=reason
                        equity+=position.pnl
                        result.trades.append(position); result.equity_curve.append(equity)
                        position=None; cooldown_until=i+COOLDOWN_BARS
                    continue

                if i <= cooldown_until: continue
                if _is_sideways(day_df, i): continue
                side, confidence = _check_entry(row, prev, prev2, day_df=day_df.iloc[:i+1], use_vp=True)
                if side:
                    entry_price=row["open"]
                    qty=position_size(equity, entry_price, confidence)
                    if side=="long" and equity>=entry_price*qty:
                        position=Trade(symbol=sym, side="long", entry_time=row.name,
                                       entry_price=entry_price, qty=qty, confidence=confidence)
                    elif side=="short" and sym in shortable:
                        position=Trade(symbol=sym, side="short", entry_time=row.name,
                                       entry_price=entry_price, qty=qty, confidence=confidence)

            if position:
                last=day_df.iloc[-1]; position.exit_time=last.name; position.exit_price=last["close"]
                position.reason="장마감청산"; equity+=position.pnl
                result.trades.append(position); result.equity_curve.append(equity)

    result.equity_curve.append(equity)
    return result

def stats(r):
    trades=r.trades
    wins=[t for t in trades if t.pnl>0]; losses=[t for t in trades if t.pnl<=0]
    wr=len(wins)/len(trades)*100
    avg_win=np.mean([t.pnl for t in wins]) if wins else 0
    avg_loss=abs(np.mean([t.pnl for t in losses])) if losses else 0
    pf=sum(t.pnl for t in wins)/abs(sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses)!=0 else 0
    hard=[t for t in trades if '하드손절' in t.reason]
    streak_l=max_l=0
    for t in trades:
        if t.pnl<=0: streak_l+=1; max_l=max(max_l,streak_l)
        else: streak_l=0
    worst=min(t.pnl_pct for t in trades)
    return dict(n=len(trades),wr=wr,pf=pf,total=r.total_return_pct,
                mdd=r.mdd,sharpe=r.sharpe,payoff=avg_win/avg_loss if avg_loss>0 else 0,
                hard=len(hard),mcl=max_l,worst=worst)

print("데이터 수집 및 시뮬레이션 중...")
r1 = run_scanner_backtest(days=120, side_filter='both', strict_exit=False, cooldown_bars=2, use_vp=True)
print("하드손절 없는 버전 시뮬레이션 중...")
r2 = run_custom(check_exit_long_no_stop, check_exit_short_no_stop, "하드손절 없음")

s1 = stats(r1)
s2 = stats(r2)

print()
print('='*60)
print('  하드손절 유/무 비교 (2026 YTD, 82거래일)')
print('='*60)
rows = [
    ('총 거래 수',    f'{s1["n"]}건',           f'{s2["n"]}건'),
    ('총 수익률',     f'{s1["total"]:+.2f}%',   f'{s2["total"]:+.2f}%'),
    ('MDD',          f'{s1["mdd"]:.2f}%',       f'{s2["mdd"]:.2f}%'),
    ('샤프',         f'{s1["sharpe"]:.2f}',     f'{s2["sharpe"]:.2f}'),
    ('승률',         f'{s1["wr"]:.1f}%',        f'{s2["wr"]:.1f}%'),
    ('손익비',       f'{s1["payoff"]:.2f}',     f'{s2["payoff"]:.2f}'),
    ('프로핏팩터',   f'{s1["pf"]:.2f}',         f'{s2["pf"]:.2f}'),
    ('하드손절 횟수', f'{s1["hard"]}건',          f'{s2["hard"]}건'),
    ('최대연속손실', f'{s1["mcl"]}회',            f'{s2["mcl"]}회'),
    ('단일 최대손실', f'{s1["worst"]:+.2f}%',   f'{s2["worst"]:+.2f}%'),
]
print(f'  {"지표":14s}  {"하드손절 있음(-1%)":>16}  {"하드손절 없음":>14}')
print(f'  {"-"*50}')
for label, v1, v2 in rows:
    print(f'  {label:14s}  {v1:>16}  {v2:>14}')
