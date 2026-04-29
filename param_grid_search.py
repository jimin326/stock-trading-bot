"""
파라미터 그리드 서치 (데이터 1회 로딩 후 96가지 조합 비교)
  쿨타임  : 0/1/2/3/4/5 bars (0/5/10/15/20/25분)
  하드손절 : 0/1/2/3%
  방향     : long_only / short_only
  청산방식 : strict=True / False

실행: python param_grid_search.py [--days 90]
"""
import argparse
import itertools
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

import src.config as config
from src.indicators import add_indicators
from src.backtest import Trade, BacktestResult, _is_sideways, _check_entry
from src.risk import check_exit_long, check_exit_short, position_size


def load_data(days: int):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from src.broker import get_shortable_set

    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    end = datetime.now()

    print(f"[1/3] 일봉 데이터 수집 중 ({len(config.BACKTEST_UNIVERSE)}종목)...")
    daily_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=config.BACKTEST_UNIVERSE,
        timeframe=TimeFrame.Day,
        start=end - timedelta(days=days + 35),
        feed=DataFeed.IEX,
    )).data

    print(f"[2/3] 5분봉 데이터 수집 중...")
    intra_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=config.BACKTEST_UNIVERSE,
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
    shortable = get_shortable_set(config.BACKTEST_UNIVERSE)
    print(f"      {len(all_dates)}거래일 로드 완료\n")
    return daily_dfs, intraday_dfs, shortable, all_dates


def simulate(daily_dfs, intraday_dfs, shortable, all_dates,
             hard_stop_pct, cooldown_bars, side_filter, strict_exit,
             initial_equity=10_000.0):
    config.HARD_STOP_PCT = hard_stop_pct

    result = BacktestResult(symbol="GRID", initial_equity=initial_equity)
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
            for i in range(1, len(day_df)):
                row   = day_df.iloc[i]
                prev  = day_df.iloc[i - 1]
                close, open_ = row["close"], row["open"]
                high,  low   = row["high"],  row["low"]
                ema8         = row["ema9"]

                if position:
                    if position.side == "long":
                        do_exit, exit_price, reason = check_exit_long(
                            close, open_, low, ema8, position.entry_price, strict=strict_exit)
                    else:
                        do_exit, exit_price, reason = check_exit_short(
                            close, open_, high, ema8, position.entry_price, strict=strict_exit)
                    if do_exit:
                        position.exit_time  = row.name
                        position.exit_price = exit_price
                        position.reason     = reason
                        equity += position.pnl
                        result.trades.append(position)
                        result.equity_curve.append(equity)
                        position = None
                        cooldown_until = i + cooldown_bars
                    continue

                if i <= cooldown_until:
                    continue
                if _is_sideways(day_df, i):
                    continue
                side, conf = _check_entry(row, prev, day_df=day_df.iloc[:i+1], use_vp=True)
                if not side or i + 1 >= len(day_df):
                    continue
                if side_filter == "long_only" and side != "long":
                    continue
                if side_filter == "short_only" and side != "short":
                    continue

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


def calc_extra(trades):
    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    total_win  = sum(t.pnl for t in wins)
    total_loss = abs(sum(t.pnl for t in losses))
    pf = total_win / total_loss if total_loss > 0 else float("inf")

    avg_win  = np.mean([t.pnl for t in wins])  if wins   else 0
    avg_loss = abs(np.mean([t.pnl for t in losses])) if losses else 0
    payoff = avg_win / avg_loss if avg_loss > 0 else float("inf")

    return pf, payoff


def print_table(rows):
    rows_sorted = sorted(rows, key=lambda r: r["total_return"], reverse=True)

    W = 130
    print("\n" + "=" * W)
    print(f"  {'쿨타임':>5} {'손절':>5} {'방향':>6} {'청산':>5} │"
          f" {'거래':>5} {'승률':>6} {'수익률':>8} {'MDD':>8} {'샤프':>6}"
          f" {'PF':>6} {'P/L비':>6} {'회복계수':>8}")
    print("  " + "─"*26 + "─┼─" + "─"*90)

    for r in rows_sorted:
        stop_str   = f"-{r['stop']*100:.0f}%" if r['stop'] > 0 else "없음"
        cool_str   = f"{r['cooldown']*5}분"
        side_str   = "롱만" if r['side'] == "long_only" else ("숏만" if r['side'] == "short_only" else "롱+숏")
        strict_str = "종가" if r['strict'] else "몸통"
        marker     = " ★" if r == rows_sorted[0] else "  "

        pf_str     = f"{r['pf']:.2f}"     if r['pf']     != float("inf") else "  ∞"
        payoff_str = f"{r['payoff']:.2f}" if r['payoff'] != float("inf") else "  ∞"
        rf         = r['total_return'] / abs(r['mdd']) if r['mdd'] != 0 else float("inf")
        rf_str     = f"{rf:.2f}" if rf != float("inf") else "  ∞"

        print(
            f"  {cool_str:>5} {stop_str:>5} {side_str:>6} {strict_str:>5} │"
            f" {r['trades']:5d} {r['win_rate']:5.1f}%"
            f" {r['total_return']:+7.2f}%"
            f" {r['mdd']:+7.2f}%"
            f" {r['sharpe']:6.2f}"
            f" {pf_str:>6}"
            f" {payoff_str:>6}"
            f" {rf_str:>8}"
            f"{marker}"
        )
    print("=" * W)
    print(f"  총 {len(rows)}가지 조합 | ★ = 수익률 1위")
    print(f"  PF: 프로핏팩터(1.8+우수) | P/L비: 평균익절/평균손절 | 회복계수: 수익률/|MDD|(3+우수)\n")


def main(days: int = 90):
    orig_stop = config.HARD_STOP_PCT

    daily_dfs, intraday_dfs, shortable, all_dates = load_data(days)

    cooldowns   = [0, 1, 2, 3, 4, 5]       # bars (×5분)
    stops       = [0.00, 0.01, 0.02, 0.03]
    sides       = ["long_only", "short_only", "both"]
    strict_opts = [True, False]

    combos = list(itertools.product(cooldowns, stops, sides, strict_opts))
    print(f"총 {len(combos)}가지 조합 시뮬레이션 시작...\n")

    rows = []
    for idx, (cool, stop, side, strict) in enumerate(combos, 1):
        print(f"[{idx:3d}/{len(combos)}] 쿨{cool*5}분 손절{stop*100:.0f}% {side} strict={strict}", end="\r")
        result = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                          hard_stop_pct=stop, cooldown_bars=cool,
                          side_filter=side, strict_exit=strict)
        trades = result.trades
        pf, payoff = calc_extra(trades)
        rows.append({
            "cooldown":     cool,
            "stop":         stop,
            "side":         side,
            "strict":       strict,
            "trades":       len(trades),
            "win_rate":     result.win_rate,
            "total_return": result.total_return_pct,
            "mdd":          result.mdd,
            "sharpe":       result.sharpe,
            "pf":           pf,
            "payoff":       payoff,
        })

    config.HARD_STOP_PCT = orig_stop
    print(f"\n완료!\n")
    print_table(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    main(days=args.days)
