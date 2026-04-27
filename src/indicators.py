import pandas as pd
import ta

from src.config import RSI_PERIOD, MA_SHORT, MA_LONG


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=RSI_PERIOD).rsi()

    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()

    df["ma_short"] = ta.trend.SMAIndicator(df["close"], window=MA_SHORT).sma_indicator()
    df["ma_long"] = ta.trend.SMAIndicator(df["close"], window=MA_LONG).sma_indicator()

    bb = ta.volatility.BollingerBands(df["close"])
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()

    return df


def latest(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


if __name__ == "__main__":
    from src.data_feed import get_bars

    df = get_bars("AAPL", days=30)
    df = add_indicators(df)
    row = latest(df)

    print(f"=== AAPL 최신 지표 ===")
    print(f"RSI       : {row['rsi']:.2f}")
    print(f"MACD      : {row['macd']:.4f}  Signal: {row['macd_signal']:.4f}")
    print(f"MA{MA_SHORT}/{MA_LONG}    : {row['ma_short']:.2f} / {row['ma_long']:.2f}")
    print(f"볼린저밴드: {row['bb_lower']:.2f} ~ {row['bb_upper']:.2f}")
    print(f"현재가    : {row['close']:.2f}")
