from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

TRADE_SYMBOLS = ["AAPL", "TSLA", "NVDA", "MSFT"]  # 스캐너 없을 때 기본 대상

TIMEFRAME  = "5Min"
EMA_PERIOD = 9

VOLUME_PROFILE_WINDOW = 60
VOLUME_PROFILE_BINS   = 20
VOLUME_EMPTY_RATIO    = 0.4

SIDEWAYS_WINDOW          = 6
SIDEWAYS_CROSS_THRESHOLD = 3

MAX_POSITION_PCT = 0.1

# ── 종목 스캐너 설정 ──────────────────────────────────────────
GAP_THRESHOLD     = 2.0   # 갭 기준 (%)
VOL_RATIO_MIN     = 1.5   # 전일 대비 거래량 배수 하한
SCAN_TOP_N        = 5     # 최종 선정 종목 수

# 스캔 유니버스 — S&P500 대형주 + 고변동성 인기 종목
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
