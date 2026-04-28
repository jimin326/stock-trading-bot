"""
6가지 조합 백테스트 비교
  손절: 1% / 1.5% / 2%
  포지션비중: [5,10,20]% vs [7,10,13]%

실행: python backtest_compare.py [--days 60]
"""

import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass

import src.config as config
from src.indicators import add_indicators
from src.backtest import Trade, BacktestResult, _is_sideways, _check_entry
from src.risk import check_exit_long, check_exit_short, position_size


COMBOS = [
    {"stop": 0.010, "tiers": [0.05, 0.10, 0.20], "label": "손절1.0% / 비중 5-10-20%"},
    {"stop": 0.015, "tiers": [0.05, 0.10, 0.20], "label": "손절1.5% / 비중 5-10-20%"},
    {"stop": 0.020, "tiers": [0.05, 0.10, 0.20], "label": "손절2.0% / 비중 5-10-20%"},
    {"stop": 0.010, "tiers": [0.07, 0.10, 0.13], "label": "손절1.0% / 비중 7-10-13%"},
    {"stop": 0.015, "tiers": [0.07, 0.10, 0.13], "label": "손절1.5% / 비중 7-10-13%"},
    {"stop": 0.020, "tiers": [0.07, 0.10, 0.13], "label": "손절2.0% / 비중 7-10-13% ← 현재"},
]


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
             hard_stop_pct, tiers, initial_equity=10_000.0):
    config.HARD_STOP_PCT       = hard_stop_pct
    config.POSITION_SIZE_TIERS = tiers

    result = BacktestResult(symbol="CMP", initial_equity=initial_equity)
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
                side, conf = _check_entry(row, prev, day_df=day_df.iloc[:i+1], use_vp=True)
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
    W = 100
    print("\n" + "=" * W)
    print(f"  {'':42} │ {'거래':>4} {'승':>4} {'패':>4} {'승률':>6} {'수익률':>7} {'MDD':>7} {'샤프':>6}")
    print("  " + "─" * 42 + "─┼─" + "─" * 43)
    for r in rows:
        marker = " ★" if r["label"].endswith("현재") else "  " if "현재" not in r["label"] else "  "
        # marker already in label as ← 현재
        label = r["label"]
        n, w, l = r["trades"], r["wins"], r["losses"]
        wr  = r["win_rate"]
        tr  = r["total_return"]
        mdd = r["mdd"]
        sh  = r["sharpe"]
        tr_color  = "+" if tr >= 0 else ""
        print(f"  {label:42} │ {n:4d} {w:4d} {l:4d} {wr:5.1f}% {tr:+6.2f}% {mdd:+6.2f}% {sh:6.2f}")

    print("=" * W)

    # 확신도별 상세
    print(f"\n  {'':42} │ 확신도1          확신도2          확신도3")
    print(f"  {'':42} │ {'거래 승 패 승률':>18} {'거래 승 패 승률':>18} {'거래 승 패 승률':>18}")
    print("  " + "─" * 42 + "─┼─" + "─" * 57)
    for r in rows:
        label = r["label"]
        parts = []
        for conf in [1, 2, 3]:
            t = r["conf"][conf]
            if t["n"] == 0:
                parts.append(f"{'없음':>18}")
            else:
                parts.append(f"{t['n']:3d} {t['w']:3d} {t['l']:3d} {t['wr']:5.1f}%")
        print(f"  {label:42} │ {parts[0]:18} {parts[1]:18} {parts[2]:18}")
    print("=" * W)


def main(days: int = 60):
    orig_stop  = config.HARD_STOP_PCT
    orig_tiers = config.POSITION_SIZE_TIERS[:]

    daily_dfs, intraday_dfs, shortable, all_dates = load_data(days)

    rows = []
    for i, combo in enumerate(COMBOS, 1):
        print(f"[{i}/6] {combo['label']} 시뮬레이션 중...")
        result = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                          hard_stop_pct=combo["stop"], tiers=combo["tiers"])

        trades = result.trades
        n      = len(trades)
        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        conf_stats = {}
        for conf in [1, 2, 3]:
            ct = [t for t in trades if t.confidence == conf]
            cw = [t for t in ct if t.pnl > 0]
            cl = [t for t in ct if t.pnl <= 0]
            conf_stats[conf] = {
                "n": len(ct),
                "w": len(cw),
                "l": len(cl),
                "wr": len(cw) / len(ct) * 100 if ct else 0,
            }

        rows.append({
            "label":        combo["label"],
            "trades":       n,
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     result.win_rate,
            "total_return": result.total_return_pct,
            "mdd":          result.mdd,
            "sharpe":       result.sharpe,
            "conf":         conf_stats,
        })

    config.HARD_STOP_PCT       = orig_stop
    config.POSITION_SIZE_TIERS = orig_tiers

    print_table(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    main(days=args.days)
