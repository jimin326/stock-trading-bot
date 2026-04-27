import asyncio
from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed
from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, TRADE_SYMBOLS


async def on_bar(bar):
    print(f"[BAR] {bar.symbol} | close={bar.close} | volume={bar.volume} | time={bar.timestamp}")


async def on_trade(trade):
    print(f"[TRADE] {trade.symbol} | price={trade.price} | size={trade.size}")


async def on_quote(quote):
    print(f"[QUOTE] {quote.symbol} | bid={quote.bid_price} | ask={quote.ask_price}")


def run_stream(symbols: list[str] = TRADE_SYMBOLS):
    stream = StockDataStream(ALPACA_API_KEY, ALPACA_SECRET_KEY, feed=DataFeed.IEX)

    stream.subscribe_bars(on_bar, *symbols)
    stream.subscribe_trades(on_trade, *symbols)
    stream.subscribe_quotes(on_quote, *symbols)

    print(f"WebSocket 연결 시작... 종목: {symbols}")
    print("장 마감 중에는 데이터가 들어오지 않습니다.")
    print("Ctrl+C로 종료\n")

    stream.run()


if __name__ == "__main__":
    run_stream()
