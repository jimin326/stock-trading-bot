"""
파라미터 최적화: 데이터 1회 로드 후 56개 조합 시뮬레이션
  - COOLDOWN_BARS : 0 / 1 / 2 / 3 / 5 / 8 / 10
  - HARD_STOP_PCT : 0.01 / 0.015 / 0.02 / 0.03
  - STRICT_EXIT   : True / False

실행: python optimize_params.py [--days 60]
"""

import argparse
import itertools
from dataclasses import dataclass
from datetime import datetime, timedelta, date

import pandas as pd
import numpy as np

import src.config as config
from src.indicators import add_indicators, vp_is_clear
from src.backtest import Trade, BacktestResult, _is_sideways, _check_entry
from src.risk import check_exit_long, check_exit_short, position_size


# ── 파라미터 그리드 ─────────────────────────────────────────
COOLDOWN_GRID   = [0, 1, 2, 3, 5, 8, 10]
HARD_STOP_GRID  = [0.01, 0.015, 0.02, 0.03]
STRICT_EXIT_GRID = [True, False]


@dataclass
class OptimRow:
    cooldown: int
    hard_stop: float
    strict_exit: bool
    trades: int
    win_rate: float
    total_return: float
    mdd: float
    sharpe: float

    def score(self) -> float:
        if self.trades < 3:
            return -999
        return self.sharpe * 0.4 + self.total_return * 0.3 + (self.mdd * 0.3)

    def __str__(self):
        se = "엄격" if self.strict_exit else "완화"
        return (
            f"쿨다운={self.cooldown:2d}봉({self.cooldown*5:3d}분) "
            f"손절={self.hard_stop*100:.1f}% "
            f"청산={se}  │  "
            f"거래={self.trades:3d}건  승률={self.win_rate:5.1f}%  "
            f"수익={self.total_return:+7.2f}%  "
            f"MDD={self.mdd:+6.2f}%  "
            f"샤프={self.sharpe:5.2f}  "
            f"점수={self.score():+6.2f}"
        )


def load_data(days: int) -> tuple[dict, dict, set]:
    """일봉 + 5분봉 데이터를 1회만 다운로드하여 반환"""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from src.broker import get_shortable_set

    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    end   = datetime.now()
    start_intra = end - timedelta(days=days)
    start_daily = end - timedelta(days=days + 35)
    universe = config.BACKTEST_UNIVERSE

    print(f"[1/3] 일봉 데이터 수집 중 ({len(universe)}종목)...")
    daily_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=universe,
        timeframe=TimeFrame.Day,
        start=start_daily,
        feed=DataFeed.IEX,
    )).data

    print(f"[2/3] 5분봉 데이터 수집 중 (약 30초)...")
    intra_raw = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=universe,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start_intra,
        feed=DataFeed.IEX,
    )).data

    daily_dfs: dict[str, pd.DataFrame] = {}
    for sym, bars in daily_raw.items():
        df = pd.DataFrame([{
            "date": b.timestamp.date(),
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        } for b in bars]).set_index("date")
        daily_dfs[sym] = df

    intraday_dfs: dict[str, pd.DataFrame] = {}
    for sym, bars in intra_raw.items():
        df = pd.DataFrame([{
            "timestamp": b.timestamp,
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        } for b in bars]).set_index("timestamp")
        intraday_dfs[sym] = df

    print(f"[3/3] 공매도 가능 종목 조회 중...")
    shortable = get_shortable_set(universe)

    all_dates = sorted(set(
        d for sym_df in daily_dfs.values()
        for d in sym_df.index
        if d >= start_intra.date()
    ))
    print(f"      거래일 {len(all_dates)}일 로드 완료\n")
    return daily_dfs, intraday_dfs, shortable, all_dates


def simulate(
    daily_dfs: dict,
    intraday_dfs: dict,
    shortable: set,
    all_dates: list,
    cooldown_bars: int,
    hard_stop_pct: float,
    strict_exit: bool,
    initial_equity: float = 10_000.0,
) -> BacktestResult:
    config.HARD_STOP_PCT = hard_stop_pct

    result = BacktestResult(symbol="OPT", initial_equity=initial_equity)
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
                close = row["close"]
                open_ = row["open"]
                high  = row["high"]
                low   = row["low"]
                ema8  = row["ema9"]

                if position:
                    if position.side == "long":
                        do_exit, exit_price, reason = check_exit_long(close, open_, low, ema8, position.entry_price, strict=strict_exit)
                    else:
                        do_exit, exit_price, reason = check_exit_short(close, open_, high, ema8, position.entry_price, strict=strict_exit)
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
                side, confidence = _check_entry(row, prev, day_df=day_df.iloc[:i+1], use_vp=True)
                if side and i + 1 < len(day_df):
                    next_row    = day_df.iloc[i + 1]
                    entry_price = next_row["open"]
                    qty = position_size(equity, entry_price, confidence)
                    if side == "long" and equity >= entry_price * qty:
                        position = Trade(symbol=sym, side="long",
                                         entry_time=next_row.name, entry_price=entry_price, qty=qty, confidence=confidence)
                    elif side == "short" and sym in shortable:
                        position = Trade(symbol=sym, side="short",
                                         entry_time=next_row.name, entry_price=entry_price, qty=qty, confidence=confidence)

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


def main(days: int = 60):
    original_hard_stop = config.HARD_STOP_PCT  # 원복용

    daily_dfs, intraday_dfs, shortable, all_dates = load_data(days)

    combos = list(itertools.product(COOLDOWN_GRID, HARD_STOP_GRID, STRICT_EXIT_GRID))
    total  = len(combos)
    rows: list[OptimRow] = []

    print(f"총 {total}개 조합 시뮬레이션 시작...\n")
    print(f"{'쿨다운':>12} {'손절':>6} {'청산':>6} │ {'거래':>5} {'승률':>7} {'수익률':>8} {'MDD':>7} {'샤프':>6} {'점수':>7}")
    print("─" * 80)

    for idx, (cd, hs, se) in enumerate(combos, 1):
        result = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                          cooldown_bars=cd, hard_stop_pct=hs, strict_exit=se)
        r = result
        n = len(r.trades)
        wr = r.win_rate
        tr = r.total_return_pct
        mdd = r.mdd
        sh = r.sharpe
        row = OptimRow(cd, hs, se, n, wr, tr, mdd, sh)
        rows.append(row)

        se_str = "엄격" if se else "완화"
        print(f"[{idx:3d}/{total}] 쿨={cd:2d}봉 손절={hs*100:.1f}% 청산={se_str} │"
              f" {n:4d}건 {wr:6.1f}% {tr:+7.2f}% {mdd:+6.2f}% {sh:6.2f} {row.score():+6.2f}")

    config.HARD_STOP_PCT = original_hard_stop  # 원복

    rows.sort(key=lambda r: r.score(), reverse=True)

    print("\n" + "=" * 90)
    print("  ★ 상위 10개 조합 (점수 = 샤프×0.4 + 수익률×0.3 + MDD×0.3)")
    print("=" * 90)
    for i, r in enumerate(rows[:10], 1):
        se_str = "엄격" if r.strict_exit else "완화"
        print(f"  {i:2d}위  쿨다운={r.cooldown:2d}봉({r.cooldown*5:3d}분)  "
              f"손절={r.hard_stop*100:.1f}%  청산={se_str}  │  "
              f"거래={r.trades:3d}건  승률={r.win_rate:.1f}%  "
              f"수익={r.total_return:+.2f}%  MDD={r.mdd:+.2f}%  "
              f"샤프={r.sharpe:.2f}  점수={r.score():+.2f}")

    best = rows[0]
    print(f"\n  현재 설정: 쿨다운=5봉(25분)  손절=2.0%  청산={'엄격' if config.STRICT_EXIT else '완화'}")
    print(f"  최적 설정: 쿨다운={best.cooldown}봉({best.cooldown*5}분)  "
          f"손절={best.hard_stop*100:.1f}%  청산={'엄격' if best.strict_exit else '완화'}")

    # 쿨다운별 평균 성과 (다른 파라미터 평균)
    print("\n" + "=" * 60)
    print("  쿨다운별 평균 점수 (손절/청산 평균)")
    print("=" * 60)
    for cd in COOLDOWN_GRID:
        subset = [r for r in rows if r.cooldown == cd]
        avg_score  = np.mean([r.score() for r in subset])
        avg_return = np.mean([r.total_return for r in subset])
        avg_wr     = np.mean([r.win_rate for r in subset])
        marker = " ← 현재" if cd == 5 else ""
        print(f"  쿨다운={cd:2d}봉({cd*5:3d}분)  평균점수={avg_score:+.2f}  "
              f"평균수익={avg_return:+.2f}%  평균승률={avg_wr:.1f}%{marker}")

    # 확신도(1/2/3)별 승패 분석 — 현재 설정 기준으로 1회 시뮬레이션
    print("\n" + "=" * 65)
    print("  확신도별 승패 분석 (현재 설정: 쿨=5봉 손절=2% 청산=엄격)")
    print("=" * 65)
    conf_result = simulate(daily_dfs, intraday_dfs, shortable, all_dates,
                           cooldown_bars=5, hard_stop_pct=0.02, strict_exit=True)
    config.HARD_STOP_PCT = original_hard_stop

    print(f"  {'확신도':>4} │ {'거래':>5} {'승':>5} {'패':>5} {'승률':>7} {'평균수익률':>10} {'총손익':>10}  포지션비중")
    print(f"  {'─'*4}─┼─{'─'*56}")
    tiers = config.POSITION_SIZE_TIERS
    for conf in [1, 2, 3]:
        trades = [t for t in conf_result.trades if t.confidence == conf]
        if not trades:
            print(f"     {conf} │  데이터 없음")
            continue
        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        wr     = len(wins) / len(trades) * 100
        avg    = np.mean([t.pnl_pct for t in trades])
        total  = sum(t.pnl for t in trades)
        pct    = tiers[conf - 1] * 100
        print(f"     {conf} │ {len(trades):5d} {len(wins):5d} {len(losses):5d} {wr:6.1f}% {avg:+9.2f}% ${total:+9.2f}  {pct:.0f}%")
    all_t = conf_result.trades
    if all_t:
        wins  = [t for t in all_t if t.pnl > 0]
        wr    = len(wins) / len(all_t) * 100
        avg   = np.mean([t.pnl_pct for t in all_t])
        total = sum(t.pnl for t in all_t)
        print(f"  {'합계':>4} │ {len(all_t):5d} {len(wins):5d} {len(all_t)-len(wins):5d} {wr:6.1f}% {avg:+9.2f}% ${total:+9.2f}")
        print(f"\n  → 확신도 3인 신호가 더 높은 승률을 보이면 POSITION_SIZE_TIERS 비중 차이를 늘려도 됩니다.")
        print(f"     반대로 1~3 승률이 비슷하면 단일 포지션 비중이 나을 수 있습니다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60, help="백테스트 기간(일)")
    args = parser.parse_args()
    main(days=args.days)
