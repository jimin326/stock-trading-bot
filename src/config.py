from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
PAPER_TRADING   = os.getenv("PAPER_TRADING", "true").lower() != "false"  # .env에서 PAPER_TRADING=false 설정 시 실전

TRADE_SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD", "META", "MSFT", "AMZN", "GOOGL", "COIN", "PLTR"]  # 고정 감시 종목

TIMEFRAME  = "5Min"
EMA_PERIOD = 8

EMA_TOUCH_PCT      = 0.005  # EMA 눌림목 인정 범위 (0.5%)
PULLBACK_LOWER_PCT = 0.02   # 눌림목 하한선: EMA 기준 -2% 이내까지만 인정
VWAP_TOUCH_PCT     = 0.003  # VWAP 리테스트 인정 범위 (0.3%)

HARD_STOP_PCT    = 0.02   # 하드 손절 -2%
COOLDOWN_BARS    = 5      # 청산 후 재진입 금지 캔들 수 (5캔들 = 25분)
STRICT_EXIT      = True   # True=종가 EMA 이탈 즉시 청산, False=몸통 전체 이탈

# 확신도(1~3)별 포지션 비중
POSITION_SIZE_TIERS = [0.07, 0.10, 0.13]

SIDEWAYS_WINDOW    = 6    # 횡보 판단에 사용할 최근 캔들 수 (5분봉 기준 30분)
SIDEWAYS_CROSSES   = 3    # 해당 구간에서 VWAP 교차 횟수 ≥ 이 값이면 횡보로 판단

# ── 종목 스캐너 설정 ──────────────────────────────────────────
GAP_THRESHOLD     = 1.0   # 갭 기준 (%)
VOL_RATIO_MIN     = 1.5   # 전일 대비 거래량 배수 하한
SCAN_TOP_N        = 2     # 스캐너 추가 종목 수

# 백테스트용 유니버스 (5분봉 데이터 부하 고려해 25종목으로 제한)
BACKTEST_UNIVERSE = [
    "AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOGL","AMD",
    "QCOM","INTC","COIN","PLTR","ARM","SMCI","MSTR",
    "UBER","SHOP","SNAP","PYPL","SOFI","RIVN","NIO","HOOD","SQ","RBLX",
]

# 실시간 스캔 유니버스 — S&P500 대형주 + 고변동성 인기 종목
SCAN_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO",
    "JPM","LLY","V","UNH","XOM","MA","HD","PG","COST","ORCL",
    "ABBV","WMT","BAC","CVX","MRK","KO","NFLX","CRM","AMD",
    "PEP","TMO","ADBE","ACN","DHR","MCD","ABT","CSCO","TXN",
    "QCOM","HON","LOW","ISRG","BKNG","GS","MS","AMAT","SYK",
    "GILD","MDT","DE","NOW","ADI","SBUX","VRTX","MU","LRCX",
    "PANW","KLAC","MELI","REGN","CI","ZTS","CME","UBER","PYPL",
    "COIN","PLTR","SOFI","RIVN","NIO","SHOP","SPOT","SNAP","SQ",
    "RBLX","U","HOOD","F","GM","INTC","ARM","SMCI","MSTR",
]
