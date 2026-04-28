"""
장 시작 전 또는 장중에 실행해서 오늘 터질 종목을 찾아 반환한다.
조건: 갭상승/하락 + 20일 평균 대비 거래량 급증
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

import src.config as config


@dataclass
class ScanResult:
    symbol: str
    gap_pct: float
    vol_ratio: float   # 오늘 거래량 / 20일 평균 거래량
    price: float
    direction: str     # "up" | "down"

    def __str__(self):
        arrow = "▲" if self.direction == "up" else "▼"
        return (f"{self.symbol:6s} {arrow} 갭 {self.gap_pct:+.1f}%  "
                f"거래량 {self.vol_ratio:.1f}x (20일평균)  ${self.price:.2f}")


def scan_market(
    top_n: int | None = None,
    gap_threshold: float | None = None,
    vol_ratio_min: float | None = None,
) -> list[ScanResult]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockSnapshotRequest, StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed

    top_n         = top_n         or config.SCAN_TOP_N
    gap_threshold = gap_threshold or config.GAP_THRESHOLD
    vol_ratio_min = vol_ratio_min or config.VOL_RATIO_MIN

    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)

    # 1) 스냅샷 — 갭 + 오늘 거래량
    try:
        snap_req  = StockSnapshotRequest(symbol_or_symbols=config.SCAN_UNIVERSE)
        snapshots = client.get_stock_snapshot(snap_req)
    except Exception as e:
        print(f"[scanner] 스냅샷 조회 실패: {e}")
        return []

    # 2) 20일치 일봉 — 평균 거래량 계산
    try:
        bar_req = StockBarsRequest(
            symbol_or_symbols=config.SCAN_UNIVERSE,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=35),  # 35일 치 요청 → 영업일 20일 확보
            feed=DataFeed.IEX,
        )
        bars_dict = client.get_stock_bars(bar_req)
    except Exception as e:
        print(f"[scanner] 일봉 조회 실패: {e}")
        bars_dict = {}

    # 종목별 20일 평균 거래량 (오늘 봉 제외)
    avg_volumes: dict[str, float] = {}
    for sym, bars in bars_dict.data.items():
        full_days = bars[:-1][-20:]  # 오늘 제외, 최근 20영업일
        if full_days:
            avg_volumes[sym] = sum(b.volume for b in full_days) / len(full_days)

    candidates: list[ScanResult] = []
    for symbol, snap in snapshots.items():
        try:
            daily = snap.daily_bar
            prev  = snap.previous_daily_bar
            if not daily or not prev or prev.close == 0:
                continue

            avg_vol = avg_volumes.get(symbol, 0)
            if avg_vol == 0:
                continue

            gap_pct   = (daily.open - prev.close) / prev.close * 100
            vol_ratio = prev.volume / avg_vol  # 어제 거래량 / 20일 평균

            if vol_ratio < 1.0:
                continue

            candidates.append(ScanResult(
                symbol    = symbol,
                gap_pct   = gap_pct,
                vol_ratio = vol_ratio,
                price     = daily.close,
                direction = "up" if gap_pct > 0 else "down",
            ))
        except Exception:
            continue

    candidates.sort(key=lambda x: x.vol_ratio, reverse=True)
    return candidates[:top_n]


if __name__ == "__main__":
    print("=== 오늘의 스캔 결과 ===")
    results = scan_market()
    if results:
        for r in results:
            print(" ", r)
    else:
        print("  조건을 만족하는 종목 없음 (장 마감/프리마켓 중일 수 있음)")
