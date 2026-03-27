# ⚡ SignalForge

> Automated prediction market trading bot powered by Pyth Network real-time price feeds

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Deployed on Railway](https://img.shields.io/badge/Deployed-Railway-purple)](https://railway.app)
[![Pyth Network](https://img.shields.io/badge/Data-Pyth%20Network-orange)](https://pyth.network)
[![Limitless Exchange](https://img.shields.io/badge/Market-Limitless%20Exchange-green)](https://limitless.exchange)

---

## Live Demo

| | |
|---|---|
| **SignalForge Dashboard** | [Goodie323.github.io/signalforge](https://Goodie323.github.io/signalforge) |
| **Pyth Pulse Analytics** | [Goodie323.github.io/signalforge/pulse.html](https://Goodie323.github.io/signalforge/pulse.html) |
| **Bot Stats API** | `https://signalforge-production-bc9d.up.railway.app/stats` |

---

## What It Does

SignalForge monitors DOGE/USD prediction markets on [Limitless Exchange](https://limitless.exchange) 24/7 using Pyth Network's real-time price feed as its sole data source. Every 5 minutes it silently evaluates market direction using three independent technical indicators. When all indicators converge on the same direction for 15 consecutive minutes, it fires a Telegram alert with the signal direction, live Limitless market odds, edge calculation, and Kelly-sized bet recommendation.

At market close it evaluates the outcome against the same Pyth oracle that Limitless uses to settle — ensuring zero discrepancy between prediction and resolution.

The live dashboard shows real-time DOGE/USD from Pyth, ensemble voter states, convergence streak, entry signal banner, and bot PnL — all updating automatically. A companion analytics page (Pyth Pulse) tracks 8 Pyth price feeds simultaneously with a volatility heatmap, rolling correlation matrix, and anomaly detector.

---

## Key Features

- **Real-time Pyth price feed** — polls `hermes.pyth.network` every 10 seconds for DOGE/USD
- **3-voter ensemble signal** — Z-score probability, RSI/Momentum gate, TWAP alignment
- **Convergence tracking** — signal must hold 3 consecutive 5-min checks (15 min) before firing
- **Entry signal banner** — 4 states: STANDBY / ENTER NOW / NO BET / WINDOW CLOSED
- **Live market odds** — pulls YES/NO prices from Limitless API at convergence
- **Edge calculation** — model probability vs market implied odds
- **Kelly Criterion sizing** — quarter Kelly with 3 confidence tiers (Full / Half / Quarter)
- **NO BET detection** — signals Kelly below $1 minimum explicitly, never silently skipped
- **Live stats endpoint** — `/stats` serves real-time bot state as JSON for the dashboard
- **Pyth Pulse** — 8-asset multi-feed analytics dashboard built entirely on Pyth data
- **Auto-execution ready** — `executor.py` handles EIP-712 signing and FOK order submission on Base

---

## Live Results

```
Markets monitored:    50+
Decided markets:      19
Wins:                 16
Losses:                3
Win rate:          84.2%

Real bankroll:           $20.00
Paper bankroll started:  $100.00
Paper bankroll current:  $210.06
Paper return:           +110.1%
```

---

## How It Works

```
Pyth Network (DOGE/USD feed)
        ↓  every 10s via Hermes API
  Price History Buffer
        ↓
  ┌─────────────────────────────────┐
  │  3-Voter Ensemble               │
  │  Voter 1: Z-score probability   │
  │  Voter 2: RSI + Momentum gate   │
  │  Voter 3: TWAP alignment        │
  │  2/3 votes needed to signal     │
  └─────────────────────────────────┘
        ↓  every 5 min silent check
  Convergence Tracker
  (signal must hold 3 checks = 15 min)
        ↓
  Edge Calculation
  (model prob vs Limitless market odds)
        ↓
  Kelly Bet Sizing (quarter Kelly, 3 tiers)
  MIN_BET = $1.00
        ↓
  Telegram Alert + Dashboard Update
        ↓
  Expiry → evaluate_result() vs Pyth price
  WIN/LOSS → PnL Update
```

---

## Pyth Integration

SignalForge uses Pyth's Hermes API for low-latency price updates:

```python
DOGE_FEED_ID = "dcef50dd0a4cd2dcc17e45df1676dcb336a11a61c69df7a0299b0150c672d25c"

def get_price():
    url    = "https://hermes.pyth.network/v2/updates/price/latest"
    params = {"ids[]": DOGE_FEED_ID}
    r      = requests.get(url, params=params, timeout=10)
    data   = r.json()
    p      = data["parsed"][0]["price"]
    price  = int(p["price"]) * (10 ** int(p["expo"]))
    return price, int(p["publish_time"])
```

**Why Pyth specifically?** Limitless Exchange resolves prediction markets using the Pyth DOGE/USD oracle at expiry. SignalForge reads the exact same feed — so what the bot predicts and what the market resolves against are literally the same number. No oracle discrepancy risk.

The frontend dashboard and Pyth Pulse also call the Hermes WebSocket directly from the browser — so Pyth data flows into both backend logic and frontend visualisation independently.

---

## Signal Example

```
🚨 DOGE CONVERGED SIGNAL

⏱ Elapsed:  25.3 min
📊 Held for: 25 mins (5/5 checks)

Price:     0.094437
Threshold: 0.094940
TWAP:      0.094821

🗳 Votes → YES:0  NO:3  SKIP:0
Prob (model): 0.914

━━━━━━━━━━━━━━━━━━
💰 Live Market Odds:
  YES: 42.25%  |  NO: 57.75%
  Pool size: $840

⚡ Edge: +33.7%  ✅ Positive edge
  (Model: 91.4% vs Market: 57.8%)

━━━━━━━━━━━━━━━━━━
📌 Signal: NO

━━━━━━━━━━━━━━━━━━
🧾 Kelly Sizing:
  Bankroll:  $20.00
  Bet size:  $1.40  🔥 Full Kelly
  If WIN:   +$1.05
  If LOSS:  -$1.40
```

---

## Stats Endpoint

`checker.py` runs a lightweight HTTP server exposing live bot state:

```
GET /stats  →  live JSON state
GET /health →  {"status":"ok","service":"SignalForge"}
```

---

## Architecture

```
signalforge/
├── main.py          — Main bot: ensemble logic, convergence, /stats server
├── executor.py      — Live trade execution (EIP-712, Limitless API)
├── requirements.txt — Python dependencies
├── index.html       — SignalForge dashboard (GitHub Pages)
├── pulse.html       — Pyth Pulse analytics (GitHub Pages)
└── login.html       — Supabase auth gate
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11 |
| Price Data | Pyth Network — Hermes API + WebSocket |
| Prediction Market | Limitless Exchange (Base chain) |
| Deployment | Railway (24/7 cloud worker) |
| Dashboard | Vanilla JS + GitHub Pages |
| Notifications | Telegram Bot API |
| Auth | Supabase |
| On-chain Execution | web3.py + EIP-712 signing |
| Blockchain | Base (chain ID 8453) |

---

## Environment Variables

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Live trading only
LIMITLESS_API_KEY=lmts_...
PRIVATE_KEY=0x...
LIVE_TRADING=false   # set to true when ready
```

---

## Kelly Criterion Sizing

```
Full Kelly    = Win% - (Loss% / Payout ratio)
Quarter Kelly = Full Kelly / 4

Tiers:
  3/3 votes + prob > 0.80  →  🔥 Full Kelly
  2/3 votes + prob > 0.65  →  ⚡ Half Kelly
  2/3 votes + prob > 0.60  →  💧 Quarter Kelly
  Below $1 natural size    →  🚫 No bet
```

---

## Safety Guards

- `LIVE_TRADING=false` by default
- Daily loss limit ($5 on $20 bankroll) — halts trading if hit
- USDC balance check before every trade
- Maximum 20% of bankroll per single bet
- Private key in environment variables only — never in code

---

## Roadmap

- [ ] 15-minute market support (Limitless recently added)
- [ ] Multi-asset support (BTC, ETH, SOL markets)
- [ ] Telegram Mini App dashboard
- [ ] Backtesting against historical Pyth price data
- [ ] Multi-user subscription gating

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Built For

[Pyth Community Hackathon](https://dev-forum.pyth.network) — March 4 – April 1, 2026

Wikipedia contribution: [Blockchain oracle — Pyth Network section](https://en.wikipedia.org/wiki/Blockchain_oracle#Pyth_Network)