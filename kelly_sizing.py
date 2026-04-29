"""
켈리 공식으로 확신도별 최적 포지션 비중 계산 후 현재 설정과 비교
  하드 손절: 1% 고정
  비교: 현재(7-10-13%) vs 풀켈리 vs 하프켈리
"""

import argparse
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
    universe = config.BACKTEST_UNIVERSE
    end = datetime.now()

    print("[1/3] 일봉 데이터 수집 중...")
    daily_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=universe,
        timeframe=TimeFrame.Day,
        start=end - timedelta(days=days + 35),
        feed=DataFeed.IEX,
    )).data

    print("[2/3] 5분봉 데이터 수집 중 (약 30초)...")
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

    print("[3/3] 공매도 가능 종목 조회 중...")
    shortable = get_shortable_set(universe)
    print(f"      {len(all_dates)}거래일 로드 완료\n")
    return daily_dfs, intraday_dfs, shortable, all_dates


def simulate(daily_dfs, intraday_dfs, shortable, all_dates,
             hard_stop_pct, tiers, initial_equity=10_000.0):
    config.HARD_STOP_PCT       = hard_stop_pct
    config.POSITION_SIZE_TIERS = tiers

    result = BacktestResult(symbol="K", initial_equity=initial_equity)
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


def calc_kelly(trades: list) -> dict:
    """확신도별 켈리 비중 계산"""
    result = {}
    for conf in [1, 2, 3]:
        ct = [t for t in trades if t.confidence == conf]
        if len(ct) < 5:
            result[conf] = {"kelly": 0, "half_kelly": 0, "p": 0, "rr": 0, "n": len(ct)}
            continue

        wins   = [t for t in ct if t.pnl_pct > 0]
        losses = [t for t in ct if t.pnl_pct <= 0]

        p = len(wins) / len(ct)
        q = 1 - p

        avg_win  = np.mean([t.pnl_pct for t in wins])   if wins   else 0
        avg_loss = abs(np.mean([t.pnl_pct for t in losses])) if losses else 0

        if avg_loss == 0:
            result[conf] = {"kelly": 0, "half_kelly": 0, "p": p, "rr": 0, "n": len(ct)}
            continue

        rr    = avg_win / avg_loss          # 손익비
        kelly = (p * rr - q) / rr          # 켈리 공식: f* = (p*R - q) / R
        kelly = max(0, min(kelly, 0.25))   # 0~25% 클램프 (안전)

        result[conf] = {
            "n":          len(ct),
            "p":          p,
            "avg_win":    avg_win,
            "avg_loss":   avg_loss,
            "rr":         rr,
            "kelly":      kelly,
            "half_kelly": kelly / 2,
        }
    return result


def main(days: int = 60):
    orig_stop  = config.HARD_STOP_PCT
    orig_tiers = config.POSITION_SIZE_TIERS[:]

    daily_dfs, intraday_dfs, shortable, all_dates = load_data(days)

    # ── 1단계: 손절 1% + 현재 비중으로 데이터 수집 ──────────────
    print("[Step 1] 손절 1% / 비중 7-10-13% 시뮬레이션 (켈리 계산용)...")
    base = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                    hard_stop_pct=0.01, tiers=[0.07, 0.10, 0.13])

    # ── 2단계: 켈리 계산 ──────────────────────────────────────
    kelly_data = calc_kelly(base.trades)

    print("\n" + "=" * 65)
    print("  확신도별 켈리 계산 결과")
    print("=" * 65)
    print(f"  {'확신도':>4} │ {'거래':>4} {'승률':>6} {'평균수익':>8} {'평균손실':>8} {'손익비':>6} {'풀켈리':>8} {'하프켈리':>8}")
    print("  " + "─" * 4 + "─┼─" + "─" * 58)

    kelly_tiers      = []
    half_kelly_tiers = []
    for conf in [1, 2, 3]:
        d = kelly_data[conf]
        kelly_tiers.append(round(d["kelly"], 4))
        half_kelly_tiers.append(round(d["half_kelly"], 4))
        print(f"  {conf:4d} │ {d['n']:4d} {d['p']*100:5.1f}% "
              f"{d['avg_win']:+7.2f}% {d['avg_loss']:+7.2f}% "
              f"{d['rr']:6.2f}  "
              f"{d['kelly']*100:6.1f}%   {d['half_kelly']*100:6.1f}%")

    print(f"\n  풀켈리  비중: {[f'{v*100:.1f}%' for v in kelly_tiers]}")
    print(f"  하프켈리 비중: {[f'{v*100:.1f}%' for v in half_kelly_tiers]}")
    print(f"  현재    비중: ['7.0%', '10.0%', '13.0%']")

    # ── 3단계: 세 가지 비중 비교 ──────────────────────────────
    print("\n[Step 2] 현재 비중 시뮬레이션...")
    r_current = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                         hard_stop_pct=0.01, tiers=[0.07, 0.10, 0.13])

    print("[Step 3] 풀켈리 비중 시뮬레이션...")
    r_kelly = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                       hard_stop_pct=0.01, tiers=kelly_tiers)

    print("[Step 4] 하프켈리 비중 시뮬레이션...")
    r_half = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                      hard_stop_pct=0.01, tiers=half_kelly_tiers)

    config.HARD_STOP_PCT       = orig_stop
    config.POSITION_SIZE_TIERS = orig_tiers

    # ── 결과 출력 ──────────────────────────────────────────────
    scenarios = [
        ("현재  (7-10-13%)",                         r_current,  [0.07, 0.10, 0.13]),
        (f"풀켈리 ({[f'{v*100:.0f}%' for v in kelly_tiers]})",      r_kelly,    kelly_tiers),
        (f"하프켈리({[f'{v*100:.0f}%' for v in half_kelly_tiers]})", r_half,     half_kelly_tiers),
    ]

    print("\n" + "=" * 75)
    print(f"  비교 결과 (손절 1% 고정, 60일, $10,000 기준)")
    print("=" * 75)
    print(f"  {'':30} │ {'거래':>4} {'승':>4} {'패':>4} {'승률':>6} {'수익률':>7} {'MDD':>7} {'샤프':>6}")
    print("  " + "─" * 30 + "─┼─" + "─" * 40)
    for label, r, _ in scenarios:
        n   = len(r.trades)
        w   = sum(1 for t in r.trades if t.pnl > 0)
        l   = n - w
        wr  = r.win_rate
        tr  = r.total_return_pct
        mdd = r.mdd
        sh  = r.sharpe
        print(f"  {label:30} │ {n:4d} {w:4d} {l:4d} {wr:5.1f}% {tr:+6.2f}% {mdd:+6.2f}% {sh:6.2f}")
    print("=" * 75)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    main(days=args.days)
