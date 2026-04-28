import pandas as pd
import ta

import src.config as config


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ema9"] = ta.trend.EMAIndicator(df["close"], window=config.EMA_PERIOD).ema_indicator()
    df["vwap"] = _calc_vwap(df)

    return df


def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol  = typical * df["volume"]

    # ET 날짜 기준으로 하루씩 누적 — TradingView와 동일한 세션 리셋
    if hasattr(df.index, "date"):
        dates = pd.Series([t.date() for t in df.index], index=df.index)
    else:
        dates = pd.to_datetime(df.index).date

    vwap = pd.Series(index=df.index, dtype=float)

    for date, idx in df.groupby(dates).groups.items():
        cum_tp_vol = tp_vol.loc[idx].cumsum()
        cum_vol    = df["volume"].loc[idx].cumsum()
        vwap.loc[idx] = cum_tp_vol / cum_vol

    return vwap


def vp_is_clear(df: pd.DataFrame, direction: str, bins: int = 20, clear_ratio: float = 0.3) -> bool:
    """볼륨 프로파일 기준 진입 방향이 뚫려있는지 확인.
    direction: 'up'(롱) or 'down'(숏)
    clear_ratio: 해당 방향 구간 평균 거래량이 최대 거래량의 이 비율 이하이면 '뚫려있다'고 판단
    """
    price_min = df["low"].min()
    price_max = df["high"].max()
    if price_max == price_min:
        return True

    bin_size = (price_max - price_min) / bins
    current  = df["close"].iloc[-1]

    vp = []
    for b in range(bins):
        lo  = price_min + b * bin_size
        hi  = lo + bin_size
        vol = df.loc[(df["close"] >= lo) & (df["close"] < hi), "volume"].sum()
        vp.append(((lo + hi) / 2, vol))

    max_vol = max(v for _, v in vp) or 1

    if direction == "up":
        target = [v for p, v in vp if p > current]
    else:
        target = [v for p, v in vp if p < current]

    if not target:
        return True
    return (sum(target) / len(target)) < max_vol * clear_ratio


def latest(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


if __name__ == "__main__":
    from src.data_feed import get_bars

    df = get_bars("AAPL", days=30)
    df = add_indicators(df)
    row = latest(df)

    print(f"=== AAPL 최신 지표 ===")
    print(f"EMA9   : {row['ema9']:.2f}")
    print(f"VWAP   : {row['vwap']:.2f}")
    print(f"현재가 : {row['close']:.2f}")
