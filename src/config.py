from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

TRADE_SYMBOLS = ["AAPL", "TSLA", "NVDA", "MSFT"]

TIMEFRAME = "15Min"

EMA_PERIOD = 9

VOLUME_PROFILE_WINDOW = 60   # 볼륨 프로파일 계산에 사용할 봉 수
VOLUME_PROFILE_BINS = 20     # 가격대 분할 수
VOLUME_EMPTY_RATIO = 0.4     # 평균 대비 이 비율 미만이면 "매물 없음"으로 판단

EMA_TOUCH_PCT = 0.003        # EMA 터치 인정 범위 (0.3%)
SIDEWAYS_WINDOW = 6          # 횡보 판단에 사용할 최근 봉 수
SIDEWAYS_CROSS_THRESHOLD = 2 # 이 횟수 이상 VWAP 교차 시 횡보로 판단

MAX_POSITION_PCT = 0.1
