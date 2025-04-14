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


# ==== External Function ====
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
TESTNET = os.getenv("TESTNET", 'False').lower() in ('true', '1', 't')
INTERVAL = '5m'
QUANTITY_USDT = float(os.getenv("QUANTITY_USDT", 1))  # Convert to float
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", 0.5))  # Convert to float
TP_USDT = float(os.getenv("TP_USDT", 0.5))  # Convert to float
LEVERAGE = float(os.getenv("LEVERAGE", 20))  # Convert to float
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", 6))  # Convert to int
TODAY = datetime.now().strftime('%Y-%m-%d')


# ==== INITIALIZE ====
print(f"[START] Starting bot...")
get_yesterday_pnl(API_KEY, API_SECRET, TESTNET)
BASE_URL = 'https://testnet.binancefuture.com' if TESTNET else 'https://fapi.binance.com'
client = UMFutures(key=API_KEY, secret=API_SECRET, base_url=BASE_URL)
trades_today = max(0, min(0, MAX_TRADES_PER_DAY))
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
            # Skip known problematic pairs
            if any(x in symbol for x in ['BTCDOM', 'DEFI']):
                continue
                
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
    # Get 24hr ticker data for all pairs
    tickers = client.ticker_24hr_price_change()
    
    valid_pairs = []
    for ticker in tickers:
        symbol = ticker['symbol']
        if symbol in symbol_precisions:
            volume = float(ticker['volume']) * float(ticker['lastPrice'])  # Daily volume in USDT
            price_change = abs(float(ticker['priceChangePercent']))
            
            # Filter conditions:
            # 1. Minimum daily volume of 1M USDT
            # 2. Price change within reasonable range (1-15%)
            # 3. Not in excluded symbols list
            if (volume > 1_000_000 and 
                1 < price_change < 15 and 
                symbol not in excluded_symbols):
                valid_pairs.append(symbol)
    
    # Sort valid pairs by volume, from highest to lowest
    tickers = {t['symbol']: float(t['volume']) * float(t['lastPrice']) for t in tickers}
    valid_pairs.sort(key=lambda x: tickers[x], reverse=True)
    return valid_pairs


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
        lambda: (ema20 > ema50 and rsi < 40 and macd > signal_line and hist > 0, 'long', 'Perfect match for LONG', 100),
        lambda: (ema20 < ema50 and rsi > 60 and macd < signal_line and hist < 0, 'short', 'Perfect match for SHORT', 100),
        lambda: (ema20 > ema50 and rsi < 50, 'long', 'Close match for LONG', 80),
        lambda: (ema20 < ema50 and rsi > 50, 'short', 'Close match for SHORT', 80),
        lambda: (ema20 > ema50 and rsi < 50, 'long', 'Ignoring MACD - LONG', 60),
        lambda: (ema20 < ema50 and rsi > 50, 'short', 'Ignoring MACD - SHORT', 60),
        lambda: (ema20 > ema50, 'long', 'Ignoring RSI - LONG', 40),
        lambda: (ema20 < ema50, 'short', 'Ignoring RSI - SHORT', 40)
    ]

    for i, attempt in enumerate(attempts, start=1):
        print(f"    [ATTEMPT {i}] Evaluating...")
        condition, direction, notes, score = attempt()
        if condition:
            if direction == 'long' and ema20 > ema200:
                print(f"    [MATCH] {notes} ✅ Confirmed by EMA200")
                return direction, f"[Attempt {i}] {notes} | Confirmed by EMA200", score
            elif direction == 'short' and ema20 < ema200:
                print(f"    [MATCH] {notes} ✅ Confirmed by EMA200")
                return direction, f"[Attempt {i}] {notes} | Confirmed by EMA200", score
            else:
                print(f"    [SKIP] Direction valid but not aligned with EMA200 trend")
        else:
            print(f"    [FAIL] {notes} not satisfied")
        time.sleep(0)  # Sleep to avoid rate limits

    return None, None, 0

def calculate_order_quantity(symbol, entry_price, leverage, symbol_precisions, usdt_amount):
    try:
        # Ensure price and leverage are valid
        if entry_price <= 0 or leverage <= 0:
            raise ValueError("Invalid entry price or leverage")

        try:
            precision = symbol_precisions.get(symbol, 3)
            
            # Fetch minimum notional value for the symbol
            exchange_info = client.exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            min_notional = float(next(f['notional'] for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'))
            
            # Calculate quantity with minimum notional check
            raw_qty = (usdt_amount * leverage) / entry_price
            if (raw_qty * entry_price) < min_notional:
                print(f"[SKIP] Order size too small for {symbol}")
                return 0, False
                
            qty = round(raw_qty, precision)
            
            # Validate final quantity
            if qty <= 0:
                return 0, False
                
            return qty, True
        except Exception as e:
            print(f"Error calculating order quantity for {symbol}: {e}")
            excluded_symbols.append(symbol)
            print(f"[REMOVE] Excluding {symbol} from potential pairs due to errors.")
            return 0, False
    except Exception as e:
        print(f"Error calculating order quantity for {symbol}: {e}")
        # Exclude symbols after errors
        excluded_symbols.append(symbol)
        print(f"[REMOVE] Excluding {symbol} from potential pairs due to errors.")
        return 0, False
    
def apply_buffer(symbol, entry_price, sl_price, tp_price, signal, buffer_percentage=0.01):
    try:
        # Ensure entry_price, sl_price, and tp_price are numeric
        entry_price = float(entry_price)
        sl_price = float(sl_price)
        tp_price = float(tp_price)

        # Fetch PERCENT_PRICE filter for the symbol
        info = client.exchange_info()
        percent_price_filter = next(
            (f for f in info['symbols'] if f['symbol'] == symbol), None
        )
        if not percent_price_filter:
            print(f"[ERROR] Could not fetch PERCENT_PRICE filter for {symbol}")
            return sl_price, tp_price  # Return original prices if filter is unavailable

        # Extract multiplierDown and multiplierUp
        for f in percent_price_filter['filters']:
            if f['filterType'] == 'PERCENT_PRICE':
                multiplier_down = float(f['multiplierDown'])
                multiplier_up = float(f['multiplierUp'])
                break

        # Calculate dynamic buffer based on PERCENT_PRICE filter
        min_allowed_price = entry_price * multiplier_down
        max_allowed_price = entry_price * multiplier_up
        buffer = buffer_percentage * entry_price  # Default buffer (1% of entry price)

        # Adjust stop-loss and take-profit prices with buffer
        if signal == 'long':
            sl_price = max(sl_price, min_allowed_price)  # Ensure SL is above min allowed price
            sl_price = min(sl_price, entry_price - buffer)  # Ensure SL is below entry price by buffer
            tp_price = min(tp_price, max_allowed_price)  # Ensure TP is below max allowed price
            tp_price = max(tp_price, entry_price + buffer)  # Ensure TP is above entry price by buffer
        else:  # signal == 'short'
            sl_price = min(sl_price, max_allowed_price)  # Ensure SL is below max allowed price
            sl_price = max(sl_price, entry_price + buffer)  # Ensure SL is above entry price by buffer
            tp_price = max(tp_price, min_allowed_price)  # Ensure TP is above min allowed price
            tp_price = min(tp_price, entry_price - buffer)  # Ensure TP is below entry price by buffer

        return sl_price, tp_price
    except ValueError as e:
        print(f"[ERROR] Invalid numeric value for {symbol}: {e}")
        excluded_symbols.append(symbol)  # Exclude invalid symbol
        return sl_price, tp_price  # Return original prices in case of error
    except Exception as e:
        print(f"[ERROR] Failed to apply buffer for {symbol}: {e}")
        excluded_symbols.append(symbol)  # Exclude invalid symbol
        return sl_price, tp_price

def validate_prices(symbol, entry_price, qty, signal):
    try:
        precision = symbol_precisions.get(symbol, 3)
        
        # Get minimum price movement
        exchange_info = client.exchange_info()
        symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
        tick_size = float(next(f['tickSize'] for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'))
        
        # Calculate stop-loss and take-profit with minimum distance
        min_distance = tick_size * 10  # Minimum 10 ticks distance
        
        if signal == 'long':
            sl_price = max(entry_price * 0.99, entry_price - (RISK_PER_TRADE / qty))  # Maximum 1% loss
            tp_price = entry_price * 1.02  # Minimum 2% gain
        else:
            sl_price = min(entry_price * 1.01, entry_price + (RISK_PER_TRADE / qty))
            tp_price = entry_price * 0.98
            
        # Round prices to valid tick size
        sl_price = round(sl_price / tick_size) * tick_size
        tp_price = round(tp_price / tick_size) * tick_size
        
        # Additional validation
        if sl_price <= 0 or tp_price <= 0:
            return False
            
        return True
    except Exception as e:
        print(f"[ERROR] Price validation failed for {symbol}: {e}")
        return False


def place_trade(symbol, signal, entry_price, qty, notes):
    global trades_today
    precision = symbol_precisions.get(symbol, 3)
    orderId = 0

    # Calculate stop-loss and take-profit prices
    sl_price = entry_price - (RISK_PER_TRADE / qty) if signal == 'long' else entry_price + (RISK_PER_TRADE / qty)
    tp_price = entry_price + (TP_USDT / qty) if signal == 'long' else entry_price - (TP_USDT / qty)

    # Apply buffer to stop-loss and take-profit prices
    sl_price, tp_price = apply_buffer(symbol, entry_price, sl_price, tp_price, signal)

    # Validate stop-loss and take-profit prices not less than or equal to zero
    if sl_price <= 0 or tp_price <= 0:
        print(f"[ERROR] Invalid stop-loss or take-profit price for {symbol}: SL={sl_price}, TP={tp_price}")
        excluded_symbols.append(symbol)  # Exclude invalid symbol
        return False

    # Revalidate prices
    if not validate_prices(symbol, entry_price, qty, signal):
        print(f"[ERROR] Revalidation failed for {symbol}. Excluding from potential pairs.")
        excluded_symbols.append(symbol)  # Add to excluded symbols
        return False  # Trade is invalid

    rr_ratio = round(TP_USDT / RISK_PER_TRADE, 2)
    side = 'BUY' if signal == 'long' else 'SELL'
    opposite = 'SELL' if signal == 'long' else 'BUY'

    sl_price = round(sl_price, precision)
    tp_price = round(tp_price, precision)
    qty = round(qty, precision)

    testPassed = 0

    if qty:
        try:
            # Simulate market order
            try:
                client.new_order_test(
                    symbol=symbol,
                    side=side,
                    type='MARKET',
                    quantity=qty
                )
                testPassed += 1
            except ClientError as e:
                print(f"[ERROR] Failed to validate market order for {symbol}: {e.error_message}")
                send_telegram_message(f"❌ Failed to validate market order for {symbol}: {e.error_message}")
                excluded_symbols.append(symbol)  # Add to excluded symbols
                return False  # Skip trade if market order simulation fails

            # Simulate stop-loss order
            try:
                client.new_order_test(
                    symbol=symbol,
                    side=opposite,
                    type='STOP_MARKET',
                    stopPrice=str(round(sl_price, precision)),
                    closePosition=True,
                    workingType='MARK_PRICE',
                    timeInForce='GTC'
                )
                testPassed += 1
            except ClientError as e:
                print(f"[ERROR] Failed to validate stop-loss order for {symbol}: {e.error_message}")
                send_telegram_message(f"❌ Failed to validate stop-loss order for {symbol}: {e.error_message}")
                excluded_symbols.append(symbol)  # Add to excluded symbols
                return False  # Skip trade if stop-loss order simulation fails

            # Simulate take-profit order
            try:
                client.new_order_test(
                    symbol=symbol,
                    side=opposite,
                    type='TAKE_PROFIT_MARKET',
                    stopPrice=str(round(tp_price, precision)),
                    closePosition=True,
                    workingType='MARK_PRICE',
                    timeInForce='GTC'
                )
                testPassed += 1
            except ClientError as e:
                print(f"[ERROR] Failed to validate take-profit order for {symbol}: {e.error_message}")
                send_telegram_message(f"❌ Failed to validate take-profit order for {symbol}: {e.error_message}")
                excluded_symbols.append(symbol)  # Add to excluded symbols
                return False  # Skip trade if take-profit order simulation fails

            print(f"[TEST] All simulations passed for {symbol}. Proceeding with real orders.")
            # All simulations passed, proceed with real orders
            if testPassed == 3:
                try:
                    # Recheck current price before placing real orders
                    current_mark = client.mark_price(symbol=symbol)
                    current_price = float(current_mark['markPrice'])
                    
                    # Check if price hasn't moved significantly (e.g., 0.5%)
                    price_diff_percent = abs(current_price - entry_price) / entry_price * 100
                    if price_diff_percent > 0.5:  # 0.5% threshold
                        print(f"[WARNING] Price moved significantly for {symbol}. Test: {entry_price}, Current: {current_price}")
                        return False
                        
                    # Place real orders in a transaction-like manner
                    try:
                        response = client.new_order(symbol=symbol, side=side, type='MARKET', quantity=qty)
                        orderId = int(response['orderId'])
                        print(f"[INFO] Market order placed for {symbol} with orderId: {orderId}")
                        current_mark = client.mark_price(symbol=symbol)
                        actual_entry = float(current_mark['markPrice'])
                        entry_successful = True
                        print(f"[INFO] Market order executed for {symbol} at {actual_entry}")
                    except ClientError as e:
                        if "executed" in str(e.error_message).lower():
                            print(f"[INFO] Order already executed for {symbol} (Market)")
                            actual_entry = current_price
                            entry_successful = True
                        else:
                            print(f"[ERROR] Real order failed for {symbol}: {e.error_message}")
                            send_telegram_message(f"❌ Real order failed for {symbol}: {e.error_message}")
                            excluded_symbols.append(symbol)
                            return False

                    if entry_successful:
                        # Recalculate SL/TP based on actual fill price
                        sl_price, tp_price = apply_buffer(symbol, actual_entry, sl_price, tp_price, signal)
                        
                        # Place SL order
                        print(f"[INFO] Stop-Loss order placed for {symbol} at {sl_price}")
                        try:
                            client.new_order(
                                symbol=symbol,
                                side=opposite,
                                type='STOP_MARKET',
                                stopPrice=str(round(sl_price, precision)),
                                closePosition=True,
                                workingType='MARK_PRICE',
                                timeInForce='GTC'
                            )
                        except ClientError as e:
                            # Cancel the market order if SL fails
                            client.new_order(
                                    symbol=symbol,
                                    side=opposite,
                                    type='MARKET',
                                    reduceOnly=True,  # This ensures the order only reduces/closes position
                                    quantity=qty
                            )
                            print(f"[INFO] Order CANCELED for {symbol}")

                            if "already exists" in str(e.error_message).lower():
                                print(f"[INFO] Stop-Loss order already exists for {symbol}")
                            else:
                                print(f"[ERROR] Failed to place Stop-Loss order for {symbol}: {e.error_message}")
                                raise e

                        # Place TP order
                        try:
                            print(f"[INFO] Take-Profit order placed for {symbol} at {tp_price}")
                            client.new_order(
                                symbol=symbol,
                                side=opposite,
                                type='TAKE_PROFIT_MARKET',
                                stopPrice=str(round(tp_price, precision)),
                                closePosition=True,
                                workingType='MARK_PRICE',
                                timeInForce='GTC'
                            )
                        except ClientError as e:
                            # Cancel the market order if TP fails
                            client.new_order(
                                    symbol=symbol,
                                    side=opposite,
                                    type='MARKET',
                                    reduceOnly=True,  # This ensures the order only reduces/closes position
                                    quantity=qty
                            )
                            print(f"[INFO] Order CANCELED for {symbol}")
                            
                            if "already exists" in str(e.error_message).lower():
                                print(f"[INFO] Take-Profit order already exists for {symbol}")
                            else:
                                print(f"[ERROR] Failed to place Take-Profit order for {symbol}: {e.error_message}")
                                raise e

                        trades_today += 1
                        trade_log.append([
                            trades_today, symbol, signal, actual_entry, round(sl_price, precision), 
                            round(tp_price, precision), qty, rr_ratio, notes
                        ])
                        
                        print(f"[TRADE] Placed {symbol} | {signal.upper()} | Entry: {actual_entry} | SL: {sl_price} | TP: {tp_price} | Qty: {qty}")
                        msg = (
                            f"📈 <b>TRADE EXECUTED</b>\n"
                            f"Pair: <code>{symbol}</code>\n"
                            f"Signal: <b>{signal.upper()}</b>\n"
                            f"Entry: ${actual_entry:.2f}\n"
                            f"SL: ${sl_price:.2f}\n"
                            f"TP: ${tp_price:.2f}\n"
                            f"Qty: {qty}\n"
                            f"RR: {rr_ratio}\n"
                            f"Notes: {notes}"
                        )
                        send_telegram_message(msg)
                        return True
                    
                except ClientError as e:
                    # Cancel the market order if any error occurs      
                    print(f"[ERROR] Real order failed for {symbol}: {e.error_message}")
                    client.new_order(
                        symbol=symbol,
                        side=opposite,
                        type='MARKET',
                        reduceOnly=True,  # This ensures the order only reduces/closes position
                        quantity=qty
                        )
                    trades_today -= 1
                    print(f"[INFO] Order CANCELED for {symbol}")

                    if "executed" not in str(e.error_message).lower():
                        excluded_symbols.append(symbol)
                    return False
            else:
                # Cancel the market order if any error occurs
                print(f"[ERROR] Test failed for {symbol}. Not placing real trade.")
                send_telegram_message(f"❌ Test failed for {symbol}. Not placing real trade.")
                excluded_symbols.append(symbol)
                return False  # Skip trade if test failed
        except ClientError as e:
            # Cancel the market order if any error occurs
            print(f"[ERROR] Trade Error for {symbol}: {e.error_message}")
            send_telegram_message(f"❌ Trade Error for {symbol}: {e.error_message}")
            excluded_symbols.append(symbol)  # Add to excluded symbols
            return False  # Trade is invalid
    else:
        # Cancel the market order if any error occurs
        error_msg = f"Invalid quantity calculated for {symbol}: {qty}"
        print(f"[ERROR] Trade Error for  {error_msg}")
        send_telegram_message(f"❌ Trade Error: {error_msg}")
        excluded_symbols.append(symbol)  # Add to excluded symbols
        return False  # Raise an error for invalid quantity

potential_pair = [] #  List to track potential pairs
top_signals = [] # List to track top signals
excluded_symbols = [] # List to track excluded symbols


# ==== MAIN LOOP ====
while True:
    try:
        if trades_today >= MAX_TRADES_PER_DAY:
            print("[END] Max trades reached today. Exiting bot.")
            break

        found_signal = False

        # === SCANNING PHASE ===
        if not potential_pair:  # Only scan if potential_pair is empty
            print("[START] Scanning for signals...")
            usdt_pairs = get_usdt_pairs()
            for symbol in usdt_pairs:
                if symbol in excluded_symbols:
                    print(f"[SKIP] {symbol} is excluded due to previous errors or successful trades.")
                    continue

                if trades_today >= MAX_TRADES_PER_DAY:
                    print("[LIMIT] Max trades reached. Stopping further trades.")
                    break
                try:
                    print(f"\n[SCANNING] {symbol}")
                    df = get_klines(symbol, INTERVAL)
                    df = generate_indicators(df)
                    signal, notes, score = get_signal(df)

                    if signal:
                        mark = client.mark_price(symbol=symbol)
                        price = float(mark['markPrice'])
                        qty, valid_qty = calculate_order_quantity(symbol, price, LEVERAGE, symbol_precisions, QUANTITY_USDT)

                        if valid_qty:
                            # Validate stop-loss and take-profit prices
                            if not validate_prices(symbol, price, qty, signal):
                                print(f"[SKIP] Invalid prices for {symbol}")
                                excluded_symbols.append(symbol)  # Exclude invalid symbol
                                continue

                            print(f"[SIGNAL FOUND] {symbol} | Signal: {signal} | Price: {price} | Score: {score} | Notes: {notes} | Qty: {qty}")
                            potential_pair.append({
                                'symbol': symbol,
                                'signal': signal,
                                'price': price,
                                'notes': notes,
                                'score': score,
                                'qty': qty
                            })
                        else:
                            print(f"[SKIP] Invalid quantity for {symbol} | Signal: {signal} | Price: {price}")
                            excluded_symbols.append(symbol)  # Exclude invalid symbol
                except Exception as e:
                    print(f"[ERROR] {symbol}: {e}")
                    excluded_symbols.append(symbol)  # Exclude symbol that caused an error

        # === TRADING PHASE ===
        if potential_pair:
            print("[START] Processing top signals...")
            # Filter out excluded symbols from potential_pair
            potential_pair = [pair for pair in potential_pair if pair['symbol'] not in excluded_symbols]
            top_signals = sorted(potential_pair, key=lambda x: x['score'], reverse=True)[:6]

            for signal_data in top_signals[:]:  # Use a copy of the list to safely modify it
                if trades_today >= MAX_TRADES_PER_DAY:
                    print("[LIMIT] Max trades reached. Stopping further trades.")
                    break

                valid_trade = place_trade(
                    signal_data['symbol'],
                    signal_data['signal'],
                    signal_data['price'],
                    signal_data["qty"],
                    signal_data['notes']
                )
                if not valid_trade:
                    print(f"[REMOVE] Excluding {signal_data['symbol']} from potential pairs.")
                    potential_pair.remove(signal_data)  # Remove invalid trade from potential_pair
                    excluded_symbols.append(signal_data['symbol'])  # Exclude invalid symbol
                else:
                    print(f"[SUCCESS] Excluding {signal_data['symbol']} after successful trade.")
                    excluded_symbols.append(signal_data['symbol'])  # Exclude successfully traded symbol
                    time.sleep(5)  # Delay between trades
                    found_signal = True

        if not found_signal:
            print("[SUMMARY] No valid pairs found or trades placed in this cycle.")

        # If there are still potential pairs left, skip rescanning
        if potential_pair:
            print("[INFO] Reusing remaining potential pairs for the next cycle.")
            continue

    except Exception as e:
        print(f"[FATAL] {e}")

    print("[FINISH] Cycle completed.")
    break

print("[END] Bot execution completed.")
send_telegram_message("Bot execution completed.")

if top_signals:
    message_lines = ["\n Final Top Signals"]
    for i, s in enumerate(top_signals, 1):
        message_lines.append(f"  {i}. {s['symbol']} | Signal: {s['signal']} | Price: {s['price']} | Score: {s['score']} | Notes: {s['notes']}")

    final_message = "\n".join(message_lines)
    print(final_message)
else:
    print("[NO TOP SIGNALS] No top signals found at the end of the bot execution.")

# Send final top signals to Telegram
if top_signals:
    # Prepare the final top signals message
    message_lines = ["<b>📊 Final Top Signals</b>"]
    for i, s in enumerate(top_signals, 1):
        message_lines.append(
            f"| {i}. <code>{s['symbol']}</code> | Signal: <b>{s['signal'].upper()}</b> | "
        )
    final_message = "\n".join(message_lines)

    # Send the message via Telegram
    send_telegram_message(final_message)
else:
    send_telegram_message("❌ No top signals found at the end of the bot execution.")

if trade_log:
    message_lines = ["\n Final Trade Log"]
    for i, trade in enumerate(trade_log, 1):
        trade_num, symbol, signal, entry, sl, tp, qty, rr, notes = trade
        message_lines.append(f"  {i}. {symbol} | Signal: {signal} | Entry: {entry} | SL: {sl} | TP: {tp} | RR: {rr} | Notes: {notes}")

    final_message = "\n".join(message_lines)
    print(final_message)
else:
    print("[NO TRADES] No trades were executed during bot execution.")

if trade_log:
    # Prepare simple trade log message
    message_lines = ["<b>📊 Trade Summary</b>"]
    for i, trade in enumerate(trade_log, 1):
        _, symbol, signal, *_ = trade
        message_lines.append(f"{i}. <code>{symbol}</code> | <b>{signal.upper()}</b>")
    final_message = "\n".join(message_lines)

    # Send the message via Telegram 
    send_telegram_message(final_message)
else:
    send_telegram_message("❌ No trades executed")