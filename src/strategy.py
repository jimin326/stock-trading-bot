from datetime import datetime, time as dtime
from enum import Enum
from zoneinfo import ZoneInfo
import pandas as pd

from src.indicators import add_indicators, latest, vp_is_clear
from src.config import EMA_TOUCH_PCT, PULLBACK_LOWER_PCT, VWAP_TOUCH_PCT, SIDEWAYS_WINDOW, SIDEWAYS_CROSSES

_ET = ZoneInfo("America/New_York")


def _is_near_market_close() -> bool:
    return datetime.now(_ET).time() >= dtime(15, 50)


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def _is_sideways(df: pd.DataFrame) -> bool:
    """최근 N캔들에서 VWAP 교차 횟수가 임계값 이상이면 횡보로 판단"""
    recent = df.iloc[-SIDEWAYS_WINDOW:]
    above  = recent["close"] > recent["vwap"]
    crosses = (above != above.shift()).sum() - 1
    return int(crosses) >= SIDEWAYS_CROSSES


def get_signal(df: pd.DataFrame) -> tuple[Signal, str, int]:
    """반환: (Signal, 사유, 확신도 1~4)

    기본 조건 (모두 충족해야 진입):
      1. close > VWAP (롱) / close < VWAP (숏)
      2. 최근 6캔들 VWAP 교차 3회 미만 (횡보 아님)
      3. EMA8 >= VWAP (롱) / EMA8 <= VWAP (숏)

    확신도 (VP 여부 + 눌림목 조건 수):
      1 = 눌림목 1개 (EMA or VWAP),  VP 불명확
      2 = 눌림목 1개 + VP clear
      3 = 눌림목 2개 (EMA AND VWAP), VP 불명확
      4 = 눌림목 2개 + VP clear
    """
    df = add_indicators(df)

    if len(df) < 3:
        return Signal.HOLD, "데이터 부족", 0

    row   = latest(df)   # N+1: 진입 캔들
    prev  = df.iloc[-2]  # N  : 양봉 확인 캔들
    prev2 = df.iloc[-3]  # N-1: 눌림목 캔들

    ema8  = row["ema9"]
    vwap  = row["vwap"]
    close = row["close"]

    if pd.isna(ema8) or pd.isna(vwap):
        return Signal.HOLD, "지표 계산 데이터 부족", 0

    if _is_sideways(df):
        return Signal.HOLD, f"횡보장 관망 (VWAP={vwap:.2f})", 0

    # ── VWAP 위 = 롱 타점 탐색 ───────────────────────────────
    if close > vwap and ema8 >= vwap:
        ema_pullback = (prev2["low"] <= ema8 * (1 + EMA_TOUCH_PCT)
                        and prev2["low"] >= ema8 * (1 - PULLBACK_LOWER_PCT))
        vwap_retest  = (prev2["low"] <= vwap * (1 + VWAP_TOUCH_PCT)
                        and prev2["low"] >= vwap * (1 - VWAP_TOUCH_PCT))
        bounce       = (prev["close"] > prev["open"] and prev["close"] > ema8)

        if bounce and (ema_pullback or vwap_retest):
            if _is_near_market_close():
                return Signal.HOLD, "장마감 10분전 매수금지", 0
            both = ema_pullback and vwap_retest
            vp   = vp_is_clear(df, "up")
            if both and vp:     score = 4
            elif both:          score = 3
            elif vp:            score = 2
            else:               score = 1
            tags = []
            if ema_pullback: tags.append(f"EMA8눌림({ema8:.2f})")
            if vwap_retest:  tags.append(f"VWAP리테스트({vwap:.2f})")
            if vp:           tags.append("VP클리어")
            return Signal.BUY, " + ".join(tags), score
        return Signal.HOLD, f"VWAP위 매수타점 대기 | EMA8={ema8:.2f}", 0

    # ── VWAP 아래 = 숏 타점 탐색 ─────────────────────────────
    if close < vwap and ema8 <= vwap:
        ema_pullback = (prev2["high"] >= ema8 * (1 - EMA_TOUCH_PCT)
                        and prev2["high"] <= ema8 * (1 + PULLBACK_LOWER_PCT))
        vwap_retest  = (prev2["high"] >= vwap * (1 - VWAP_TOUCH_PCT)
                        and prev2["high"] <= vwap * (1 + VWAP_TOUCH_PCT))
        bounce       = (prev["close"] < prev["open"] and prev["close"] < ema8)

        if bounce and (ema_pullback or vwap_retest):
            both = ema_pullback and vwap_retest
            vp   = vp_is_clear(df, "down")
            if both and vp:     score = 4
            elif both:          score = 3
            elif vp:            score = 2
            else:               score = 1
            tags = []
            if ema_pullback: tags.append(f"EMA8반락({ema8:.2f})")
            if vwap_retest:  tags.append(f"VWAP리테스트({vwap:.2f})")
            if vp:           tags.append("VP클리어")
            return Signal.SELL, " + ".join(tags), score
        return Signal.HOLD, f"VWAP아래 매도타점 대기 | EMA8={ema8:.2f}", 0

    return Signal.HOLD, f"VWAP={vwap:.2f} EMA8={ema8:.2f}", 0


if __name__ == "__main__":
    from src.data_feed import get_bars

    for symbol in ["AAPL", "TSLA", "NVDA", "MSFT"]:
        df = get_bars(symbol, days=30)
        signal, reason = get_signal(df)
        print(f"[{signal.value:4s}] {symbol:5s} | {reason}")
