from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

TRADE_SYMBOLS = ["AAPL", "TSLA", "NVDA", "MSFT"]

TIMEFRAME = "15Min"  # 기본값 (종목별 설정 없을 때 사용)

# 종목별 최적 타임프레임 (optimize.py 실행 후 자동 업데이트)
SYMBOL_TIMEFRAME: dict[str, str] = {
    "AAPL": "5Min",
    "TSLA": "5Min",
    "NVDA": "1Hour",
    "MSFT": "1Hour",
}

# 종목별 최적 EMA 기간 (optimize.py 실행 후 자동 업데이트)
SYMBOL_EMA: dict[str, int] = {
    "AAPL": 21,
    "TSLA": 12,
    "NVDA": 5,
    "MSFT": 5,
}

def get_timeframe(symbol: str) -> str:
    return SYMBOL_TIMEFRAME.get(symbol, TIMEFRAME)

def get_ema_period(symbol: str) -> int:
    return SYMBOL_EMA.get(symbol, EMA_PERIOD)

EMA_PERIOD = 9

VOLUME_PROFILE_WINDOW = 60   # 볼륨 프로파일 계산에 사용할 봉 수
VOLUME_PROFILE_BINS = 20     # 가격대 분할 수
VOLUME_EMPTY_RATIO = 0.4     # 평균 대비 이 비율 미만이면 "매물 없음"으로 판단

EMA_TOUCH_PCT = 0.003        # EMA 터치 인정 범위 (0.3%)
SIDEWAYS_WINDOW = 6          # 횡보 판단에 사용할 최근 봉 수
SIDEWAYS_CROSS_THRESHOLD = 2 # 이 횟수 이상 VWAP 교차 시 횡보로 판단

MAX_POSITION_PCT = 0.1
