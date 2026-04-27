from dotenv import load_dotenv
import os

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

TRADE_SYMBOLS = ["AAPL", "TSLA", "NVDA", "MSFT"]

TIMEFRAME = "5Min"

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

MA_SHORT = 9
MA_LONG = 21

STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04
MAX_POSITION_PCT = 0.1
