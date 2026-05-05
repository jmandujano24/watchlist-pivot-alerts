import os
import json
import requests

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = "state.json"

MA_PRIORITY = {
    "D_EMA8": 1,
    "D_EMA20": 2,
    "D_SMA50": 3,
    "W_EMA8": 4,
}


# =========================
# UTIL
# =========================

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg
    })


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def load_tickers():
    with open("tickers.txt", "r") as f:
        return [
            x.strip().upper()
            for x in f.readlines()
            if x.strip()
        ]


# =========================
# DATA
# =========================

def fetch(symbol, interval, size=120):
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={symbol}"
        f"&interval={interval}"
        f"&outputsize={size}"
        f"&apikey={API_KEY}"
    )

    data = requests.get(url).json()

    if "values" not in data:
        raise Exception(f"{symbol}: {data}")

    return list(reversed(data["values"]))


# =========================
# MA
# =========================

def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    out = [values[0]]

    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))

    return out[-1]


def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


def detect_cross(symbol):
    candidates = []

    # DAILY
    daily = fetch(symbol, "1day", 100)
    closes_d = [float(x["close"]) for x in daily]
    now_d = closes_d[-1]

    ema8_d = ema(closes_d, 8)
    ema20_d = ema(closes_d, 20)
    sma50_d = sma(closes_d, 50)

    if ema8_d and now_d < ema8_d:
        candidates.append("D_EMA8")

    if ema20_d and now_d < ema20_d:
        candidates.append("D_EMA20")

    if sma50_d and now_d < sma50_d:
        candidates.append("D_SMA50")

    # WEEKLY
    weekly = fetch(symbol, "1week", 60)
    closes_w = [float(x["close"]) for x in weekly]
    now_w = closes_w[-1]

    ema8_w = ema(closes_w, 8)

    if ema8_w and now_w < ema8_w:
        candidates.append("W_EMA8")

    if not candidates:
        return None

    return max(candidates, key=lambda x: MA_PRIORITY[x])


# =========================
# SCORE
# =========================

def quality_score(vb, vsma, ref_high, hb, ref_close, cb):
    score = 0

    vr = vb / vsma if vsma else 0

    # volumen
    if vr > 1.5:
        score += 40
    elif vr > 1:
        score += 25
    else:
        score += 10

    # breakout strength
    strength = (hb - ref_high) / ref_high

    if strength > 0.008:
        score += 30
    elif strength > 0.003:
        score += 15
    else:
        score += 5

    # momentum
    if cb > ref_close:
        score += 20

    return score


# =========================
# MAIN
# =========================

def main():
    state = load_state()
    tickers = load_tickers()

    trigger_msgs = []

    for symbol in tickers:
        try:
            if symbol not in state:
                state[symbol] = {
                    "watching": False,
                    "ma": None,
                    "priority": 0,
                    "a_high": None,
                    "a_close": None,
                    "expiry": 0,
                    "prev": 0
                }

            s = state[symbol]

            # detectar pérdida MA
            trigger_ma = detect_cross(symbol)

            # datos 30m
            bars30 = fetch(symbol, "30min", 30)

            bar_a = bars30[-2]
            bar_b = bars30[-1]

            ha = float(bar_a["high"])
            hb = float(bar_b["high"])
            ca = float(bar_a["close"])
            cb = float(bar_b["close"])

            vols = [float(x.get("volume", 0)) for x in bars30[-12:]]
            vb = vols[-1]
            vsma = sum(vols[:-1]) / len(vols[:-1]) if vols[:-1] else 0

            price = cb

            # activar / reemplazar vigilancia
            if trigger_ma:
                p = MA_PRIORITY[trigger_ma]

                if (not s["watching"]) or (p > s["priority"]):
                    s["watching"] = True
                    s["ma"] = trigger_ma
                    s["priority"] = p
                    s["a_high"] = hb
                    s["a_close"] = cb
                    s["expiry"] = 20

                    trigger_msgs.append(
                        f"{symbol} → {trigger_ma}"
                    )

            # rolling pivot
            if s["watching"]:

                if hb >= s["a_high"]:
                    score = quality_score(
                        vb,
                        vsma,
                        s["a_high"],
                        hb,
                        s["a_close"],
                        cb
                    )

                    vr = vb / vsma if vsma else 0

                    send(
                        f"🔔 {symbol} PIVOT 30m\n"
                        f"MA: {s['ma']}\n"
                        f"Score: {score}/100\n"
                        f"Price: {price:.2f}\n"
                        f"VolRatio: {vr:.2f}x"
                    )

                    state[symbol] = {
                        "watching": False,
                        "ma": None,
                        "priority": 0,
                        "a_high": None,
                        "a_close": None,
                        "expiry": 0,
                        "prev": price
                    }

                else:
                    s["a_high"] = ha
                    s["a_close"] = ca
                    s["expiry"] -= 1

                    if s["expiry"] <= 0:
                        state[symbol] = {
                            "watching": False,
                            "ma": None,
                            "priority": 0,
                            "a_high": None,
                            "a_close": None,
                            "expiry": 0,
                            "prev": price
                        }

            state[symbol]["prev"] = price

        except Exception as e:
            print(f"{symbol}: {e}")

    # mensaje agrupado triggers
    if trigger_msgs:
        send(
            "👀 WATCHLIST TRIGGERS\n\n"
            + "\n".join(trigger_msgs)
        )

    save_state(state)


if __name__ == "__main__":
    main()
