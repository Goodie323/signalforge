import requests
import pandas as pd
import time
import json
from datetime import datetime, timezone
from collections import deque
import csv
import os
import numpy as np

# ── Live trading executor (set LIVE_TRADING=true in Railway to enable) ──
try:
    from executor import execute_trade
    EXECUTOR_AVAILABLE = True
except ImportError:
    EXECUTOR_AVAILABLE = False
    print("⚠️  executor.py not found — live trading disabled")

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────
DOGE_FEED_ID        = "dcef50dd0a4cd2dcc17e45df1676dcb336a11a61c69df7a0299b0150c672d25c"

POLL_INTERVAL       = 10        # seconds between price fetches
MARKET_DURATION     = 3600      # 1 hour in seconds
MINI_CHECK_INTERVAL = 5 * 60    # silent check every 5 minutes
MIN_CONSECUTIVE     = 3         # checks needed to fire (3 × 5min = 15min streak)
ALERT_CUTOFF        = 40 * 60   # stop actionable alerts after 40 minutes

STARTING_BANKROLL   = 100.0     # paper trading starting bankroll ($)
MIN_BET             = 3.0       # Minimum bet ($) — skip signal entirely if Kelly sizes below this
MAX_BET_PCT         = 0.20      # never bet more than 20% of bankroll

LOG_FILE            = "doge_market.csv"
STATE_FILE          = "state.json"
RECORD_FILE         = "win_loss.json"
PAPER_FILE          = "paper_trading.json"

# ── Hardcoded credentials ──
TELEGRAM_BOT_TOKEN  = "8757904533:AAHSsUNGDzfjnBECVYRY3cjDBPlTd3XEei8" #signalforge_mainbot
TELEGRAM_CHAT_ID    = "6648446138"
MARKET_API_URL      = "https://api.limitless.exchange/markets/active"

price_history = deque(maxlen=500)


# ────────────────────────────────────────────────
# PAPER TRADING — Kelly Bankroll
# ────────────────────────────────────────────────
def load_paper():
    try:
        if os.path.exists(PAPER_FILE):
            with open(PAPER_FILE) as f:
                return json.load(f)
    except Exception as e:
        print(f"load_paper failed: {e}")
    return {
        "bankroll":      STARTING_BANKROLL,
        "daily_start":   STARTING_BANKROLL,
        "daily_date":    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "daily_pnl":     0.0,
        "total_pnl":     0.0,
        "open_bet":      None,   # {"signal": "YES"/"NO", "amount": x, "yes_price": y, "no_price": z}
    }

def save_paper(paper):
    try:
        with open(PAPER_FILE, "w") as f:
            json.dump(paper, f, indent=2)
    except Exception as e:
        print(f"save_paper failed: {e}")

def kelly_bet_size(win_prob, payout_ratio, bankroll):
    """
    Quarter Kelly formula.
    win_prob     = model's estimated win probability (e.g. 0.789)
    payout_ratio = net profit ratio (e.g. if you bet $10 and win $18, ratio = 0.8)
    Returns 0.0 if Kelly sizes below MIN_BET — skip rather than overbetting weak signals.
    """
    if payout_ratio <= 0 or win_prob <= 0:
        return 0.0
    loss_prob  = 1 - win_prob
    full_kelly = win_prob - (loss_prob / payout_ratio)
    if full_kelly <= 0:
        return 0.0  # no edge — don't bet
    quarter_kelly = full_kelly / 4
    bet = bankroll * quarter_kelly
    # Cap at MAX_BET_PCT of bankroll
    bet = min(bet, bankroll * MAX_BET_PCT)
    # If Kelly naturally sizes below minimum — signal not worth betting
    if bet < MIN_BET:
        return 0.0
    return round(bet, 2)

def kelly_tier(votes_yes, votes_no, prob):
    """Returns bet size multiplier based on signal confidence."""
    total_decisive = votes_yes + votes_no
    if total_decisive == 3 and prob > 0.80:
        return 1.0, "🔥 Full Kelly (3/3 + prob >0.80)"
    elif total_decisive >= 2 and prob > 0.65:
        return 0.5, "⚡ Half Kelly (2/3 + prob >0.65)"
    elif total_decisive >= 2 and prob > 0.60:
        return 0.25, "💧 Quarter Kelly (marginal signal)"
    else:
        return 0.0, "🚫 No bet (weak signal)"

def reset_daily_if_needed(paper):
    """Resets daily PnL tracker at UTC midnight."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if paper["daily_date"] != today:
        paper["daily_date"]  = today
        paper["daily_start"] = paper["bankroll"]
        paper["daily_pnl"]   = 0.0
    return paper


# ────────────────────────────────────────────────
# LIVE ODDS FETCH
# ────────────────────────────────────────────────
def extract_odds(market):
    """
    Pull YES/NO prices and pool size from Limitless market object.
    Confirmed field mapping from API:
      prices[0] = YES implied probability
      prices[1] = NO implied probability
      volume    = raw USDC integer (divide by 1,000,000)
    Payout ratio = (1 / price) - 1
    """
    try:
        prices    = market.get("prices", [0.5, 0.5])
        yes_price = float(prices[0])
        no_price  = float(prices[1])

        # volume is raw USDC with 6 decimals e.g. 36204474 = $36.20
        pool_size = float(market.get("volume", 0)) / 1_000_000

        return yes_price, no_price, pool_size
    except Exception as e:
        print(f"extract_odds failed: {e}")
        return 0.5, 0.5, 0.0

def compute_edge(model_prob, signal, yes_price, no_price):
    """
    Edge = model's directional probability - market implied probability.
    For YES: model_prob is already the YES probability.
    For NO:  model_prob is the YES probability, so flip it (1 - model_prob) to get NO probability.
    Positive edge = model thinks outcome is more likely than market does.
    """
    if signal == "YES":
        model_directional = model_prob          # prob of YES
        market_implied    = yes_price
        payout_ratio      = (1 / yes_price) - 1 if yes_price > 0 else 0
    elif signal == "NO":
        model_directional = 1 - model_prob      # flip to get prob of NO
        market_implied    = no_price
        payout_ratio      = (1 / no_price) - 1 if no_price > 0 else 0
    else:
        return 0.0, 0.0

    edge = model_directional - market_implied
    return round(edge, 4), round(payout_ratio, 4)


# ────────────────────────────────────────────────
# WIN / LOSS RECORD
# ────────────────────────────────────────────────
def load_record():
    try:
        if os.path.exists(RECORD_FILE):
            with open(RECORD_FILE) as f:
                return json.load(f)
    except Exception as e:
        print(f"load_record failed: {e}")
    return {"wins": 0, "losses": 0, "skips": 0, "total": 0}

def save_record(record):
    try:
        with open(RECORD_FILE, "w") as f:
            json.dump(record, f)
    except Exception as e:
        print(f"save_record failed: {e}")

def evaluate_result(alert_signal, final_price, threshold):
    if alert_signal is None:
        return "NO_SIGNAL"
    ended_above = final_price > threshold
    if alert_signal == "YES" and ended_above:
        return "WIN"
    elif alert_signal == "NO" and not ended_above:
        return "WIN"
    return "LOSS"


# ────────────────────────────────────────────────
# POOL URGENCY
# ────────────────────────────────────────────────
def pool_urgency_label(elapsed):
    minutes = elapsed / 60
    if minutes < 20:
        return "🟢 Pool likely FULL — great odds"
    elif minutes < 35:
        return "🟡 Pool ~50% — decent odds"
    else:
        return "🔴 Pool likely THIN — informational only"


# ────────────────────────────────────────────────
# TELEGRAM
# ────────────────────────────────────────────────
def send_telegram_message(text):
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send failed: {e}")


# ────────────────────────────────────────────────
# STATE PERSISTENCE
# ────────────────────────────────────────────────
def save_state(threshold, expiry):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"threshold": threshold, "expiry": expiry}, f)
    except Exception as e:
        print(f"save_state failed: {e}")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception as e:
        print(f"load_state failed: {e}")
    return None


# ────────────────────────────────────────────────
# LOGGING
# ────────────────────────────────────────────────
def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "utc_time", "elapsed_min", "price", "distance", "rsi",
                "momentum", "volatility", "prob_raw",
                "votes_yes", "votes_no", "votes_skip",
                "yes_price", "no_price", "edge", "pool_size",
                "consecutive", "signal", "signal_reason", "pool_status",
                "bet_size", "outcome", "pnl"
            ])

def log_signal(row):
    try:
        with open(LOG_FILE, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)
    except Exception as e:
        print(f"log_signal failed: {e}")


# ────────────────────────────────────────────────
# MARKET FETCH (Limitless)
# ────────────────────────────────────────────────
def get_doge_market():
    try:
        response = requests.get(MARKET_API_URL, timeout=10)
        if response.status_code != 200:
            print(f"Market API returned {response.status_code}")
            return None
        markets = response.json().get("data", [])
        for market in markets:
            tags   = market.get("tags", [])
            symbol = market.get("priceOracleMetadata", {}).get("symbol", "")
            if symbol == "Crypto.DOGE/USD":
                if "Simple Mode" in tags and "mmbot" in tags and "Prophet" in tags:
                    return market
        return None
    except Exception as e:
        print(f"get_doge_market() failed: {e}")
        return None


# ────────────────────────────────────────────────
# LIVE PRICE FETCH (Pyth)
# ────────────────────────────────────────────────
def get_price():
    url    = "https://hermes.pyth.network/v2/updates/price/latest"
    params = {"ids[]": DOGE_FEED_ID}
    try:
        r     = requests.get(url, params=params, timeout=10)
        data  = r.json()
        p     = data["parsed"][0]["price"]
        price = int(p["price"]) * (10 ** int(p["expo"]))
        ts    = int(p["publish_time"])
        return price, ts
    except Exception as e:
        print(f"get_price() failed: {e}")
        return None, None


# ────────────────────────────────────────────────
# INDICATORS
# ────────────────────────────────────────────────
def compute_rsi(series, window=14):
    if len(series) < window + 1:
        return None
    df       = pd.DataFrame({"c": series})
    d        = df["c"].diff()
    gain     = d.clip(lower=0)
    loss     = -d.clip(upper=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs       = avg_gain / avg_loss
    rsi      = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def compute_twap(prices):
    return float(np.mean(prices)) if len(prices) >= 2 else None


# ────────────────────────────────────────────────
# VOTERS
# ────────────────────────────────────────────────
def vote_probability(current_price, prices, time_left, threshold):
    distance    = current_price - threshold
    vol         = np.std(prices) if len(prices) >= 2 else 0.0001
    z           = distance / vol if vol > 0 else 0
    time_factor = np.sqrt(time_left / MARKET_DURATION) if time_left > 0 else 0.1
    prob        = 1 / (1 + np.exp(-(z / time_factor)))
    if prob > 0.6:
        return "YES", prob
    elif prob < 0.4:
        return "NO", prob
    return "SKIP", prob

def vote_rsi_momentum(current_price, prices, threshold, rsi):
    if rsi is None or len(prices) < 2:
        return "SKIP"
    distance = current_price - threshold
    momentum = (current_price - prices[0]) / prices[0] * 100
    above    = distance > 0
    below    = distance < 0
    if above and rsi >= 75:
        return "NO"
    if below and rsi <= 25:
        return "YES"
    if above and rsi < 70 and momentum > 0:
        return "YES"
    if below and rsi > 30 and momentum < 0:
        return "NO"
    return "SKIP"

def vote_twap(current_price, prices, threshold):
    twap = compute_twap(prices)
    if twap is None:
        return "SKIP"
    price_above_threshold = current_price > threshold
    price_above_twap      = current_price > twap
    if price_above_threshold and price_above_twap:
        return "YES"
    if not price_above_threshold and not price_above_twap:
        return "NO"
    return "SKIP"

def ensemble_signal(current_price, prices, time_left, threshold, rsi):
    v1, prob = vote_probability(current_price, prices, time_left, threshold)
    v2       = vote_rsi_momentum(current_price, prices, threshold, rsi)
    v3       = vote_twap(current_price, prices, threshold)
    votes      = [v1, v2, v3]
    yes_count  = votes.count("YES")
    no_count   = votes.count("NO")
    skip_count = votes.count("SKIP")
    print(f"    Votes → Prob:{v1}  RSI/Mom:{v2}  TWAP:{v3}")
    if yes_count >= 2:
        return "YES", prob, yes_count, no_count, skip_count, f"YES majority {yes_count}/3"
    elif no_count >= 2:
        return "NO", prob, yes_count, no_count, skip_count, f"NO majority {no_count}/3"
    return "SKIP", prob, yes_count, no_count, skip_count, f"No majority YES:{yes_count} NO:{no_count} SKIP:{skip_count}"


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────
print("🚀 Starting SignalForge — DOGE 1H bot (convergence + ensemble + Kelly paper trading)...")
send_telegram_message("⚡ SignalForge is live.\n\nWe watch the market so you don't have to.\nWhen confidence is high, you'll know.\n\n⏳ Monitoring DOGE/USD silently...")
init_log()

while True:
    print("\n🟢 Looking for active DOGE market...")

    poll = get_doge_market()
    if not poll:
        print("No matching market found → retrying in 30s")
        time.sleep(30)
        continue

    THRESHOLD        = float(poll["metadata"]["openPrice"])
    expiry_timestamp = poll["expirationTimestamp"] / 1000
    title            = poll.get("title", "DOGE/USD")

    # ── Pull live odds at market open ──
    yes_price_open, no_price_open, pool_size = extract_odds(poll)

    # ── Resume after restart if market still active ──
    state = load_state()
    if state and time.time() < state["expiry"]:
        THRESHOLD        = state["threshold"]
        expiry_timestamp = state["expiry"]
        print(f"♻️  Resuming from saved state → threshold: {THRESHOLD:.6f}")
        send_telegram_message(f"♻️ Resumed after restart\nThreshold: {THRESHOLD:.6f}")
    else:
        save_state(THRESHOLD, expiry_timestamp)
        print(f"Market found → threshold: {THRESHOLD:.6f}")
        send_telegram_message(
            f"🟢 New DOGE 1H market detected\n"
            f"Title: {title}\n"
            f"Threshold: {THRESHOLD:.6f}\n\n"
            f"💰 Opening Odds:\n"
            f"  YES: {yes_price_open:.2%}  |  NO: {no_price_open:.2%}\n"
            f"  Pool: ${pool_size:,.0f}\n\n"
            f"⏳ Monitoring silently... alert fires when signal converges."
        )

    market_open_time   = time.time()
    price_history.clear()

    # ── Convergence tracker ──
    last_mini_check    = market_open_time
    consecutive_signal = None
    consecutive_count  = 0
    alert_fired        = False
    alert_fired_at     = None
    alert_signal       = None      # locked at convergence, never overwritten
    alert_bet_size     = 0.0       # paper bet placed at convergence
    alert_payout_ratio = 0.0       # locked payout ratio at convergence

    while True:
        now     = time.time()
        elapsed = now - market_open_time

        price, ts = get_price()

        if price is None:
            print("⚠️  Price fetch returned None — skipping cycle")
            time.sleep(POLL_INTERVAL)
            continue

        price_history.append(price)
        prices = list(price_history)

        # ───────── MINI CHECK (every 5 minutes, silent) ─────────
        if now - last_mini_check >= MINI_CHECK_INTERVAL:
            last_mini_check = now
            time_left       = max(MARKET_DURATION - elapsed, 0)
            rsi             = compute_rsi(prices)
            elapsed_min     = elapsed / 60

            signal, prob, yes_v, no_v, skip_v, reason = ensemble_signal(
                price, prices, time_left, THRESHOLD, rsi
            )

            print(f"\n🔍 {elapsed_min:.1f}m silent check → {signal} | streak: {consecutive_count}")

            # ── Update convergence streak (SKIP tolerant — only flip resets) ──
            if signal != "SKIP":
                if signal == consecutive_signal:
                    consecutive_count += 1
                else:
                    consecutive_signal = signal
                    consecutive_count  = 1
            # SKIP → don't increment, don't reset

            # ── Fetch live odds at check time ──
            fresh_market              = get_doge_market()
            yes_price, no_price, pool = extract_odds(fresh_market) if fresh_market else (yes_price_open, no_price_open, pool_size)
            edge, payout_ratio        = compute_edge(prob, signal, yes_price, no_price)

            momentum = ((price - prices[0]) / prices[0] * 100) if len(prices) >= 2 else 0
            vol      = np.std(prices) if len(prices) >= 2 else 0.0001
            distance = price - THRESHOLD
            rsi_str  = f"{rsi:.2f}" if rsi is not None else "N/A"
            pool_lbl = pool_urgency_label(elapsed)
            utc      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            log_signal([
                utc, round(elapsed_min, 1), price, distance, rsi_str,
                momentum, vol, prob, yes_v, no_v, skip_v,
                yes_price, no_price, edge, pool,
                consecutive_count, signal, reason, pool_lbl,
                "", "", ""
            ])

            # ── CONVERGENCE TRIGGER — actionable window ──
            if consecutive_count >= MIN_CONSECUTIVE and not alert_fired and elapsed <= ALERT_CUTOFF:
                alert_fired        = True
                alert_fired_at     = elapsed_min
                alert_signal       = consecutive_signal  # LOCKED — never overwritten

                # ── Kelly bet sizing ──
                paper              = load_paper()
                paper              = reset_daily_if_needed(paper)
                tier_mult, tier_lbl = kelly_tier(yes_v, no_v, prob)
                # Use directional probability for Kelly — flip for NO signals
                directional_prob   = prob if alert_signal == "YES" else 1 - prob
                base_bet           = kelly_bet_size(directional_prob, payout_ratio, paper["bankroll"])
                final_bet          = round(base_bet * tier_mult, 2) if base_bet > 0 else 0.0
                # Skip if Kelly sizes below MIN_BET
                if final_bet < MIN_BET:
                    final_bet      = 0.0
                    tier_lbl       = "🚫 No bet — Kelly below $3 minimum"
                alert_bet_size     = final_bet
                alert_payout_ratio = payout_ratio

                # Record open bet
                paper["open_bet"]  = {
                    "signal":       alert_signal,
                    "amount":       final_bet,
                    "yes_price":    yes_price,
                    "no_price":     no_price,
                    "payout_ratio": payout_ratio
                }
                save_paper(paper)

                # ── LIVE TRADE EXECUTION ──
                if EXECUTOR_AVAILABLE and final_bet > 0:
                    execute_trade(
                        market       = poll,
                        signal       = alert_signal,
                        amount_usdc  = final_bet,
                        paper        = paper,
                        send_telegram_message = send_telegram_message
                    )

                twap     = compute_twap(prices)
                twap_str = f"{twap:.6f}" if twap is not None else "N/A"

                edge_str          = f"{edge:+.1%}"
                edge_label        = "✅ Positive edge" if edge > 0.10 else "⚠️ Thin edge" if edge > 0 else "❌ No edge"
                directional_pct   = prob if alert_signal == "YES" else 1 - prob
                market_pct        = yes_price if alert_signal == "YES" else no_price

                print(f"\n🚨 CONVERGENCE ALERT at {elapsed_min:.1f}m → {alert_signal} | bet: ${final_bet}")

                msg = (
                    f"🚨 DOGE CONVERGED SIGNAL\n\n"
                    f"⏱ Elapsed:  {elapsed_min:.1f} min\n"
                    f"📊 Held for: {consecutive_count * 5} mins ({consecutive_count}/{consecutive_count} checks)\n\n"
                    f"Price:     {price:.6f}\n"
                    f"Threshold: {THRESHOLD:.6f}\n"
                    f"TWAP:      {twap_str}\n\n"
                    f"Distance:  {distance:+.6f}\n"
                    f"RSI:       {rsi_str}\n"
                    f"Momentum:  {momentum:+.3f}%\n\n"
                    f"🗳 Votes → YES:{yes_v}  NO:{no_v}  SKIP:{skip_v}\n"
                    f"Prob (model): {prob:.3f}\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Live Market Odds:\n"
                    f"  YES: {yes_price:.2%}  |  NO: {no_price:.2%}\n"
                    f"  Pool size: ${pool:,.0f}\n\n"
                    f"⚡ Edge: {edge_str}  {edge_label}\n"
                    f"  (Model: {directional_pct:.1%} vs Market: {market_pct:.1%})\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📌 Signal: {alert_signal}\n"
                    f"{pool_lbl}\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 Paper Trade (Kelly):\n"
                    f"  Bankroll:  ${paper['bankroll']:.2f}\n"
                    f"  Bet size:  {'$' + str(final_bet) + '  ' + tier_lbl if final_bet > 0 else tier_lbl}\n"
                    f"  If WIN:   {'+$' + str(round(final_bet * payout_ratio, 2)) if final_bet > 0 else 'N/A'}\n"
                    f"  If LOSS:  {'-$' + str(final_bet) if final_bet > 0 else 'N/A'}"
                )
                send_telegram_message(msg)

            # ── Late convergence — informational only ──
            elif consecutive_count >= MIN_CONSECUTIVE and not alert_fired and elapsed > ALERT_CUTOFF:
                alert_fired    = True
                alert_fired_at = elapsed_min
                alert_signal   = consecutive_signal
                print(f"\n📋 Late convergence at {elapsed_min:.1f}m — informational only")
                send_telegram_message(
                    f"📋 DOGE late signal ({elapsed_min:.1f}m) — informational only\n\n"
                    f"Signal: {signal} | Streak: {consecutive_count} checks\n"
                    f"Market odds: YES {yes_price:.2%} | NO {no_price:.2%}\n"
                    f"🔴 Pool likely thin — do not act on this"
                )

        # ───────── FINAL EXPIRY ─────────
        if now >= expiry_timestamp:
            rsi      = compute_rsi(prices)
            momentum = ((price - prices[0]) / prices[0] * 100) if len(prices) >= 2 else 0
            vol      = np.std(prices) if len(prices) >= 2 else 0.0001
            distance = price - THRESHOLD
            rsi_str  = f"{rsi:.2f}" if rsi is not None else "N/A"
            twap     = compute_twap(prices)
            twap_str = f"{twap:.6f}" if twap is not None else "N/A"

            # Final ensemble (for logging only — alert_signal already locked)
            final_sig, final_prob, yes_v, no_v, skip_v, reason = ensemble_signal(
                price, prices, 0, THRESHOLD, rsi
            )

            utc      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            fired_at = f"{alert_fired_at:.1f}m" if alert_fired_at else "never"

            # ── WIN / LOSS using LOCKED alert_signal ──
            outcome = evaluate_result(alert_signal, price, THRESHOLD)
            record  = load_record()
            paper   = load_paper()
            paper   = reset_daily_if_needed(paper)

            hourly_pnl = 0.0

            if outcome == "WIN":
                record["wins"]    += 1
                outcome_emoji      = "✅ WIN"
                profit             = round(alert_bet_size * alert_payout_ratio, 2)
                hourly_pnl         = profit
                paper["bankroll"] += profit
                paper["daily_pnl"] += profit
                paper["total_pnl"] += profit

            elif outcome == "LOSS":
                record["losses"]   += 1
                outcome_emoji       = "❌ LOSS"
                hourly_pnl          = -alert_bet_size
                paper["bankroll"]  -= alert_bet_size
                paper["daily_pnl"] -= alert_bet_size
                paper["total_pnl"] -= alert_bet_size

            else:
                record["skips"] += 1
                outcome_emoji    = "⏭ NO SIGNAL THIS MARKET"

            paper["open_bet"] = None
            record["total"]  += 1
            save_record(record)
            save_paper(paper)

            decided  = record["wins"] + record["losses"]
            win_rate = (record["wins"] / decided * 100) if decided > 0 else 0.0

            # ── Daily PnL summary ──
            daily_return = (paper["daily_pnl"] / paper["daily_start"] * 100) if paper["daily_start"] > 0 else 0
            total_return = ((paper["bankroll"] - STARTING_BANKROLL) / STARTING_BANKROLL * 100)

            print(f"\n🔥 FINAL: {final_sig} | Outcome: {outcome} | Hourly PnL: ${hourly_pnl:+.2f}")

            log_signal([
                utc, 60.0, price, distance, rsi_str,
                momentum, vol, final_prob, yes_v, no_v, skip_v,
                "", "", "", "",
                consecutive_count, final_sig, f"FINAL|{outcome}", "—",
                alert_bet_size, outcome, hourly_pnl
            ])

            final_msg = (
                f"🔥 FINAL DOGE RESULT (60m)\n\n"
                f"Final Price: {price:.6f}\n"
                f"Threshold:   {THRESHOLD:.6f}\n"
                f"TWAP:        {twap_str}\n\n"
                f"Distance:    {distance:+.6f}\n"
                f"RSI:         {rsi_str}\n"
                f"Momentum:    {momentum:+.3f}%\n\n"
                f"Alert fired:  {fired_at}\n"
                f"Alert signal: {alert_signal if alert_signal else 'None'}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 OUTCOME: {outcome_emoji}\n\n"
                f"All-time: ✅{record['wins']}W  ❌{record['losses']}L  "
                f"Win rate: {win_rate:.1f}%\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💹 PAPER TRADING PnL\n\n"
                f"  This market:  ${hourly_pnl:+.2f}\n"
                f"  Today:        ${paper['daily_pnl']:+.2f}  ({daily_return:+.1f}%)\n"
                f"  All-time:     ${paper['total_pnl']:+.2f}  ({total_return:+.1f}%)\n\n"
                f"  Bankroll:     ${paper['bankroll']:.2f}\n"
                f"  Started:      ${STARTING_BANKROLL:.2f}"
            )
            send_telegram_message(final_msg)

            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)

            print("⏳ Waiting for next market cycle...\n")
            time.sleep(10)
            break

        time.sleep(POLL_INTERVAL)