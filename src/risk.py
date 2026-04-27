from src.config import MAX_POSITION_PCT


def position_size(equity: float, price: float) -> int:
    max_amount = equity * MAX_POSITION_PCT
    qty = int(max_amount / price)
    return max(qty, 1)


def should_exit_long(close: float, ema9: float) -> bool:
    """롱 포지션 청산: 캔들 몸통(종가)이 EMA9 아래에서 마감"""
    return close < ema9


def should_exit_short(close: float, ema9: float) -> bool:
    """숏 포지션 청산: 캔들 몸통(종가)이 EMA9 위에서 마감"""
    return close > ema9


if __name__ == "__main__":
    equity = 10000
    price = 270.5

    qty = position_size(equity, price)
    print(f"=== 리스크 계산 (잔고 ${equity:,.0f}) ===")
    print(f"매수가   : ${price}")
    print(f"수량     : {qty}주 (${qty * price:,.1f})")
    print(f"청산기준 : EMA9 반대 돌파 시")
