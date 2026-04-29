import src.config as config


def position_size(equity: float, price: float, confidence: int = 1) -> float:
    tiers = config.POSITION_SIZE_TIERS
    pct   = tiers[min(confidence - 1, len(tiers) - 1)]
    if config.FRACTIONAL_SHARES:
        return round(equity * pct / price, 4)   # 소수점 4자리
    else:
        qty = int(equity * pct / price)
        return max(qty, 1)                       # 정수, 최소 1주


def check_exit_long(
    close: float, open_: float, low: float, ema9: float, entry: float,
    strict: bool = False,
) -> tuple[bool, float, str]:
    """
    롱 청산 조건. 반환: (청산여부, 청산가격, 사유)
    strict=False(기본): 몸통 전체가 EMA8 아래여야 청산
    strict=True(영상방식): 종가만 EMA8 아래면 즉시 청산
    """
    stop_price = entry * (1 - config.HARD_STOP_PCT)
    if low <= stop_price:
        return True, stop_price, f"하드손절(-{config.HARD_STOP_PCT*100:.0f}%)"
    if strict:
        if close < ema9:
            return True, close, "EMA8하향이탈(종가)"
    else:
        if max(open_, close) < ema9:
            return True, close, "EMA8하향이탈"
    return False, close, ""


def check_exit_short(
    close: float, open_: float, high: float, ema9: float, entry: float,
    strict: bool = False,
) -> tuple[bool, float, str]:
    """
    숏 청산 조건. 반환: (청산여부, 청산가격, 사유)
    strict=False(기본): 몸통 전체가 EMA8 위여야 청산
    strict=True(영상방식): 종가만 EMA8 위면 즉시 청산
    """
    stop_price = entry * (1 + config.HARD_STOP_PCT)
    if high >= stop_price:
        return True, stop_price, f"하드손절(-{config.HARD_STOP_PCT*100:.0f}%)"
    if strict:
        if close > ema9:
            return True, close, "EMA8상향이탈(종가)"
    else:
        if min(open_, close) > ema9:
            return True, close, "EMA8상향이탈"
    return False, close, ""
