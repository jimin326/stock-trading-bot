from enum import Enum
import pandas as pd

from src.indicators import add_indicators, latest
from src.config import EMA_TOUCH_PCT, SIDEWAYS_WINDOW, SIDEWAYS_CROSS_THRESHOLD


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def get_signal(df: pd.DataFrame) -> tuple[Signal, str]:
    df = add_indicators(df)

    if len(df) < 2:
        return Signal.HOLD, "데이터 부족"

    row = latest(df)

    ema9 = row["ema9"]
    vwap = row["vwap"]
    close = row["close"]
    open_ = row["open"]
    low = row["low"]
    high = row["high"]

    if pd.isna(ema9) or pd.isna(vwap):
        return Signal.HOLD, "지표 계산 데이터 부족"

    # 횡보장 체크
    if _is_sideways(df):
        return Signal.HOLD, "횡보장 - 관망"

    above_vwap = close > vwap
    below_vwap = close < vwap
    is_bullish = close > open_
    is_bearish = close < open_

    # EMA9 터치 후 지지/저항 확인
    ema_support = low <= ema9 * (1 + EMA_TOUCH_PCT) and close > ema9
    ema_resistance = high >= ema9 * (1 - EMA_TOUCH_PCT) and close < ema9

    empty_above = bool(row.get("vp_empty_above", False))
    empty_below = bool(row.get("vp_empty_below", False))

    # 롱 진입: VWAP 위 + EMA9 지지 반등(양봉) + 위쪽 매물 없음
    if above_vwap and ema_support and is_bullish and empty_above:
        return Signal.BUY, f"VWAP위({vwap:.2f}) + EMA9지지반등({ema9:.2f}) + 위쪽매물공백"

    # 숏 진입: VWAP 아래 + EMA9 저항(음봉) + 아래쪽 매물 없음
    if below_vwap and ema_resistance and is_bearish and empty_below:
        return Signal.SELL, f"VWAP아래({vwap:.2f}) + EMA9저항({ema9:.2f}) + 아래쪽매물공백"

    return Signal.HOLD, f"EMA9={ema9:.2f} | VWAP={vwap:.2f} | {'VWAP위' if above_vwap else 'VWAP아래'}"


def _is_sideways(df: pd.DataFrame) -> bool:
    recent = df.tail(SIDEWAYS_WINDOW)
    if "vwap" not in recent.columns:
        return False
    crossings = 0
    for i in range(1, len(recent)):
        prev_above = recent["close"].iloc[i - 1] > recent["vwap"].iloc[i - 1]
        curr_above = recent["close"].iloc[i] > recent["vwap"].iloc[i]
        if prev_above != curr_above:
            crossings += 1
    return crossings >= SIDEWAYS_CROSS_THRESHOLD


if __name__ == "__main__":
    from src.data_feed import get_bars

    for symbol in ["AAPL", "TSLA", "NVDA", "MSFT"]:
        df = get_bars(symbol, days=30)
        signal, reason = get_signal(df)
        print(f"[{signal.value:4s}] {symbol:5s} | {reason}")
