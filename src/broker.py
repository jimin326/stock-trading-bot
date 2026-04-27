from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.trading.models import Order, Position

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY

_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)


def get_account() -> dict:
    acct = _client.get_account()
    return {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "pnl": float(acct.equity) - float(acct.last_equity),
    }


def get_positions() -> list[Position]:
    return _client.get_all_positions()


def get_position(symbol: str) -> Position | None:
    try:
        return _client.get_open_position(symbol)
    except Exception:
        return None


def buy_market(symbol: str, qty: int) -> Order:
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = _client.submit_order(req)
    print(f"[매수] {symbol} {qty}주 | 시장가")
    return order


def sell_market(symbol: str, qty: int) -> Order:
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = _client.submit_order(req)
    print(f"[매도] {symbol} {qty}주 | 시장가")
    return order


def buy_limit(symbol: str, qty: int, price: float) -> Order:
    req = LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=round(price, 2),
    )
    order = _client.submit_order(req)
    print(f"[매수] {symbol} {qty}주 | 지정가 ${price:.2f}")
    return order


def sell_limit(symbol: str, qty: int, price: float) -> Order:
    req = LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=round(price, 2),
    )
    order = _client.submit_order(req)
    print(f"[매도] {symbol} {qty}주 | 지정가 ${price:.2f}")
    return order


def cancel_all_orders():
    _client.cancel_orders()
    print("[취소] 모든 미체결 주문 취소")


def close_all_positions():
    _client.close_all_positions(cancel_orders=True)
    print("[청산] 모든 포지션 청산")


if __name__ == "__main__":
    acct = get_account()
    print(f"=== 계좌 현황 ===")
    print(f"총 자산    : ${acct['equity']:,.2f}")
    print(f"현금       : ${acct['cash']:,.2f}")
    print(f"매수 가능  : ${acct['buying_power']:,.2f}")
    print(f"오늘 손익  : ${acct['pnl']:+,.2f}")

    positions = get_positions()
    if positions:
        print(f"\n=== 보유 포지션 ===")
        for p in positions:
            print(f"  {p.symbol:6s} | {p.qty}주 | 평균가 ${float(p.avg_entry_price):.2f} | 손익 ${float(p.unrealized_pl):+.2f}")
    else:
        print("\n보유 포지션 없음")
