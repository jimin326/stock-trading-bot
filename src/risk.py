import src.config as config


def position_size(equity: float, price: float) -> int:
    qty = int(equity * config.MAX_POSITION_PCT / price)
    return max(qty, 1)


def check_exit_long(
    close: float, low: float, ema9: float, entry: float
) -> tuple[bool, float, str]:
    """
    롱 청산 조건 확인. 반환: (청산여부, 청산가격, 사유)
    하드손절: 캔들 저가가 손절선 터치 → 손절선 가격으로 청산 (실손 3% 고정)
    EMA청산: 종가가 EMA9 아래 마감
    """
    stop_price = entry * (1 - config.HARD_STOP_PCT)
    if low <= stop_price:
        return True, stop_price, f"하드손절(-{config.HARD_STOP_PCT*100:.0f}%)"
    if close < ema9:
        return True, close, "EMA9하향이탈"
    return False, close, ""


def check_exit_short(
    close: float, high: float, ema9: float, entry: float
) -> tuple[bool, float, str]:
    """
    숏 청산 조건 확인. 반환: (청산여부, 청산가격, 사유)
    하드손절: 캔들 고가가 손절선 터치 → 손절선 가격으로 청산 (실손 3% 고정)
    EMA청산: 종가가 EMA9 위 마감
    """
    stop_price = entry * (1 + config.HARD_STOP_PCT)
    if high >= stop_price:
        return True, stop_price, f"하드손절(-{config.HARD_STOP_PCT*100:.0f}%)"
    if close > ema9:
        return True, close, "EMA9상향이탈"
    return False, close, ""
