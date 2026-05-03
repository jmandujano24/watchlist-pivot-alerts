import os
import json
import requests
import pandas as pd

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = "state.json"
TICKERS_FILE = "tickers.txt"


# -------------------------
# UTIL
# -------------------------

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_tickers():
    with open(TICKERS_FILE, "r") as f:
        return [t.strip() for t in f.readlines() if t.strip()]


# -------------------------
# DATA
# -------------------------

def get_price(symbol):
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={API_KEY}"
    r = requests.get(url).json()
    return float(r["price"])


def get_series(symbol, interval, outputsize=60):
    url = (
        f"https://api.twelvedata.com/time_series?"
        f"symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={API_KEY}"
    )
    r = requests.get(url).json()
    return list(reversed(r["values"]))


def ema(series, span):
    closes = [float(x["close"]) for x in series]
    return pd.Series(closes).ewm(span=span).mean().iloc[-1]


# -------------------------
# CORE LOGIC
# -------------------------

MA_PRIORITY = ["WEMA8", "SMA50", "EMA20", "EMA8"]


def detect_ma_cross(prev_price, price, ma_value):
    return prev_price > ma_value and price < ma_value


def get_ma_values(symbol):
    daily = get_series(symbol, "1day", 100)
    weekly = get_series(symbol, "1week", 50)

    return {
        "EMA8": ema(daily, 8),
        "EMA20": ema(daily, 20),
        "SMA50": pd.Series([float(x["close"]) for x in daily]).rolling(50).mean().iloc[-1],
        "WEMA8": ema(weekly, 8)
    }


def get_30m_bars(symbol):
    bars = get_series(symbol, "30min", 5)
    return bars[-3], bars[-2]  # A (closed), B (current forming)


# -------------------------
# MAIN LOOP
# -------------------------

def main():
    tickers = get_tickers()
    state = load_state()

    for t in tickers:
        try:
            price = get_price(t)
            ma = get_ma_values(t)

            prev_price = state.get(t, {}).get("prev_price", price)

            # -------------------------
            # RESET IF ALREADY IN STATE
            # -------------------------
            ticker_state = state.get(t, {
                "watching": False,
                "ma": None,
                "bar_a_high": None,
                "trigger": None,
                "alerted": False,
                "expiry": 0,
                "prev_price": price
            })

            # -------------------------
            # DETECT FRESH CROSS
            # -------------------------
            crossed_ma = None

            for m in MA_PRIORITY:
                if detect_ma_cross(prev_price, price, ma[m]):
                    crossed_ma = m
                    break

            # ACTIVATE WATCH
            if crossed_ma:
                ticker_state["watching"] = True
                ticker_state["ma"] = crossed_ma
                ticker_state["alerted"] = False
                ticker_state["expiry"] = 10  # 10 x 30m bars

                send(f"👀 {t} perdió {crossed_ma}")

            # -------------------------
            # WATCH MODE
            # -------------------------
            if ticker_state["watching"] and not ticker_state["alerted"]:

                bars = get_30m_bars(t)
                bar_a, bar_b = bars

                # set A once
                if not ticker_state["bar_a_high"]:
                    ticker_state["bar_a_high"] = float(bar_a["high"])
                    ticker_state["trigger"] = float(bar_a["high"])

                # PIVOT
                if float(bar_b["high"]) >= ticker_state["bar_a_high"]:
                    send(
                        f"🔔 {t} PIVOT\n"
                        f"MA perdida: {ticker_state['ma']}\n"
                        f"High A: {ticker_state['bar_a_high']}\n"
                        f"Precio: {price}"
                    )
                    ticker_state["alerted"] = True
                    ticker_state["watching"] = False

                ticker_state["expiry"] -= 1

                if ticker_state["expiry"] <= 0:
                    ticker_state["watching"] = False

            # update prev price
            ticker_state["prev_price"] = price
            state[t] = ticker_state

        except Exception as e:
            print(f"{t} error:", e)

    save_state(state)


if __name__ == "__main__":
    main()
