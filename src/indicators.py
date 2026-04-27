import pandas as pd
import ta

from src.config import (
    EMA_PERIOD,
    VOLUME_PROFILE_WINDOW, VOLUME_PROFILE_BINS, VOLUME_EMPTY_RATIO,
)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ema9"] = ta.trend.EMAIndicator(df["close"], window=EMA_PERIOD).ema_indicator()
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
    n = len(df)
    empty_above = pd.Series(False, index=df.index)
    empty_below = pd.Series(False, index=df.index)

    for i in range(VOLUME_PROFILE_WINDOW, n):
        window = df.iloc[i - VOLUME_PROFILE_WINDOW: i + 1]
        current_price = df["close"].iloc[i]

        price_min = window["low"].min()
        price_max = window["high"].max()
        price_range = price_max - price_min

        if price_range == 0:
            continue

        bin_size = price_range / VOLUME_PROFILE_BINS
        vol_by_bin = [0.0] * VOLUME_PROFILE_BINS

        for _, row in window.iterrows():
            b = min(int((row["close"] - price_min) / bin_size), VOLUME_PROFILE_BINS - 1)
            vol_by_bin[b] += row["volume"]

        avg_vol = sum(vol_by_bin) / VOLUME_PROFILE_BINS
        threshold = avg_vol * VOLUME_EMPTY_RATIO

        current_bin = min(int((current_price - price_min) / bin_size), VOLUME_PROFILE_BINS - 1)

        # 위쪽 인접 5개 구간이 모두 threshold 미만이면 "매물 없음"
        check = 5
        above_bins = vol_by_bin[current_bin + 1: current_bin + 1 + check]
        below_bins = vol_by_bin[max(0, current_bin - check): current_bin]

        empty_above.iloc[i] = all(v < threshold for v in above_bins) if above_bins else True
        empty_below.iloc[i] = all(v < threshold for v in below_bins) if below_bins else True

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
