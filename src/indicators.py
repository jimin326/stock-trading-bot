import pandas as pd
import ta

import src.config as config


def add_indicators(df: pd.DataFrame, ema_period: int | None = None) -> pd.DataFrame:
    df = df.copy()
    period = ema_period if ema_period is not None else config.EMA_PERIOD

    df["ema9"] = ta.trend.EMAIndicator(df["close"], window=period).ema_indicator()
    df["vwap"] = _calc_vwap(df)
    df["vp_empty_above"], df["vp_empty_below"] = _calc_volume_profile(df)

    return df


def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical * df["volume"]

    dates = df.index.normalize() if hasattr(df.index, "normalize") else pd.Series(df.index).dt.normalize()

    vwap = pd.Series(index=df.index, dtype=float)

    for date, idx in df.groupby(df.index.normalize()).groups.items():
        cum_tp_vol = tp_vol.loc[idx].cumsum()
        cum_vol = df["volume"].loc[idx].cumsum()
        vwap.loc[idx] = cum_tp_vol / cum_vol

    return vwap


def _calc_volume_profile(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    import numpy as np

    n = len(df)
    empty_above = pd.Series(False, index=df.index)
    empty_below = pd.Series(False, index=df.index)

    closes  = df["close"].to_numpy()
    volumes = df["volume"].to_numpy()
    lows    = df["low"].to_numpy()
    highs   = df["high"].to_numpy()
    W = config.VOLUME_PROFILE_WINDOW
    B = config.VOLUME_PROFILE_BINS
    check = 5

    for i in range(W, n):
        w_close = closes[i - W: i + 1]
        w_vol   = volumes[i - W: i + 1]
        price_min = lows[i - W: i + 1].min()
        price_max = highs[i - W: i + 1].max()
        price_range = price_max - price_min

        if price_range == 0:
            continue

        # numpy로 한번에 bin 계산
        bins = np.clip(((w_close - price_min) / price_range * B).astype(int), 0, B - 1)
        vol_by_bin = np.bincount(bins, weights=w_vol, minlength=B)

        threshold   = vol_by_bin.mean() * config.VOLUME_EMPTY_RATIO
        current_bin = int(np.clip((closes[i] - price_min) / price_range * B, 0, B - 1))

        above = vol_by_bin[current_bin + 1: current_bin + 1 + check]
        below = vol_by_bin[max(0, current_bin - check): current_bin]

        empty_above.iloc[i] = bool(np.all(above < threshold)) if len(above) > 0 else True
        empty_below.iloc[i] = bool(np.all(below < threshold)) if len(below) > 0 else True

    return empty_above, empty_below


def latest(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


if __name__ == "__main__":
    from src.data_feed import get_bars

    df = get_bars("AAPL", days=30)
    df = add_indicators(df)
    row = latest(df)

    print(f"=== AAPL 최신 지표 ===")
    print(f"EMA9      : {row['ema9']:.2f}")
    print(f"VWAP      : {row['vwap']:.2f}")
    print(f"현재가    : {row['close']:.2f}")
    print(f"위쪽 매물 비어있음: {row['vp_empty_above']}")
    print(f"아래쪽 매물 비어있음: {row['vp_empty_below']}")
