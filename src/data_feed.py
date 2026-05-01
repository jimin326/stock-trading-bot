from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from datetime import datetime, timedelta, time
import pandas as pd
import pytz

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, TIMEFRAME

_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
_ET = pytz.timezone("America/New_York")
_now_et = lambda: datetime.now(tz=_ET)

_MARKET_OPEN  = time(9, 30)
_MARKET_CLOSE = time(16, 0)

_TIMEFRAME_MAP = {
    "1Min":  TimeFrame(1, TimeFrameUnit.Minute),
    "5Min":  TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day":  TimeFrame(1, TimeFrameUnit.Day),
}


def get_premarket_hl(symbol: str) -> tuple[float | None, float | None]:
    """당일 프리마켓(4:00~9:30 ET) 고점/저점 반환. 데이터 없으면 (None, None)"""
    now = datetime.now(tz=_ET)
    today_open = now.replace(hour=4, minute=0, second=0, microsecond=0)
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=today_open,
            end=market_open,
            feed=DataFeed.IEX,
            extended_hours=True,
        )
        bars = _client.get_stock_bars(request)
        df = bars.df
        if df.empty:
            return None, None
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        return float(df["high"].max()), float(df["low"].min())
    except Exception:
        return None, None


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

    # UTC → ET 변환 후 정규장(9:30~16:00)만 남김 — TradingView 기준과 동일
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(_ET)
    t = df.index.time
    df = df[(t >= _MARKET_OPEN) & (t <= _MARKET_CLOSE)]

    return df[["open", "high", "low", "close", "volume"]]


if __name__ == "__main__":
    df = get_bars("AAPL", days=5)
    print(df.tail(10))
    print(f"\n인덱스 타임존: {df.index.tzinfo}")
    print(f"첫 봉: {df.index[0]}")
    print(f"마지막 봉: {df.index[-1]}")
