"""EMA 눌림목만 vs 기존 확신도2+ 비교"""
import numpy as np
import pandas as pd
import src.config as config
from src.backtest import Trade, BacktestResult, _is_sideways, _check_entry
from src.indicators import add_indicators
from src.risk import check_exit_long, check_exit_short, position_size
from src.config import EMA_TOUCH_PCT, PULLBACK_LOWER_PCT
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from src.broker import get_shortable_set
from datetime import datetime, timedelta

config.HARD_STOP_PCT = 0.01


def entry_ema_only(row, prev, day_df=None):
    close, open_ = row["close"], row["open"]
    ema8, vwap   = row["ema9"], row["vwap"]
    if close > vwap:
        ema_pb = (prev["low"] <= ema8 * (1 + EMA_TOUCH_PCT)
                  and prev["low"] >= ema8 * (1 - PULLBACK_LOWER_PCT))
        bounce = (close > open_) and close > ema8
        if bounce and ema_pb:
            return "long", 1 + int(close > vwap * 1.005)
    elif close < vwap:
        ema_pb = (prev["high"] >= ema8 * (1 - EMA_TOUCH_PCT)
                  and prev["high"] <= ema8 * (1 + PULLBACK_LOWER_PCT))
        bounce = (close < open_) and close < ema8
        if bounce and ema_pb:
            return "short", 1 + int(close < vwap * 0.995)
    return None, 0


def entry_conf2(row, prev, day_df=None):
    side, conf = _check_entry(row, prev, day_df=day_df)
    return (side, conf) if conf >= 2 else (None, 0)


def simulate(daily_dfs, intraday_dfs, shortable, all_dates, entry_fn, initial_equity=10000.0):
    result = BacktestResult(symbol="CMP", initial_equity=initial_equity)
    equity = initial_equity
    for d in all_dates:
        candidates = []
        for sym, ddf in daily_dfs.items():
            date_idx = ddf.index.tolist()
            if d not in date_idx: continue
            pos = date_idx.index(d)
            if pos < 21: continue
            today, prev_bar = ddf.loc[d], ddf.iloc[pos-1]
            hist = ddf.iloc[pos-21:pos-1]
            if prev_bar["close"] == 0 or hist["volume"].mean() == 0: continue
            gap = (today["open"] - prev_bar["close"]) / prev_bar["close"] * 100
            vol = today["volume"] / hist["volume"].mean()
            if abs(gap) >= config.GAP_THRESHOLD and vol >= config.VOL_RATIO_MIN:
                candidates.append((sym, abs(gap)*vol))
        candidates.sort(key=lambda x: -x[1])
        for sym, _ in candidates[:config.SCAN_TOP_N]:
            if sym not in intraday_dfs: continue
            idf = intraday_dfs[sym]
            day_df = idf[pd.to_datetime(idf.index).date == d].copy()
            if len(day_df) < 10: continue
            try:
                day_df = add_indicators(day_df).dropna(subset=["ema9", "vwap"])
            except:
                continue
            position, cooldown_until = None, -1
            for i in range(1, len(day_df)):
                row, prev = day_df.iloc[i], day_df.iloc[i-1]
                close, open_, high, low, ema8 = row["close"], row["open"], row["high"], row["low"], row["ema9"]
                if position:
                    if position.side == "long":
                        do_exit, ep, reason = check_exit_long(close, open_, low, ema8, position.entry_price, strict=False)
                    else:
                        do_exit, ep, reason = check_exit_short(close, open_, high, ema8, position.entry_price, strict=False)
                    if do_exit:
                        position.exit_time, position.exit_price, position.reason = row.name, ep, reason
                        equity += position.pnl
                        result.trades.append(position)
                        result.equity_curve.append(equity)
                        position, cooldown_until = None, i + 4
                    continue
                if i <= cooldown_until or _is_sideways(day_df, i): continue
                side, conf = entry_fn(row, prev, day_df.iloc[:i+1])
                if side and i+1 < len(day_df):
                    next_row = day_df.iloc[i+1]
                    ep = next_row["open"]
                    qty = position_size(equity, ep, conf)
                    if side == "long" and equity >= ep * qty:
                        position = Trade(symbol=sym, side="long", entry_time=next_row.name, entry_price=ep, qty=qty, confidence=conf)
                    elif side == "short" and sym in shortable:
                        position = Trade(symbol=sym, side="short", entry_time=next_row.name, entry_price=ep, qty=qty, confidence=conf)
            if position:
                last = day_df.iloc[-1]
                position.exit_time, position.exit_price, position.reason = last.name, last["close"], "장마감청산"
                equity += position.pnl
                result.trades.append(position)
                result.equity_curve.append(equity)
    result.equity_curve.append(equity)
    return result


def stats(trades, label):
    if not trades:
        print(f"  {label:20s} │ 거래 없음"); return
    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    pf     = sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses)) if losses else float("inf")
    payoff = (np.mean([t.pnl for t in wins]) / abs(np.mean([t.pnl for t in losses]))) if wins and losses else float("inf")
    equity = [10000]
    for t in trades: equity.append(equity[-1] + t.pnl)
    eq  = np.array(equity)
    mdd = float(((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq) * 100).min())
    ret = (equity[-1] - 10000) / 10000 * 100
    wr  = len(wins) / len(trades) * 100
    rets = [t.pnl_pct for t in trades]
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252) if np.std(rets) > 0 else 0
    rf = ret / abs(mdd) if mdd != 0 else float("inf")
    print(f"  {label:20s} │ {len(trades):5d} {wr:5.1f}% {ret:+7.2f}% {mdd:+7.2f}% {sharpe:6.2f} {pf:6.2f} {payoff:6.2f} {rf:8.2f}")


def main():
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    end = datetime.now()
    print("[데이터 로딩 중...]")
    daily_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=config.BACKTEST_UNIVERSE, timeframe=TimeFrame.Day,
        start=end-timedelta(days=125), feed=DataFeed.IEX)).data
    intra_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=config.BACKTEST_UNIVERSE,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=end-timedelta(days=90), feed=DataFeed.IEX)).data

    daily_dfs = {s: pd.DataFrame([{"date": b.timestamp.date(), "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in bars]).set_index("date") for s, bars in daily_raw.items()}
    intra_dfs  = {s: pd.DataFrame([{"timestamp": b.timestamp, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in bars]).set_index("timestamp") for s, bars in intra_raw.items()}
    all_dates  = sorted(set(d for df in daily_dfs.values() for d in df.index if d >= (end-timedelta(days=90)).date()))
    shortable  = get_shortable_set(config.BACKTEST_UNIVERSE)
    print(f"  {len(all_dates)}거래일 로드 완료\n")

    print("[EMA 눌림목만 시뮬레이션...]")
    r1 = simulate(daily_dfs, intra_dfs, shortable, all_dates, entry_ema_only)

    print("[기존 확신도2+ 시뮬레이션...]")
    r2 = simulate(daily_dfs, intra_dfs, shortable, all_dates, entry_conf2)

    print()
    print("=" * 102)
    print(f"  {'':20s} │ {'거래':>5} {'승률':>6} {'수익률':>8} {'MDD':>8} {'샤프':>6} {'PF':>6} {'P/L비':>6} {'회복계수':>8}")
    print("  " + "─"*20 + "─┼─" + "─"*74)
    stats(r1.trades, "EMA 눌림목만")
    stats(r2.trades, "기존 확신도2+")
    print("=" * 102)


if __name__ == "__main__":
    main()
