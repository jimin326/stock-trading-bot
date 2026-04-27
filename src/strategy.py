from enum import Enum
import pandas as pd

from src.indicators import add_indicators, latest
from src.config import EMA_TOUCH_PCT, PULLBACK_LOWER_PCT


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def get_signal(df: pd.DataFrame) -> tuple[Signal, str]:
    df = add_indicators(df)

    if len(df) < 2:
        return Signal.HOLD, "데이터 부족"

    row  = latest(df)
    prev = df.iloc[-2]

    ema9  = row["ema9"]
    vwap  = row["vwap"]
    close = row["close"]
    open_ = row["open"]

    if pd.isna(ema9) or pd.isna(vwap):
        return Signal.HOLD, "지표 계산 데이터 부족"

    is_bullish = close > open_
    is_bearish = close < open_

    # ── VWAP 위 = 롱 타점만 탐색 ─────────────────────────────
    if close > vwap:
        # 눌림목: 직전 캔들 저가가 EMA9 근처(+0.5% ~ -2%)까지 눌렸다가
        # 현재 캔들이 EMA9 위에서 양봉으로 마감 → 진입
        pullback = (prev["low"] <= ema9 * (1 + EMA_TOUCH_PCT)
                    and prev["low"] >= ema9 * (1 - PULLBACK_LOWER_PCT))
        bounce   = is_bullish and close > ema9
        if pullback and bounce:
            return Signal.BUY, f"VWAP위({vwap:.2f}) | EMA9눌림반등({ema9:.2f})"
        return Signal.HOLD, f"VWAP위 매수타점 대기 | EMA9={ema9:.2f}"

    # ── VWAP 아래 = 숏 타점만 탐색 ───────────────────────────
    if close < vwap:
        # 눌림목: 직전 캔들 고가가 EMA9 근처(-0.5% ~ +2%)까지 되돌아갔다가
        # 현재 캔들이 EMA9 아래에서 음봉으로 마감 → 진입
        pullback = (prev["high"] >= ema9 * (1 - EMA_TOUCH_PCT)
                    and prev["high"] <= ema9 * (1 + PULLBACK_LOWER_PCT))
        bounce   = is_bearish and close < ema9
        if pullback and bounce:
            return Signal.SELL, f"VWAP아래({vwap:.2f}) | EMA9반락({ema9:.2f})"
        return Signal.HOLD, f"VWAP아래 매도타점 대기 | EMA9={ema9:.2f}"

    return Signal.HOLD, f"VWAP={vwap:.2f} EMA9={ema9:.2f}"


if __name__ == "__main__":
    from src.data_feed import get_bars

    for symbol in ["AAPL", "TSLA", "NVDA", "MSFT"]:
        df = get_bars(symbol, days=30)
        signal, reason = get_signal(df)
        print(f"[{signal.value:4s}] {symbol:5s} | {reason}")
