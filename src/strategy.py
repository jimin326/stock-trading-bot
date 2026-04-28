from enum import Enum
import pandas as pd

from src.indicators import add_indicators, latest
from src.config import EMA_TOUCH_PCT, PULLBACK_LOWER_PCT, VWAP_TOUCH_PCT, SIDEWAYS_WINDOW, SIDEWAYS_CROSSES


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def _is_sideways(df: pd.DataFrame) -> bool:
    """최근 N캔들에서 VWAP 교차 횟수가 임계값 이상이면 횡보로 판단"""
    recent = df.iloc[-SIDEWAYS_WINDOW:]
    above  = recent["close"] > recent["vwap"]
    crosses = (above != above.shift()).sum() - 1  # 첫 번째는 기준점이라 제외
    return int(crosses) >= SIDEWAYS_CROSSES


def get_signal(df: pd.DataFrame) -> tuple[Signal, str, int]:
    """반환: (Signal, 사유, 확신도 1~3)
    확신도 1 = EMA 또는 VWAP 리테스트 하나만 해당
    확신도 2 = EMA + VWAP 리테스트 둘 다 해당
    확신도 3 = 둘 다 + 강한 추세 (VWAP에서 0.5% 이상 이격)
    """
    df = add_indicators(df)

    if len(df) < 2:
        return Signal.HOLD, "데이터 부족", 0

    row  = latest(df)
    prev = df.iloc[-2]

    ema8  = row["ema9"]
    vwap  = row["vwap"]
    close = row["close"]
    open_ = row["open"]

    if pd.isna(ema8) or pd.isna(vwap):
        return Signal.HOLD, "지표 계산 데이터 부족", 0

    if _is_sideways(df):
        return Signal.HOLD, f"횡보장 관망 (VWAP={vwap:.2f})", 0

    is_bullish = close > open_
    is_bearish = close < open_

    # ── VWAP 위 = 롱 타점 탐색 ───────────────────────────────
    if close > vwap:
        ema_pullback  = (prev["low"] <= ema8 * (1 + EMA_TOUCH_PCT)
                         and prev["low"] >= ema8 * (1 - PULLBACK_LOWER_PCT))
        vwap_retest   = (prev["low"] <= vwap * (1 + VWAP_TOUCH_PCT)
                         and prev["low"] >= vwap * (1 - VWAP_TOUCH_PCT))
        bounce        = is_bullish and close > ema8

        if bounce and (ema_pullback or vwap_retest):
            score = 1 + int(ema_pullback and vwap_retest) + int(close > vwap * 1.005)
            tags  = []
            if ema_pullback:  tags.append(f"EMA8눌림({ema8:.2f})")
            if vwap_retest:   tags.append(f"VWAP리테스트({vwap:.2f})")
            return Signal.BUY, " + ".join(tags), score
        return Signal.HOLD, f"VWAP위 매수타점 대기 | EMA8={ema8:.2f}", 0

    # ── VWAP 아래 = 숏 타점 탐색 ─────────────────────────────
    if close < vwap:
        ema_pullback  = (prev["high"] >= ema8 * (1 - EMA_TOUCH_PCT)
                         and prev["high"] <= ema8 * (1 + PULLBACK_LOWER_PCT))
        vwap_retest   = (prev["high"] >= vwap * (1 - VWAP_TOUCH_PCT)
                         and prev["high"] <= vwap * (1 + VWAP_TOUCH_PCT))
        bounce        = is_bearish and close < ema8

        if bounce and (ema_pullback or vwap_retest):
            score = 1 + int(ema_pullback and vwap_retest) + int(close < vwap * 0.995)
            tags  = []
            if ema_pullback:  tags.append(f"EMA8반락({ema8:.2f})")
            if vwap_retest:   tags.append(f"VWAP리테스트({vwap:.2f})")
            return Signal.SELL, " + ".join(tags), score
        return Signal.HOLD, f"VWAP아래 매도타점 대기 | EMA8={ema8:.2f}", 0

    return Signal.HOLD, f"VWAP={vwap:.2f} EMA8={ema8:.2f}", 0


if __name__ == "__main__":
    from src.data_feed import get_bars

    for symbol in ["AAPL", "TSLA", "NVDA", "MSFT"]:
        df = get_bars(symbol, days=30)
        signal, reason = get_signal(df)
        print(f"[{signal.value:4s}] {symbol:5s} | {reason}")
