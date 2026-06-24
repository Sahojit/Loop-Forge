import re
import yfinance as yf


def _validate_ticker(ticker: str) -> bool:
    return bool(re.match(r"^[A-Z]{1,6}$", ticker.upper()))


def get_market_data(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not _validate_ticker(ticker):
        return f"Error: invalid ticker symbol '{ticker}'"
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get("currentPrice") or info.get("regularMarketPrice", "N/A")
        market_cap = info.get("marketCap", "N/A")
        pe_ratio = info.get("trailingPE", "N/A")
        volume = info.get("volume", "N/A")
        name = info.get("longName", ticker)
        return (
            f"{name} ({ticker}): Price=${price}, "
            f"MarketCap={market_cap}, P/E={pe_ratio}, Volume={volume}"
        )
    except Exception as e:
        return f"Error fetching data for {ticker}: {type(e).__name__}"
