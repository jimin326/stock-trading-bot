"""
진입 로직 v1 vs v2 백테스트 비교
  v1 (구버전): N-1 눌림목 + N 양봉 → N+1 진입
  v2 (신버전): N-1 눌림목 + N 양봉확인 → N+1 신호 → N+2 진입

실행: python backtest_compare.py [--days 60]
"""

import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

import src.config as config
from src.indicators import add_indicators
from src.backtest import Trade, BacktestResult, _is_sideways, _check_entry, _check_entry_v2
from src.risk import check_exit_long, check_exit_short, position_size


def load_data(days: int):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from src.broker import get_shortable_set

    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    universe = config.BACKTEST_UNIVERSE
    end = datetime.now()

    print(f"[1/3] 일봉 데이터 수집 중...")
    daily_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=universe,
        timeframe=TimeFrame.Day,
        start=end - timedelta(days=days + 35),
        feed=DataFeed.IEX,
    )).data

    print(f"[2/3] 5분봉 데이터 수집 중 (약 30초)...")
    intra_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=universe,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=end - timedelta(days=days),
        feed=DataFeed.IEX,
    )).data

    daily_dfs = {}
    for sym, bars in daily_raw.items():
        df = pd.DataFrame([{
            "date": b.timestamp.date(),
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        } for b in bars]).set_index("date")
        daily_dfs[sym] = df

    intraday_dfs = {}
    for sym, bars in intra_raw.items():
        df = pd.DataFrame([{
            "timestamp": b.timestamp,
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        } for b in bars]).set_index("timestamp")
        intraday_dfs[sym] = df

    all_dates = sorted(set(
        d for sym_df in daily_dfs.values()
        for d in sym_df.index
        if d >= (end - timedelta(days=days)).date()
    ))

    print(f"[3/3] 공매도 가능 종목 조회 중...")
    shortable = get_shortable_set(universe)
    print(f"      {len(all_dates)}거래일 로드 완료\n")
    return daily_dfs, intraday_dfs, shortable, all_dates


def simulate(daily_dfs, intraday_dfs, shortable, all_dates,
             use_v2: bool = False, initial_equity: float = 10_000.0):
    result = BacktestResult(symbol="V2" if use_v2 else "V1", initial_equity=initial_equity)
    equity = initial_equity

    for d in all_dates:
        candidates = []
        for sym, ddf in daily_dfs.items():
            date_idx = ddf.index.tolist()
            if d not in date_idx:
                continue
            pos = date_idx.index(d)
            if pos < 21:
                continue
            today_bar = ddf.loc[d]
            prev_bar  = ddf.iloc[pos - 1]
            hist_bars = ddf.iloc[pos - 21: pos - 1]
            if prev_bar["close"] == 0 or hist_bars["volume"].mean() == 0:
                continue
            gap_pct   = (today_bar["open"] - prev_bar["close"]) / prev_bar["close"] * 100
            vol_ratio = today_bar["volume"] / hist_bars["volume"].mean()
            if abs(gap_pct) >= config.GAP_THRESHOLD and vol_ratio >= config.VOL_RATIO_MIN:
                candidates.append((sym, abs(gap_pct) * vol_ratio))

        candidates.sort(key=lambda x: x[1], reverse=True)
        today_symbols = [s for s, _ in candidates[:config.SCAN_TOP_N]]

        for sym in today_symbols:
            if sym not in intraday_dfs:
                continue
            idf = intraday_dfs[sym]
            day_mask = pd.to_datetime(idf.index).date == d
            day_df   = idf[day_mask].copy()
            if len(day_df) < 10:
                continue
            try:
                day_df = add_indicators(day_df).dropna(subset=["ema9", "vwap"])
            except Exception:
                continue

            position = None
            cooldown_until = -1
            start_i = 2 if use_v2 else 1

            for i in range(start_i, len(day_df)):
                row   = day_df.iloc[i]
                prev  = day_df.iloc[i - 1]
                close, open_ = row["close"], row["open"]
                high,  low   = row["high"],  row["low"]
                ema8         = row["ema9"]

                if position:
                    if position.side == "long":
                        do_exit, exit_price, reason = check_exit_long(
                            close, open_, low, ema8, position.entry_price, strict=True)
                    else:
                        do_exit, exit_price, reason = check_exit_short(
                            close, open_, high, ema8, position.entry_price, strict=True)
                    if do_exit:
                        position.exit_time  = row.name
                        position.exit_price = exit_price
                        position.reason     = reason
                        equity += position.pnl
                        result.trades.append(position)
                        result.equity_curve.append(equity)
                        position = None
                        cooldown_until = i + config.COOLDOWN_BARS
                    continue

                if i <= cooldown_until:
                    continue
                if _is_sideways(day_df, i):
                    continue

                if use_v2:
                    prev2 = day_df.iloc[i - 2]
                    side, conf = _check_entry_v2(row, prev, prev2,
                                                 day_df=day_df.iloc[:i+1], use_vp=True)
                else:
                    side, conf = _check_entry(row, prev,
                                              day_df=day_df.iloc[:i+1], use_vp=True)

                if side and i + 1 < len(day_df):
                    next_row    = day_df.iloc[i + 1]
                    entry_price = next_row["open"]
                    qty = position_size(equity, entry_price, conf)
                    if side == "long" and equity >= entry_price * qty:
                        position = Trade(symbol=sym, side="long",
                                         entry_time=next_row.name, entry_price=entry_price,
                                         qty=qty, confidence=conf)
                    elif side == "short" and sym in shortable:
                        position = Trade(symbol=sym, side="short",
                                         entry_time=next_row.name, entry_price=entry_price,
                                         qty=qty, confidence=conf)

            if position:
                last = day_df.iloc[-1]
                position.exit_time  = last.name
                position.exit_price = last["close"]
                position.reason     = "장마감청산"
                equity += position.pnl
                result.trades.append(position)
                result.equity_curve.append(equity)

    result.equity_curve.append(equity)
    return result


def print_table(rows: list[dict]):
    W = 90
    print("\n" + "=" * W)
    print(f"  {'버전':30} │ {'거래':>4} {'승':>4} {'패':>4} {'승률':>6} {'수익률':>8} {'MDD':>7} {'샤프':>6}")
    print("  " + "─" * 30 + "─┼─" + "─" * 44)
    for r in rows:
        n, w, l = r["trades"], r["wins"], r["losses"]
        print(
            f"  {r['label']:30} │ {n:4d} {w:4d} {l:4d} "
            f"{r['win_rate']:5.1f}% {r['total_return']:+7.2f}% "
            f"{r['mdd']:+6.2f}% {r['sharpe']:6.2f}"
        )
    print("=" * W)

    print(f"\n  {'버전':30} │ {'확신도1':^20} {'확신도2':^20} {'확신도3':^20}")
    print(f"  {'':30} │ {'거래 승 패 승률':^20} {'거래 승 패 승률':^20} {'거래 승 패 승률':^20}")
    print("  " + "─" * 30 + "─┼─" + "─" * 63)
    for r in rows:
        parts = []
        for conf in [1, 2, 3, 4]:
            t = r["conf"][conf]
            if t["n"] == 0:
                parts.append(f"{'없음':^20}")
            else:
                parts.append(f"{t['n']:3d} {t['w']:3d} {t['l']:3d} {t['wr']:5.1f}%")
        print(f"  {r['label']:30} │ {parts[0]:20} {parts[1]:20} {parts[2]:20}")
    print("=" * W)


def main(days: int = 60):
    daily_dfs, intraday_dfs, shortable, all_dates = load_data(days)

    rows = []
    for label, use_v2 in [
        ("v1 (구버전: N-1눌림+N양봉→N+1진입)", False),
        ("v2 (신버전: N-1눌림+N양봉확인→N+2진입)", True),
    ]:
        tag = "v2" if use_v2 else "v1"
        print(f"[{tag}] {label} 시뮬레이션 중...")
        result = simulate(daily_dfs, intraday_dfs, shortable, all_dates, use_v2=use_v2)

        trades = result.trades
        n      = len(trades)
        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        conf_stats = {}
        for conf in [1, 2, 3, 4]:
            ct = [t for t in trades if t.confidence == conf]
            cw = [t for t in ct if t.pnl > 0]
            cl = [t for t in ct if t.pnl <= 0]
            conf_stats[conf] = {
                "n": len(ct), "w": len(cw), "l": len(cl),
                "wr": len(cw) / len(ct) * 100 if ct else 0,
            }

        rows.append({
            "label":        label,
            "trades":       n,
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     result.win_rate,
            "total_return": result.total_return_pct,
            "mdd":          result.mdd,
            "sharpe":       result.sharpe,
            "conf":         conf_stats,
        })

    print_table(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    main(days=args.days)
