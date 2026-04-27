import pandas as pd
import numpy as np
from dataclasses import dataclass, field

from src.indicators import add_indicators
from src.config import MAX_POSITION_PCT, TIMEFRAME, BACKTEST_UNIVERSE, GAP_THRESHOLD, VOL_RATIO_MIN, SCAN_TOP_N
from src.risk import check_exit_long, check_exit_short


@dataclass
class Trade:
    symbol: str
    side: str           # "long" or "short"
    entry_time: pd.Timestamp
    entry_price: float
    qty: int
    exit_time: pd.Timestamp = None
    exit_price: float = None
    reason: str = ""

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.side == "long":
            return (self.exit_price - self.entry_price) * self.qty
        else:
            return (self.entry_price - self.exit_price) * self.qty

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.side == "long":
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - self.exit_price) / self.entry_price * 100


@dataclass
class BacktestResult:
    symbol: str
    initial_equity: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return self.initial_equity + sum(t.pnl for t in self.trades)

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity - self.initial_equity) / self.initial_equity * 100

    @property
    def win_rate(self) -> float:
        wins = [t for t in self.trades if t.pnl > 0]
        return len(wins) / len(self.trades) * 100 if self.trades else 0

    @property
    def mdd(self) -> float:
        if not self.equity_curve:
            return 0.0
        curve = np.array(self.equity_curve)
        peak = np.maximum.accumulate(curve)
        drawdown = (curve - peak) / peak * 100
        return float(drawdown.min())

    @property
    def sharpe(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        returns = [t.pnl_pct for t in self.trades]
        mean = np.mean(returns)
        std = np.std(returns)
        return round(mean / std * np.sqrt(252) if std > 0 else 0.0, 2)

    def summary(self):
        print(f"\n{'='*45}")
        print(f"  백테스트 결과: {self.symbol}")
        print(f"{'='*45}")
        print(f"  초기 자본    : ${self.initial_equity:>10,.2f}")
        print(f"  최종 자본    : ${self.final_equity:>10,.2f}")
        print(f"  총 수익률    : {self.total_return_pct:>+9.2f}%")
        print(f"  최대 낙폭    : {self.mdd:>+9.2f}%")
        print(f"  샤프 비율    : {self.sharpe:>10.2f}")
        print(f"  총 거래 수   : {len(self.trades):>10}건")
        print(f"  승률         : {self.win_rate:>9.1f}%")
        if self.trades:
            avg_pnl = np.mean([t.pnl_pct for t in self.trades])
            print(f"  평균 수익률  : {avg_pnl:>+9.2f}%")
        print(f"{'='*45}")


def run_backtest(df: pd.DataFrame, symbol: str, initial_equity: float = 10000.0) -> BacktestResult:
    df = add_indicators(df).dropna(subset=["ema9", "vwap"])
    result = BacktestResult(symbol=symbol, initial_equity=initial_equity)

    equity = initial_equity
    position: Trade | None = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        close = row["close"]
        open_ = row["open"]
        low = row["low"]
        high = row["high"]
        ema9 = row["ema9"]
        vwap = row["vwap"]
        is_bullish = close > open_
        is_bearish = close < open_
        result.equity_curve.append(equity)

        # 포지션 보유 중 → 청산 체크 (EMA9 돌파 or 하드 손절)
        if position:
            if position.side == "long":
                do_exit, exit_price, reason = check_exit_long(close, open_, low, ema9, position.entry_price)
            else:
                do_exit, exit_price, reason = check_exit_short(close, open_, high, ema9, position.entry_price)

            if do_exit:
                position.exit_time  = row.name
                position.exit_price = exit_price
                position.reason     = reason
                equity += position.pnl
                result.trades.append(position)
                position = None
                continue

        # 포지션 없음 → 진입 신호 체크
        else:
            above_vwap = close > vwap
            below_vwap = close < vwap
            uptrend    = close > ema9
            downtrend  = close < ema9

            empty_above = bool(row.get("vp_empty_above", False))
            empty_below = bool(row.get("vp_empty_below", False))

            # 횡보장 체크 (6봉 중 3번 이상 VWAP 교차)
            recent = df.iloc[max(0, i - 6): i + 1]
            crossings = sum(
                1 for j in range(1, len(recent))
                if (recent["close"].iloc[j - 1] > recent["vwap"].iloc[j - 1])
                != (recent["close"].iloc[j] > recent["vwap"].iloc[j])
            )
            if crossings >= 3:
                continue

            # 롱: VWAP 위 + 상승추세 + 양봉 + 위쪽 매물 없음
            if above_vwap and uptrend and is_bullish and empty_above:
                qty = max(int(equity * MAX_POSITION_PCT / close), 1)
                if equity >= close * qty:
                    position = Trade(
                        symbol=symbol, side="long",
                        entry_time=row.name, entry_price=close, qty=qty,
                    )

            # 숏: VWAP 아래 + 하락추세 + 음봉 + 아래쪽 매물 없음
            elif below_vwap and downtrend and is_bearish and empty_below:
                qty = max(int(equity * MAX_POSITION_PCT / close), 1)
                position = Trade(
                    symbol=symbol, side="short",
                    entry_time=row.name, entry_price=close, qty=qty,
                )

    # 마지막 포지션 강제 청산
    if position:
        last = df.iloc[-1]
        position.exit_time = last.name
        position.exit_price = last["close"]
        position.reason = "강제청산"
        equity += position.pnl
        result.trades.append(position)

    result.equity_curve.append(equity)
    return result


def run_scanner_backtest(
    days: int = 90,
    initial_equity: float = 10_000.0,
    gap_threshold: float = GAP_THRESHOLD,
    vol_ratio_min: float = VOL_RATIO_MIN,
    top_n: int = SCAN_TOP_N,
) -> BacktestResult:
    """매일 스캐너로 종목 선별 후 해당 종목만 거래하는 현실적인 백테스트"""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from datetime import datetime, timedelta
    import src.config as _cfg

    client = StockHistoricalDataClient(_cfg.ALPACA_API_KEY, _cfg.ALPACA_SECRET_KEY)
    end   = datetime.now()
    start_intra = end - timedelta(days=days)
    start_daily = end - timedelta(days=days + 35)  # 20일 평균 계산 여유

    print(f"[1/3] 일봉 데이터 수집 중 ({len(BACKTEST_UNIVERSE)}종목, {days+35}일)...")
    daily_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=BACKTEST_UNIVERSE,
        timeframe=TimeFrame.Day,
        start=start_daily,
        feed=DataFeed.IEX,
    )).data  # dict[symbol, list[Bar]]

    print(f"[2/3] 5분봉 데이터 수집 중 (약 30초 소요)...")
    intraday_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=BACKTEST_UNIVERSE,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start_intra,
        feed=DataFeed.IEX,
    )).data  # dict[symbol, list[Bar]]

    # 일봉 → DataFrame 변환 (종목별)
    daily_dfs: dict[str, pd.DataFrame] = {}
    for sym, bars in daily_bars.items():
        df = pd.DataFrame([{
            "date":   b.timestamp.date(),
            "open":   b.open, "high": b.high, "low": b.low,
            "close":  b.close, "volume": b.volume,
        } for b in bars]).set_index("date")
        daily_dfs[sym] = df

    # 5분봉 → DataFrame 변환 (종목별)
    intraday_dfs: dict[str, pd.DataFrame] = {}
    for sym, bars in intraday_bars.items():
        df = pd.DataFrame([{
            "timestamp": b.timestamp,
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        } for b in bars]).set_index("timestamp")
        intraday_dfs[sym] = df

    # 거래일 목록 (backtest 기간)
    all_dates = sorted(set(
        d for sym_df in daily_dfs.values()
        for d in sym_df.index
        if d >= start_intra.date()
    ))

    print(f"[3/3] 전략 시뮬레이션 중 ({len(all_dates)}거래일)...")
    result = BacktestResult(symbol="SCANNER", initial_equity=initial_equity)
    equity = initial_equity

    for date in all_dates:
        # ── 당일 스캐너: 갭 + 20일 평균 거래량 필터 ──────────────
        candidates = []
        for sym, ddf in daily_dfs.items():
            date_idx = ddf.index.tolist()
            if date not in date_idx:
                continue
            pos = date_idx.index(date)
            if pos < 21:  # 20일 평균 계산 불가
                continue

            today_bar = ddf.loc[date]
            prev_bar  = ddf.iloc[pos - 1]
            hist_bars = ddf.iloc[pos - 21: pos - 1]  # 20일 평균용

            if prev_bar["close"] == 0 or hist_bars["volume"].mean() == 0:
                continue

            gap_pct   = (today_bar["open"] - prev_bar["close"]) / prev_bar["close"] * 100
            vol_ratio = today_bar["volume"] / hist_bars["volume"].mean()

            if abs(gap_pct) >= gap_threshold and vol_ratio >= vol_ratio_min:
                candidates.append((sym, abs(gap_pct) * vol_ratio))

        candidates.sort(key=lambda x: x[1], reverse=True)
        today_symbols = [s for s, _ in candidates[:top_n]]

        if not today_symbols:
            continue

        # ── 선별 종목 당일 5분봉으로 전략 실행 ───────────────────
        for sym in today_symbols:
            if sym not in intraday_dfs:
                continue

            idf = intraday_dfs[sym]
            day_mask = pd.to_datetime(idf.index).date == date
            day_df   = idf[day_mask].copy()

            if len(day_df) < 10:
                continue

            try:
                day_df = add_indicators(day_df).dropna(subset=["ema9", "vwap"])
            except Exception:
                continue

            position = None
            for i in range(1, len(day_df)):
                row   = day_df.iloc[i]
                close = row["close"]
                high  = row["high"]
                low   = row["low"]
                open_ = row["open"]
                ema9  = row["ema9"]
                vwap  = row["vwap"]

                if position:
                    if position.side == "long":
                        do_exit, exit_price, reason = check_exit_long(close, open_, low, ema9, position.entry_price)
                    else:
                        do_exit, exit_price, reason = check_exit_short(close, open_, high, ema9, position.entry_price)

                    if do_exit:
                        position.exit_time  = row.name
                        position.exit_price = exit_price
                        position.reason     = reason
                        equity += position.pnl
                        result.trades.append(position)
                        result.equity_curve.append(equity)
                        position = None
                    continue

                # 진입 신호
                is_bullish  = close > open_
                is_bearish  = close < open_
                above_vwap  = close > vwap
                below_vwap  = close < vwap
                uptrend     = close > ema9
                downtrend   = close < ema9
                empty_above = bool(row.get("vp_empty_above", False))
                empty_below = bool(row.get("vp_empty_below", False))

                recent = day_df.iloc[max(0, i - 6): i + 1]
                crossings = sum(
                    1 for j in range(1, len(recent))
                    if (recent["close"].iloc[j-1] > recent["vwap"].iloc[j-1])
                    != (recent["close"].iloc[j] > recent["vwap"].iloc[j])
                )
                if crossings >= 3:
                    continue

                if above_vwap and uptrend and is_bullish and empty_above:
                    qty = max(int(equity * MAX_POSITION_PCT / close), 1)
                    if equity >= close * qty:
                        position = Trade(symbol=sym, side="long",
                                         entry_time=row.name, entry_price=close, qty=qty)

                elif below_vwap and downtrend and is_bearish and empty_below:
                    qty = max(int(equity * MAX_POSITION_PCT / close), 1)
                    position = Trade(symbol=sym, side="short",
                                     entry_time=row.name, entry_price=close, qty=qty)

            # 장 마감 강제 청산
            if position:
                last = day_df.iloc[-1]
                position.exit_time  = last.name
                position.exit_price = last["close"]
                position.reason     = "장마감청산"
                equity += position.pnl
                result.trades.append(position)
                result.equity_curve.append(equity)
                position = None

    result.equity_curve.append(equity)
    return result


if __name__ == "__main__":
    result = run_scanner_backtest(days=90)
    result.summary()

    if result.trades:
        print(f"\n  종목별 거래 수:")
        from collections import Counter
        for sym, cnt in Counter(t.symbol for t in result.trades).most_common(10):
            print(f"    {sym}: {cnt}건")

        print(f"\n  최근 거래 10건:")
        for t in result.trades[-10:]:
            print(f"    [{t.side:5s}] {t.symbol:6s} {t.entry_time.strftime('%m/%d %H:%M')} → "
                  f"{t.exit_time.strftime('%H:%M')} | {t.pnl_pct:+.2f}% | {t.reason}")
