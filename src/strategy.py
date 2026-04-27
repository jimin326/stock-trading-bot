from enum import Enum
import pandas as pd

from src.indicators import add_indicators, latest
from src.config import SIDEWAYS_WINDOW, SIDEWAYS_CROSS_THRESHOLD


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def get_signal(df: pd.DataFrame) -> tuple[Signal, str]:
    df = add_indicators(df)

    if len(df) < 2:
        return Signal.HOLD, "데이터 부족"

    row = latest(df)

    ema9  = row["ema9"]
    vwap  = row["vwap"]
    close = row["close"]
    open_ = row["open"]

    if pd.isna(ema9) or pd.isna(vwap):
        return Signal.HOLD, "지표 계산 데이터 부족"

    if _is_sideways(df):
        return Signal.HOLD, "횡보장 - 관망"

    is_bullish = close > open_
    is_bearish = close < open_

    above_vwap   = close > vwap
    below_vwap   = close < vwap
    uptrend      = close > ema9   # EMA9 위 = 상승추세
    downtrend    = close < ema9   # EMA9 아래 = 하락추세

    empty_above = bool(row.get("vp_empty_above", False))
    empty_below = bool(row.get("vp_empty_below", False))

    # 롱: VWAP 위 + 상승추세(EMA9 위) + 양봉 + 위쪽 매물 없음
    if above_vwap and uptrend and is_bullish and empty_above:
        return Signal.BUY, f"VWAP위({vwap:.2f}) + EMA9위({ema9:.2f}) + 위쪽매물공백"

    # 숏: VWAP 아래 + 하락추세(EMA9 아래) + 음봉 + 아래쪽 매물 없음
    if below_vwap and downtrend and is_bearish and empty_below:
        return Signal.SELL, f"VWAP아래({vwap:.2f}) + EMA9아래({ema9:.2f}) + 아래쪽매물공백"

    trend_str = "EMA9위" if uptrend else "EMA9아래"
    vwap_str  = "VWAP위" if above_vwap else "VWAP아래"
    return Signal.HOLD, f"{vwap_str} | {trend_str} | EMA9={ema9:.2f} VWAP={vwap:.2f}"


def _is_sideways(df: pd.DataFrame) -> bool:
    recent = df.tail(SIDEWAYS_WINDOW)
    if "vwap" not in recent.columns:
        return False
    crossings = sum(
        1 for i in range(1, len(recent))
        if (recent["close"].iloc[i - 1] > recent["vwap"].iloc[i - 1])
        != (recent["close"].iloc[i] > recent["vwap"].iloc[i])
    )
    return crossings >= SIDEWAYS_CROSS_THRESHOLD


if __name__ == "__main__":
    from src.data_feed import get_bars

    for symbol in ["AAPL", "TSLA", "NVDA", "MSFT"]:
        df = get_bars(symbol, days=30)
        signal, reason = get_signal(df)
        print(f"[{signal.value:4s}] {symbol:5s} | {reason}")
