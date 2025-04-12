import logging
from binance.um_futures import UMFutures
from binance.lib.utils import config_logging
from binance.error import ClientError

config_logging(logging, logging.DEBUG)

key = '80e9f70fe0cbdea90c829ea5aedfea1658248715b468b150a83abcc829c99bf7' 
secret = '34f7f107aefbea65fa504ae1306d028a81fd718620ecf0b5ec3522939d014f66' 
TESTNET = True  # Set to False for live trading

BASE_URL = 'https://testnet.binancefuture.com' if TESTNET else 'https://fapi.binance.com'
um_futures_client = UMFutures(key=key, secret=secret, base_url=BASE_URL)

symbol = "TROYUSDT"
leverage = 20
usd_to_spend = 1  # Your actual capital to risk

try:
    # Set leverage
    um_futures_client.change_leverage(symbol=symbol, leverage=leverage)

    # Get current price
    ticker = um_futures_client.ticker_price(symbol=symbol)
    entry_price = float(ticker['price'])

    # Calculate quantity (capital * leverage / price)
    quantity = round((usd_to_spend * leverage) / entry_price, 0)

    # Market buy order
    order = um_futures_client.new_order(
        symbol=symbol,
        side="BUY",
        type="MARKET",
        quantity=quantity,
    )
    logging.info("Market order executed: %s", order)

    # Set Take Profit (100%) and Stop Loss (50%)
    take_profit_price = round(entry_price * 2, 6)
    stop_loss_price = round(entry_price * 0.5, 6)

    # Place TAKE_PROFIT_MARKET
    tp_order = um_futures_client.new_order(
        symbol=symbol,
        side="SELL",
        type="TAKE_PROFIT_MARKET",
        stopPrice=take_profit_price,
        closePosition=True,
        timeInForce="GTC",
    )
    logging.info("TP set at: %s", take_profit_price)

    # Place STOP_MARKET (SL)
    sl_order = um_futures_client.new_order(
        symbol=symbol,
        side="SELL",
        type="STOP_MARKET",
        stopPrice=stop_loss_price,
        closePosition=True,
        timeInForce="GTC",
    )
    logging.info("SL set at: %s", stop_loss_price)

except ClientError as error:
    logging.error(
        "Found error. status: {}, error code: {}, error message: {}".format(
            error.status_code, error.error_code, error.error_message
        )
    )