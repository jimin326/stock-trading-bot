from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from datetime import datetime, timedelta
import pandas as pd

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, TIMEFRAME

_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

_TIMEFRAME_MAP = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}


def get_bars(symbol: str, days: int = 30, timeframe: str = TIMEFRAME) -> pd.DataFrame:
    tf = _TIMEFRAME_MAP.get(timeframe, TimeFrame(5, TimeFrameUnit.Minute))
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=datetime.now() - timedelta(days=days),
        end=datetime.now(),
        feed=DataFeed.IEX,
    )
    bars = _client.get_stock_bars(request)
    df = bars.df

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")

    df.index = pd.to_datetime(df.index, utc=True)
    return df[["open", "high", "low", "close", "volume"]]


if __name__ == "__main__":
    df = get_bars("AAPL", days=5)
    print(df.tail(10))
