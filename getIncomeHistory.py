import logging
from datetime import datetime, timedelta, timezone
from binance.um_futures import UMFutures
from binance.lib.utils import config_logging
from binance.error import ClientError

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(message)s')

# This is just a test, you can enter your own API key and secret Testnet
API_KEY = ''
API_SECRET = ''
TESTNET = True  # Set to False for live trading

# Use testnet or live URL
BASE_URL = 'https://testnet.binancefuture.com' if TESTNET else 'https://fapi.binance.com'

# Initialize client
um_futures_client = UMFutures(key=API_KEY, secret=API_SECRET, base_url=BASE_URL)

# Set timezone to UTC+7 (e.g., Bangkok, Jakarta)
timezone_offset = timedelta(hours=7)
tz = timezone(timezone_offset)

# Get current time in UTC+7 and calculate timestamps for yesterday
now_utc7 = datetime.now(tz)

# Calculate the start of yesterday (midnight of the previous day in UTC+7)
start_of_yesterday = datetime(now_utc7.year, now_utc7.month, now_utc7.day, tzinfo=tz) - timedelta(days=1)
start_ts = int(start_of_yesterday.timestamp() * 1000)  # Convert to milliseconds

# Calculate the end of yesterday (midnight of today in UTC+7)
start_of_today = datetime(now_utc7.year, now_utc7.month, now_utc7.day, tzinfo=tz)
end_ts = int(start_of_today.timestamp() * 1000)  # Convert to milliseconds

try:
    # Fetch income history for yesterday
    response = um_futures_client.get_income_history(
        incomeType='REALIZED_PNL',
        startTime=start_ts,
        endTime=end_ts,
        recvWindow=6000
    )

    # Filter and log yesterday's REALIZED_PNL
    if response:
        yesterday = (now_utc7 - timedelta(days=1)).strftime('%Y-%m-%d')
        logging.info(f"== YESTERDAY'S REALIZED PNL - {yesterday} ==")
        total_pnl = 0
        for entry in response:
            income = float(entry['income'])
            if income == 0:
                continue  # Skip zero profits/losses

            symbol = entry['symbol']
            time = datetime.fromtimestamp(entry['time'] / 1000).astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
            status = "Profit" if income > 0 else "Loss"
            total_pnl += income

            logging.info(f"[{time}] {symbol} | {status}: {income:.2f} USDT")

        logging.info(f"\nTotal Realized PnL for Yesterday: {total_pnl:.2f} USDT")
    else:
        logging.info("No Realized PnL records found for yesterday.")

except ClientError as error:
    logging.error(
        f"Found error. status: {error.status_code}, "
        f"error code: {error.error_code}, "
        f"error message: {error.error_message}"
    )