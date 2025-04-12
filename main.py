# Required libraries
import time
import pandas as pd
import csv
import os
import requests
import logging
from datetime import datetime
from binance.um_futures import UMFutures
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from datetime import datetime, timedelta, timezone
from binance.error import ClientError

#load environment variables
from dotenv import load_dotenv
load_dotenv(override=True)

def send_telegram_message(text):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Telegram error: {e}")

def get_yesterday_pnl(api_key, api_secret, testnet=True):
    # Logging setup
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    # Use testnet or live URL
    base_url = 'https://testnet.binancefuture.com' if testnet else 'https://fapi.binance.com'
    
    # Initialize client
    um_futures_client = UMFutures(key=api_key, secret=api_secret, base_url=base_url)

    # Set timezone to UTC+7
    tz = timezone(timedelta(hours=7))
    now_utc7 = datetime.now(tz)

    # Calculate yesterday's time range
    start_of_yesterday = datetime(now_utc7.year, now_utc7.month, now_utc7.day, tzinfo=tz) - timedelta(days=1)
    start_ts = int(start_of_yesterday.timestamp() * 1000)
    start_of_today = datetime(now_utc7.year, now_utc7.month, now_utc7.day, tzinfo=tz)
    end_ts = int(start_of_today.timestamp() * 1000)

    try:
        response = um_futures_client.get_income_history(
            incomeType='REALIZED_PNL',
            startTime=start_ts,
            endTime=end_ts,
            recvWindow=6000
        )

        if response:
            yesterday = (now_utc7 - timedelta(days=1)).strftime('%Y-%m-%d')
            logging.info(f"== YESTERDAY'S REALIZED PNL - {yesterday} ==")
            total_pnl = 0
            trade_details = []
            for entry in response:
                income = float(entry['income'])
                if income == 0:
                    continue

                symbol = entry['symbol']
                time = datetime.fromtimestamp(entry['time'] / 1000).astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
                status = "Profit" if income > 0 else "Loss"
                total_pnl += income

                trade_details.append(f"[{time}] {symbol} | {status}: {income:.2f} USDT")
                logging.info(f"[{time}] {symbol} | {status}: {income:.2f} USDT")

            logging.info(f"\nTotal Realized PnL for Yesterday: {total_pnl:.2f} USDT")
            
            # Prepare the message for Telegram
            # Prepare and send Telegram message
            message_lines = [f"<b>📊 PNL - {yesterday}</b>"]
            for entry in response:
                income = float(entry['income'])
                if income == 0:
                    continue
                symbol = entry['symbol']
                hour_min = datetime.fromtimestamp(entry['time'] / 1000).astimezone(tz).strftime('%H:%M')
                status = "Profit" if income > 0 else "Loss"
                message_lines.append(f"[{hour_min}] <code>{symbol}</code> | {status}: <code>{income:.2f} USDT</code>")
            message_lines.append(f"\n<b>Total:</b> <code>{total_pnl:.2f} USDT</code>")
            message = "\n".join(message_lines)

            send_telegram_message(message)
            return total_pnl
        else:
            logging.info("No Realized PnL records found for yesterday.")
            send_telegram_message("❌ No Realized PnL records found for yesterday.")
            return 0

    except ClientError as error:
        logging.error(
            f"Found error. status: {error.status_code}, "
            f"error code: {error.error_code}, "
            f"error message: {error.error_message}"
        )
        send_telegram_message(f"❌ Error fetching PnL data: {error.error_message}")
        return None

# ==== CONFIG ====
API_KEY = os.getenv("API_KEY") # Fill this in
API_SECRET = os.getenv("API_SECRET")  # Fill this in
TESTNET = True  # Set to False for live trading
INTERVAL = '5m'
QUANTITY_USDT = 1.0  # Capital per trade
RISK_PER_TRADE = 0.5  # SL = $0.5
TP_USDT = 1.0  # TP = $1
LEVERAGE = 20
MAX_TRADES_PER_DAY = 6
TODAY = datetime.now().strftime('%Y-%m-%d')
REPORT_FILENAME = 'Report/daily_report.csv - {}'.format(TODAY)

# ==== INITIALIZE ====
print(f"[START] Starting bot...")
get_yesterday_pnl(API_KEY, API_SECRET, TESTNET)
BASE_URL = 'https://testnet.binancefuture.com' if TESTNET else 'https://fapi.binance.com'
client = UMFutures(key=API_KEY, secret=API_SECRET, base_url=BASE_URL)
trades_today = 0
current_day = time.strftime('%Y-%m-%d')
trade_log = []
send_telegram_message(f"Bot started on {current_day}. Monitoring market...")
print(f"[START] Bot initialized successfully on {current_day}. Monitoring market...")

# ==== FUNCTIONS ====
def get_symbol_precisions():
    info = client.exchange_info()
    precisions = {}
    for s in info['symbols']:
        if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT':
            symbol = s['symbol']
            qty_precision = None
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    qty_precision = abs(round(-1 * (len(str(step_size).split('.')[1].rstrip('0')))))
                    break
            precisions[symbol] = qty_precision
    return precisions

symbol_precisions = get_symbol_precisions()

def get_usdt_pairs():
    return list(symbol_precisions.keys())

def get_klines(symbol, interval, limit=210):
    klines = client.klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp', 'o', 'h', 'l', 'c', 'v', 'close_time', 'quote_asset_volume', 'num_trades', 'taker_buy_base_vol', 'taker_buy_quote_vol', 'ignore'])
    df['c'] = df['c'].astype(float)
    return df

def generate_indicators(df):
    df['EMA20'] = EMAIndicator(df['c'], 20).ema_indicator()
    df['EMA50'] = EMAIndicator(df['c'], 50).ema_indicator()
    df['EMA200'] = EMAIndicator(df['c'], 200).ema_indicator()
    df['RSI'] = RSIIndicator(df['c'], 14).rsi()
    macd = MACD(df['c'], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd.macd()
    df['Signal'] = macd.macd_signal()
    df['Hist'] = macd.macd_diff()
    return df

def get_signal(df):
    latest = df.iloc[-1]
    ema20 = latest['EMA20']
    ema50 = latest['EMA50']
    ema200 = latest['EMA200']
    rsi = latest['RSI']
    macd = latest['MACD']
    signal_line = latest['Signal']
    hist = latest['Hist']

    print(f"  → Indicators | EMA20: {ema20:.2f}, EMA50: {ema50:.2f}, EMA200: {ema200:.2f}, RSI: {rsi:.2f}, MACD: {macd:.4f}, Signal: {signal_line:.4f}, Hist: {hist:.4f}")

    attempts = [
        lambda: (ema20 > ema50 and rsi < 40 and macd > signal_line and hist > 0, 'long', 'Perfect match for LONG'),
        lambda: (ema20 < ema50 and rsi > 60 and macd < signal_line and hist < 0, 'short', 'Perfect match for SHORT'),
        lambda: (ema20 > ema50 and rsi < 50, 'long', 'Close match for LONG'),
        lambda: (ema20 < ema50 and rsi > 50, 'short', 'Close match for SHORT'),
        lambda: (ema20 > ema50 and rsi < 50, 'long', 'Ignoring MACD - LONG'),
        lambda: (ema20 < ema50 and rsi > 50, 'short', 'Ignoring MACD - SHORT'),
        lambda: (ema20 > ema50, 'long', 'Ignoring RSI - LONG'),
        lambda: (ema20 < ema50, 'short', 'Ignoring RSI - SHORT')
    ]

    for i, attempt in enumerate(attempts, start=1):
        print(f"    [ATTEMPT {i}] Evaluating...")
        condition, direction, notes = attempt()
        if condition:
            if direction == 'long' and ema20 > ema200:
                print(f"    [MATCH] {notes} ✅ Confirmed by EMA200")
                return direction, f"[Attempt {i}] {notes} | Confirmed by EMA200"
            elif direction == 'short' and ema20 < ema200:
                print(f"    [MATCH] {notes} ✅ Confirmed by EMA200")
                return direction, f"[Attempt {i}] {notes} | Confirmed by EMA200"
            else:
                print(f"    [SKIP] Direction valid but not aligned with EMA200 trend")
        else:
            print(f"    [FAIL] {notes} not satisfied")
        time.sleep(1)

    return None, None

def place_trade(symbol, signal, entry_price, notes):
    global trades_today
    precision = symbol_precisions.get(symbol, 3)
    raw_qty = (QUANTITY_USDT * LEVERAGE) / entry_price
    qty = round(raw_qty, precision)
    sl_price = entry_price - (RISK_PER_TRADE / qty) if signal == 'long' else entry_price + (RISK_PER_TRADE / qty)
    tp_price = entry_price + (TP_USDT / qty) if signal == 'long' else entry_price - (TP_USDT / qty)
    rr_ratio = round(TP_USDT / RISK_PER_TRADE, 2)

    side = 'BUY' if signal == 'long' else 'SELL'
    opposite = 'SELL' if signal == 'long' else 'BUY'

    client.new_order(symbol=symbol, side=side, type='MARKET', quantity=qty)
    client.new_order(
        symbol=symbol,
        side=opposite,
        type='STOP_MARKET',
        stopPrice=str(round(sl_price, 2)),
        closePosition=True,
        workingType='MARK_PRICE',
        timeInForce='GTC'
    )
    client.new_order(
        symbol=symbol,
        side=opposite,
        type='TAKE_PROFIT_MARKET',
        stopPrice=str(round(tp_price, 2)),
        closePosition=True,
        workingType='MARK_PRICE',
        timeInForce='GTC'
    )

    trades_today += 1
    trade_log.append([
        trades_today, symbol, signal, entry_price, round(sl_price, 2), round(tp_price, 2), qty, rr_ratio, notes
    ])

    print(f"[TRADE] Placed {symbol} | {signal.upper()} | Entry: {entry_price} | SL: {sl_price} | TP: {tp_price} | Qty: {qty} | Precision: {precision} | Trade Count: {trades_today}")
    # 🚀 Send Telegram Alert
    msg = (
        f"📈 <b>TRADE EXECUTED</b>\n"
        f"Pair: <code>{symbol}</code>\n"
        f"Signal: <b>{signal.upper()}</b>\n"
        f"Entry: ${entry_price:.2f}\n"
        f"SL: ${sl_price:.2f}\n"
        f"TP: ${tp_price:.2f}\n"
        f"Qty: {qty}\n"
        f"RR: {rr_ratio}\n"
        f"Notes: {notes}"
    )
    send_telegram_message(msg)


# ==== MAIN LOOP ====
while True:
    try:

        if trades_today >= MAX_TRADES_PER_DAY:
            print("[END] Max trades reached today. Exiting bot.")
            break

        found_signal = False
        usdt_pairs = get_usdt_pairs()
        for symbol in usdt_pairs:
            if trades_today >= MAX_TRADES_PER_DAY:
                break
            try:
                print(f"\n[SCANNING] {symbol}")
                df = get_klines(symbol, INTERVAL)
                df = generate_indicators(df)
                signal, notes = get_signal(df)

                if signal:
                    mark = client.mark_price(symbol=symbol)
                    price = float(mark['markPrice'])
                    place_trade(symbol, signal, price, notes)
                    found_signal = True
                time.sleep(0.5)

            except Exception as e:
                print(f"[ERROR] {symbol}: {e}")

        if not found_signal:
            print("[SUMMARY] No valid pairs found in this cycle.")

    except Exception as e:
        print(f"[FATAL] {e}")

    print("[SLEEP] Waiting 5 minutes before next scan...")
    
print("[END] Bot execution completed.")
send_telegram_message("Bot execution completed.")


