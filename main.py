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
        return [x.strip() for x in f.readlines() if x.strip()]


# -------------------------
# DATA
# -------------------------

def get_price(symbol):
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={API_KEY}"
    return float(requests.get(url).json()["price"])


def get_series(symbol, interval, size=60):
    url = (
        f"https://api.twelvedata.com/time_series?"
        f"symbol={symbol}&interval={interval}&outputsize={size}&apikey={API_KEY}"
    )
    r = requests.get(url).json()
    return list(reversed(r["values"]))


def ema(values, span):
    closes = [float(x["close"]) for x in values]
    return pd.Series(closes).ewm(span=span).mean().iloc[-1]


def sma(values, period):
    closes = [float(x["close"]) for x in values]
    return pd.Series(closes).rolling(period).mean().iloc[-1]


# -------------------------
# QUALITY SCORE
# -------------------------

def quality_score(vb, vsma, ha, hb, ca, cb, ma):
    score = 0

    # volume
    vr = vb / vsma if vsma else 0
    if vr > 1.5:
        score += 40
    elif vr > 1:
        score += 25
    else:
        score += 10

    # breakout strength
    strength = (hb - ha) / ha
    if strength > 0.008:
        score += 30
    elif strength > 0.003:
        score += 15
    else:
        score += 5

    # momentum
    if cb > ca:
        score += 20

    # MA context
    if ma == "WEMA8":
        score += 10
    elif ma == "SMA50":
        score += 7
    elif ma == "EMA20":
        score += 5
    else:
        score += 3

    return score


MA_PRIORITY = ["WEMA8", "SMA50", "EMA20", "EMA8"]


def detect_cross(prev, curr, ma):
    return prev > ma and curr < ma


# -------------------------
# CORE
# -------------------------

def main():
    tickers = get_tickers()
    state = load_state()

    for t in tickers:
        try:
            price = get_price(t)

            daily = get_series(t, "1day", 100)
            weekly = get_series(t, "1week", 50)
            bars30 = get_series(t, "30min", 20)

            ma = {
                "EMA8": ema(daily, 8),
                "EMA20": ema(daily, 20),
                "SMA50": sma(daily, 50),
                "WEMA8": ema(weekly, 8)
            }

            prev = state.get(t, {}).get("prev", price)

            st = state.get(t, {
                "watching": False,
                "ma": None,
                "a_high": None,
                "alerted": False,
                "expiry": 10,
                "prev": price
            })

            # -------------------------
            # CROSS DETECTION
            # -------------------------
            crossed = None
            for m in MA_PRIORITY:
                if detect_cross(prev, price, ma[m]):
                    crossed = m
                    break

            if crossed:
                st["watching"] = True
                st["ma"] = crossed
                st["alerted"] = False
                st["expiry"] = 10
                st["a_high"] = None

                send(f"👀 {t} perdió {crossed}")

            # -------------------------
            # WATCH MODE
            # -------------------------
            if st["watching"] and not st["alerted"]:

                bar_a, bar_b = bars30[-2], bars30[-1]

                if not st["a_high"]:
                    st["a_high"] = float(bar_a["high"])
                    st["a_close"] = float(bar_a["close"])

                hb = float(bar_b["high"])
                cb = float(bar_b["close"])

                if hb >= st["a_high"]:

                    # volume
                    vols = [float(x.get("volume", 0)) for x in bars30[-11:]]
                    vsma = sum(vols[:-1]) / len(vols[:-1]) if vols[:-1] else 0
                    vb = vols[-1]

                    score = quality_score(
                        vb, vsma,
                        st["a_high"], hb,
                        st["a_close"], cb,
                        st["ma"]
                    )

                    send(
                        f"🔔 {t} PIVOT\n"
                        f"MA: {st['ma']}\n"
                        f"Score: {score}/100\n"
                        f"High A: {st['a_high']}\n"
                        f"Price: {price}"
                    )

                    st["alerted"] = True
                    st["watching"] = False

                st["expiry"] -= 1
                if st["expiry"] <= 0:
                    st["watching"] = False

            st["prev"] = price
            state[t] = st

        except Exception as e:
            print(t, e)

    save_state(state)


if __name__ == "__main__":
    main()
