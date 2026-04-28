import pandas as pd
import numpy as np
from dataclasses import dataclass, field

from src.indicators import add_indicators
from src.config import POSITION_SIZE_TIERS, BACKTEST_UNIVERSE, GAP_THRESHOLD, VOL_RATIO_MIN, SCAN_TOP_N, EMA_TOUCH_PCT, PULLBACK_LOWER_PCT, VWAP_TOUCH_PCT, SIDEWAYS_WINDOW, SIDEWAYS_CROSSES, COOLDOWN_BARS
from src.risk import check_exit_long, check_exit_short, position_size


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
    def fee(self) -> float:
        """Alpaca 규제 수수료: SEC fee + FINRA TAF (매도 시 부과)"""
        if self.exit_price is None:
            return 0.0
        sell_price  = self.exit_price if self.side == "long" else self.entry_price
        sell_amount = sell_price * self.qty
        sec_fee     = sell_amount * 0.0000278
        finra_taf   = min(self.qty * 0.000166, 8.30)
        return sec_fee + finra_taf

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.side == "long":
            return (self.exit_price - self.entry_price) * self.qty - self.fee
        else:
            return (self.entry_price - self.exit_price) * self.qty - self.fee

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        cost = self.entry_price * self.qty
        if self.side == "long":
            return (self.exit_price - self.entry_price) * self.qty / cost * 100
        else:
            return (self.entry_price - self.exit_price) * self.qty / cost * 100


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
        total_fee = sum(t.fee for t in self.trades)
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
        print(f"  총 수수료    : ${total_fee:>10.2f}")
        if self.trades:
            avg_pnl = np.mean([t.pnl_pct for t in self.trades])
            print(f"  평균 수익률  : {avg_pnl:>+9.2f}%")
        print(f"{'='*45}")

    def print_trades(self, n: int = 20):
        if not self.trades:
            print("  거래 없음")
            return
        header = f"{'#':>4}  {'종목':6} {'방향':5} {'진입시간':16} {'진입가':>8} {'청산시간':16} {'청산가':>8} {'수익률':>7}  {'사유'}"
        print(f"\n  최근 거래 {min(n, len(self.trades))}건:")
        print(f"  {header}")
        print(f"  {'-'*len(header)}")
        for idx, t in enumerate(self.trades[-n:], 1):
            entry_str = t.entry_time.strftime("%m/%d %H:%M") if t.entry_time else "-"
            exit_str  = t.exit_time.strftime("%m/%d %H:%M")  if t.exit_time  else "-"
            print(
                f"  {idx:>4}  {t.symbol:6} {t.side:5} "
                f"{entry_str:16} {t.entry_price:>8.2f} "
                f"{exit_str:16} {t.exit_price:>8.2f} "
                f"{t.pnl_pct:>+6.2f}%  {t.reason}"
            )


def _is_sideways(df: pd.DataFrame, i: int) -> bool:
    """인덱스 i 기준 최근 N캔들에서 VWAP 교차 횟수 >= 임계값이면 횡보"""
    start = max(0, i - SIDEWAYS_WINDOW + 1)
    recent = df.iloc[start:i + 1]
    above = recent["close"] > recent["vwap"]
    crosses = int((above != above.shift()).sum()) - 1
    return crosses >= SIDEWAYS_CROSSES


def _check_entry(row: pd.Series, prev: pd.Series) -> tuple[str | None, int]:
    """진입 조건 확인. 반환: (side, confidence) — side는 'long'|'short'|None"""
    close = row["close"]
    open_ = row["open"]
    ema8  = row["ema9"]
    vwap  = row["vwap"]

    is_bullish = close > open_
    is_bearish = close < open_

    if close > vwap:
        ema_pullback = (prev["low"] <= ema8 * (1 + EMA_TOUCH_PCT)
                        and prev["low"] >= ema8 * (1 - PULLBACK_LOWER_PCT))
        vwap_retest  = (prev["low"] <= vwap * (1 + VWAP_TOUCH_PCT)
                        and prev["low"] >= vwap * (1 - VWAP_TOUCH_PCT))
        bounce       = is_bullish and close > ema8
        if bounce and (ema_pullback or vwap_retest):
            score = 1 + int(ema_pullback and vwap_retest) + int(close > vwap * 1.005)
            return "long", score

    elif close < vwap:
        ema_pullback = (prev["high"] >= ema8 * (1 - EMA_TOUCH_PCT)
                        and prev["high"] <= ema8 * (1 + PULLBACK_LOWER_PCT))
        vwap_retest  = (prev["high"] >= vwap * (1 - VWAP_TOUCH_PCT)
                        and prev["high"] <= vwap * (1 + VWAP_TOUCH_PCT))
        bounce       = is_bearish and close < ema8
        if bounce and (ema_pullback or vwap_retest):
            score = 1 + int(ema_pullback and vwap_retest) + int(close < vwap * 0.995)
            return "short", score

    return None, 0


def run_backtest(df: pd.DataFrame, symbol: str, initial_equity: float = 10000.0, long_only: bool = False) -> BacktestResult:
    df = add_indicators(df).dropna(subset=["ema9", "vwap"])
    result = BacktestResult(symbol=symbol, initial_equity=initial_equity)

    equity = initial_equity
    position: Trade | None = None

    for i in range(1, len(df)):
        row  = df.iloc[i]
        prev = df.iloc[i - 1]

        close = row["close"]
        open_ = row["open"]
        low   = row["low"]
        high  = row["high"]
        ema9  = row["ema9"]
        result.equity_curve.append(equity)

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

        if _is_sideways(df, i):
            continue
        side, confidence = _check_entry(row, prev)
        if side and i + 1 < len(df):
            next_row    = df.iloc[i + 1]
            entry_price = next_row["open"]
            qty = position_size(equity, entry_price, confidence)
            if side == "long" and equity >= entry_price * qty:
                position = Trade(symbol=symbol, side="long",
                                 entry_time=next_row.name, entry_price=entry_price, qty=qty)
            elif side == "short" and not long_only:
                position = Trade(symbol=symbol, side="short",
                                 entry_time=next_row.name, entry_price=entry_price, qty=qty)

    # 마지막 포지션 강제 청산
    if position:
        last = df.iloc[-1]
        position.exit_time  = last.name
        position.exit_price = last["close"]
        position.reason     = "강제청산"
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
    cooldown_bars: int = COOLDOWN_BARS,
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
    start_daily = end - timedelta(days=days + 35)

    print(f"[1/3] 일봉 데이터 수집 중 ({len(BACKTEST_UNIVERSE)}종목, {days+35}일)...")
    daily_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=BACKTEST_UNIVERSE,
        timeframe=TimeFrame.Day,
        start=start_daily,
        feed=DataFeed.IEX,
    )).data

    print(f"[2/3] 5분봉 데이터 수집 중 (약 30초 소요)...")
    intraday_bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=BACKTEST_UNIVERSE,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start_intra,
        feed=DataFeed.IEX,
    )).data

    daily_dfs: dict[str, pd.DataFrame] = {}
    for sym, bars in daily_bars.items():
        df = pd.DataFrame([{
            "date":   b.timestamp.date(),
            "open":   b.open, "high": b.high, "low": b.low,
            "close":  b.close, "volume": b.volume,
        } for b in bars]).set_index("date")
        daily_dfs[sym] = df

    intraday_dfs: dict[str, pd.DataFrame] = {}
    for sym, bars in intraday_bars.items():
        df = pd.DataFrame([{
            "timestamp": b.timestamp,
            "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume,
        } for b in bars]).set_index("timestamp")
        intraday_dfs[sym] = df

    all_dates = sorted(set(
        d for sym_df in daily_dfs.values()
        for d in sym_df.index
        if d >= start_intra.date()
    ))

    print(f"[3/3] 공매도 가능 종목 조회 중...")
    from src.broker import get_shortable_set
    shortable = get_shortable_set(BACKTEST_UNIVERSE)
    print(f"      공매도 가능: {len(shortable)}/{len(BACKTEST_UNIVERSE)}종목")

    print(f"[4/4] 전략 시뮬레이션 중 ({len(all_dates)}거래일)...")
    result = BacktestResult(symbol="SCANNER", initial_equity=initial_equity)
    equity = initial_equity

    for date in all_dates:
        candidates = []
        for sym, ddf in daily_dfs.items():
            date_idx = ddf.index.tolist()
            if date not in date_idx:
                continue
            pos = date_idx.index(date)
            if pos < 21:
                continue

            today_bar = ddf.loc[date]
            prev_bar  = ddf.iloc[pos - 1]
            hist_bars = ddf.iloc[pos - 21: pos - 1]

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
            cooldown_until = -1
            for i in range(1, len(day_df)):
                row   = day_df.iloc[i]
                prev  = day_df.iloc[i - 1]
                close = row["close"]
                open_ = row["open"]
                high  = row["high"]
                low   = row["low"]
                ema9  = row["ema9"]

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
                        cooldown_until = i + cooldown_bars
                    continue

                if i <= cooldown_until:
                    continue
                if _is_sideways(day_df, i):
                    continue
                side, confidence = _check_entry(row, prev)
                if side and i + 1 < len(day_df):
                    next_row    = day_df.iloc[i + 1]
                    entry_price = next_row["open"]
                    qty = position_size(equity, entry_price, confidence)
                    if side == "long" and equity >= entry_price * qty:
                        position = Trade(symbol=sym, side="long",
                                         entry_time=next_row.name, entry_price=entry_price, qty=qty)
                    elif side == "short" and sym in shortable:
                        position = Trade(symbol=sym, side="short",
                                         entry_time=next_row.name, entry_price=entry_price, qty=qty)

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
    result.print_trades(n=20)

    if result.trades:
        print(f"\n  종목별 거래 수:")
        from collections import Counter
        for sym, cnt in Counter(t.symbol for t in result.trades).most_common(10):
            print(f"    {sym}: {cnt}건")
