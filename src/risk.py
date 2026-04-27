from src.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_POSITION_PCT


def position_size(equity: float, price: float) -> int:
    max_amount = equity * MAX_POSITION_PCT
    qty = int(max_amount / price)
    return max(qty, 1)


def stop_loss_price(entry_price: float) -> float:
    return round(entry_price * (1 - STOP_LOSS_PCT), 2)


def take_profit_price(entry_price: float) -> float:
    return round(entry_price * (1 + TAKE_PROFIT_PCT), 2)


def should_stop_loss(entry_price: float, current_price: float) -> bool:
    return current_price <= stop_loss_price(entry_price)


def should_take_profit(entry_price: float, current_price: float) -> bool:
    return current_price >= take_profit_price(entry_price)


if __name__ == "__main__":
    equity = 10000
    price = 270.5

    qty = position_size(equity, price)
    sl = stop_loss_price(price)
    tp = take_profit_price(price)

    print(f"=== 리스크 계산 (잔고 ${equity:,.0f}) ===")
    print(f"매수가   : ${price}")
    print(f"수량     : {qty}주 (${qty * price:,.1f})")
    print(f"손절가   : ${sl}  (-{STOP_LOSS_PCT*100:.0f}%)")
    print(f"익절가   : ${tp}  (+{TAKE_PROFIT_PCT*100:.0f}%)")
