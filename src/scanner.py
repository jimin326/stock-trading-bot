"""
장 시작 전 또는 장중에 실행해서 오늘 터질 종목을 찾아 반환한다.
조건: 갭상승/하락 + 거래량 급증
"""
from dataclasses import dataclass

import src.config as config


@dataclass
class ScanResult:
    symbol: str
    gap_pct: float       # 갭 (%)
    vol_ratio: float     # 전일 대비 거래량 배수
    price: float         # 현재가
    direction: str       # "up" | "down"

    def __str__(self):
        arrow = "▲" if self.direction == "up" else "▼"
        return (f"{self.symbol:6s} {arrow} 갭 {self.gap_pct:+.1f}%  "
                f"거래량 {self.vol_ratio:.1f}x  ${self.price:.2f}")


def scan_market(
    top_n: int | None = None,
    gap_threshold: float | None = None,
    vol_ratio_min: float | None = None,
) -> list[ScanResult]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockSnapshotRequest

    top_n         = top_n or config.SCAN_TOP_N
    gap_threshold = gap_threshold or config.GAP_THRESHOLD
    vol_ratio_min = vol_ratio_min or config.VOL_RATIO_MIN

    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)

    # 유니버스 전체 스냅샷 한 번에 조회
    req = StockSnapshotRequest(symbol_or_symbols=config.SCAN_UNIVERSE)
    try:
        snapshots = client.get_stock_snapshot(req)
    except Exception as e:
        print(f"[scanner] 스냅샷 조회 실패: {e}")
        return []

    candidates: list[ScanResult] = []
    for symbol, snap in snapshots.items():
        try:
            daily = snap.daily_bar
            prev  = snap.previous_daily_bar
            if not daily or not prev or prev.close == 0 or prev.volume == 0:
                continue

            gap_pct   = (daily.open - prev.close) / prev.close * 100
            vol_ratio = daily.volume / prev.volume

            if abs(gap_pct) < gap_threshold or vol_ratio < vol_ratio_min:
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

    # 갭 크기 × 거래량 배수로 정렬
    candidates.sort(key=lambda x: abs(x.gap_pct) * x.vol_ratio, reverse=True)
    return candidates[:top_n]


if __name__ == "__main__":
    print("=== 오늘의 스캔 결과 ===")
    results = scan_market()
    if results:
        for r in results:
            print(" ", r)
    else:
        print("  조건을 만족하는 종목 없음 (장 마감/프리마켓 중일 수 있음)")
