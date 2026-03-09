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
| **SignalForge Dashboard** | [your-username.github.io/signalforge](https://your-username.github.io/signalforge) |
| **Pyth Pulse Analytics** | [your-username.github.io/signalforge/pulse.html](https://your-username.github.io/signalforge/pulse.html) |
| **Bot Stats API** | `https://signalforge-production-bc9d.up.railway.app/stats` |

---

## Answer Capsule

SignalForge is an automated prediction market trading bot that uses Pyth Network's real-time DOGE/USD price feed as its sole data source. It polls Pyth every 10 seconds, runs a 3-voter ensemble of RSI, momentum, and TWAP indicators, and fires Telegram alerts when signals converge — with live market edge calculation and Kelly Criterion bet sizing against Limitless Exchange 1-hour binary markets.

---

## What It Does

SignalForge monitors DOGE/USD prediction markets on [Limitless Exchange](https://limitless.exchange) 24/7. Every 5 minutes it silently evaluates market direction using three independent technical indicators powered by Pyth price data. When all indicators converge on the same direction for 15+ consecutive minutes, it fires a Telegram alert with the signal, live Limitless market odds, edge calculation, and a Kelly-sized paper trade recommendation.

At market close it evaluates whether the signal was correct, updates a running win/loss record, and reports PnL against a simulated $100 bankroll — giving a verifiable track record before committing real money.

The live dashboard shows real-time DOGE/USD from Pyth, live voter card states, convergence streak, Limitless threshold, and bot PnL — all updating automatically. A companion analytics page (Pyth Pulse) tracks 8 assets simultaneously with a volatility heatmap, correlation matrix, and anomaly detector.

---

## Key Features

- **Real-time Pyth price feed** — polls `hermes.pyth.network` every 10 seconds for DOGE/USD
- **3-voter ensemble signal** — RSI/Momentum gate, TWAP alignment, z-score probability
- **Convergence tracking** — signal must hold 3 consecutive 5-min checks (15 min) before firing
- **Limitless threshold** — tracks the market open price, shows whether DOGE is above/below in real time
- **Live market odds** — pulls YES/NO prices from Limitless API at signal time
- **Edge calculation** — model probability vs market implied odds, only alerts on positive edge
- **Kelly Criterion sizing** — quarter Kelly with 3 confidence tiers (Full / Half / Quarter)
- **Paper trading PnL** — simulated $100 bankroll with per-market and daily PnL tracking
- **Win/loss record** — persistent across Railway restarts via JSON state files
- **Live stats endpoint** — `/stats` serves real-time bot state as JSON for the dashboard
- **Auto-execution ready** — `executor.py` handles EIP-712 signing and live trade submission on Base

---

## Live Dashboard

The SignalForge dashboard is fully wired to live data — no simulated numbers:

- **DOGE/USD price** — fetched from Pyth Hermes every 5 seconds with sparkline
- **Limitless threshold** — pulled from bot stats, green if price above / red if below
- **Voter cards** — RSI, TWAP, momentum states from the running bot, or computed locally from Pyth if bot is offline
- **Convergence tracker** — live streak dots, progress bar, elapsed time
- **PnL panel** — bankroll, all-time return, win/loss record, daily PnL from Railway
- **Ticker** — scrolling live: price, signal, streak, edge, threshold, win rate, bankroll

The dashboard has a smart fallback — if the Railway bot is unreachable it shows "PYTH ONLY" and keeps computing voter signals locally from the live Pyth feed.

---

## Pyth Pulse

A companion multi-asset analytics page tracking 8 pairs (BTC, ETH, SOL, DOGE, BNB, XRP, AVAX, SUI) live via Pyth:

- **Volatility heatmap** — 8 clickable cards colour-coded HIGH/ACTIVE/LOW/CALM with real sparklines
- **Detail panel** — click any card for full price history, confidence interval, tick heatmap, 60-tick range
- **Rolling correlation matrix** — 6×6 Pearson correlation computed from live Pyth returns
- **Anomaly detector** — flags 2σ+ moves in real time, highlights DOGE events as SignalForge targets
- **SignalForge bridge** — live DOGE direction, win rate, bankroll pulled from the bot

---

## How It Works

```
Pyth Network (DOGE/USD)
        ↓  every 10s
  Price History Buffer (deque 500)
        ↓
  ┌─────────────────────────────────┐
  │  3-Voter Ensemble               │
  │                                 │
  │  Voter 1: Z-score probability   │
  │  Voter 2: RSI + Momentum gate   │
  │  Voter 3: TWAP alignment        │
  │                                 │
  │  2/3 votes needed to signal     │
  └─────────────────────────────────┘
        ↓  every 5 min silent check
  Convergence Tracker
  (signal must hold 3 checks = 15 min)
        ↓
  Edge Calculation
  (model prob vs Limitless market odds)
        ↓
  Kelly Bet Sizing
  (quarter Kelly, 3 confidence tiers)
        ↓
  Telegram Alert + Paper Trade
  live_stats updated → /stats endpoint
        ↓
  Expiry → WIN/LOSS → PnL Update
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
    ts     = int(p["publish_time"])
    return price, ts
```

The live dashboard and Pyth Pulse also call the Hermes API directly from the browser every 5 seconds — so Pyth data flows into both the backend bot logic and the frontend visualisation independently.

**Why Pyth?** The Limitless prediction markets resolve using Pyth price data at expiry. Using the same feed means SignalForge and the market evaluate the exact same price at resolution — there is no oracle discrepancy risk.

---

## Stats Endpoint

`checker.py` runs a lightweight HTTP server alongside the main bot loop, exposing live state as JSON:

```
GET /stats  → live bot state
GET /       → {"status":"ok","service":"SignalForge"}
```

Example response:

```json
{
  "price": 0.094437,
  "signal": "NO",
  "prob": 0.914,
  "votes": {"yes": 0, "no": 3, "skip": 0},
  "streak": 3,
  "elapsed": 25.3,
  "rsi": 54.62,
  "momentum": -0.977,
  "twap": 0.094821,
  "threshold": 0.094940,
  "edge": 33.7,
  "market_yes": 42.25,
  "market_no": 57.75,
  "bankroll": 210.06,
  "wins": 16,
  "losses": 3,
  "win_rate": 84.2,
  "updated": "2026-03-08 14:22:00"
}
```

---

## Signal Example

```
🚨 DOGE CONVERGED SIGNAL

⏱ Elapsed:  25.3 min
📊 Held for: 25 mins (5/5 checks)

Price:     0.094437
Threshold: 0.094940
TWAP:      0.094821

Distance:  -0.000503
RSI:       54.62
Momentum:  -0.977%

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
🟢 Pool likely FULL — great odds

━━━━━━━━━━━━━━━━━━
🧾 Paper Trade (Kelly):
  Bankroll:  $115.60
  Bet size:  $14.20  🔥 Full Kelly
  If WIN:   +$10.60
  If LOSS:  -$14.20
```

---

## Live Results (Paper Trading)

```
Markets monitored:    43
Decided markets:      19
Wins:                 16
Losses:                3
Win rate:          84.2%

Paper bankroll started:  $100.00
Paper bankroll current:  $210.06
Total return:           +110.1%
```

*Paper trading only — no real funds at risk during testing period*

---

## Architecture

```
signalforge/
├── checker.py       — Main bot loop, ensemble logic, convergence tracker, /stats server
├── executor.py      — Live trade execution (EIP-712 signing, Limitless API)
├── requirements.txt — Python dependencies
├── Procfile         — Railway deployment config
├── index.html       — Live SignalForge dashboard (GitHub Pages)
├── pulse.html       — Pyth Pulse multi-asset analytics (GitHub Pages)
└── data/
    ├── doge_market.csv    — Full signal log with indicators + odds
    ├── win_loss.json      — Persistent win/loss record
    └── paper_trading.json — Bankroll + PnL state
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11 |
| Price Data | Pyth Network (Hermes API) |
| Prediction Market | Limitless Exchange (Base chain) |
| Deployment | Railway (24/7 cloud) |
| Stats Endpoint | Python HTTPServer (port via `$PORT`) |
| Dashboard | Vanilla JS + GitHub Pages |
| Notifications | Telegram Bot API |
| On-chain Execution | web3.py + EIP-712 signing |
| Blockchain | Base (chain ID 8453) |

---

## Setup

### Prerequisites

- Python 3.10+
- Railway account (free tier works)
- Telegram bot token + chat ID
- Limitless API key (for live trading only)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/signalforge
cd signalforge
pip install -r requirements.txt
```

### Environment Variables

Set in Railway dashboard → Variables tab:

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Live trading only
LIMITLESS_API_KEY=lmts_...
PRIVATE_KEY=0x...
LIVE_TRADING=false   # set to true when ready
```

### Deploy to Railway

```bash
# 1. Push to GitHub
git add .
git commit -m "deploy"
git push

# 2. Connect repo in Railway dashboard
# 3. Set environment variables
# 4. Settings → Networking → Generate Domain (Railway sets PORT automatically)
# 5. Bot starts via Procfile: worker: python checker.py
```

### Connect Dashboard to Bot

In `index.html`, set your Railway domain:

```js
const BOT_STATS_URL = 'https://your-service.up.railway.app';
```

### Run Locally

```bash
python checker.py
```

---

## Paper Trading vs Live Trading

SignalForge ships with `LIVE_TRADING=false` by default. In this mode all signal analysis runs normally and paper trades simulate against a $100 virtual bankroll — no real money is ever moved.

To enable live trading, set `LIVE_TRADING=true` and ensure your wallet has USDC on Base. The executor handles USDC approval, EIP-712 order signing, and FOK order submission to Limitless automatically.

**Recommended:** Run paper trading for 50+ markets before enabling live trading.

---

## Kelly Criterion Sizing

```
Full Kelly    = Win% - (Loss% / Payout ratio)
Quarter Kelly = Full Kelly / 4

Tiers:
  3/3 votes + prob > 0.80  → Full Quarter Kelly
  2/3 votes + prob > 0.65  → Half Quarter Kelly
  2/3 votes + prob > 0.60  → Quarter Quarter Kelly
  Below $3 natural size    → Skip (no bet)
```

---

## Safety Guards

- `LIVE_TRADING=false` by default — must explicitly enable
- Daily loss limit ($20) — halts trading if hit
- Pool size check — skips markets with insufficient liquidity
- USDC balance check before every trade
- Maximum 20% of bankroll per single bet
- Private key stored in environment variables only, never in code

---

## Roadmap

- [ ] Multi-asset support (BTC, ETH, SOL markets)
- [ ] Telegram Mini App dashboard
- [ ] Multi-user subscription gating
- [ ] Backtesting against historical Pyth price data
- [ ] Hurst exponent regime detection (mean reversion vs trend)

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Built For

[Pyth Community Hackathon](https://dev-forum.pyth.network) — March 4 – April 1, 2026

*SignalForge uses Pyth Network price feeds as its core data source. The ensemble signal system, live dashboard, and Pyth Pulse analytics all depend on Pyth's real-time, high-fidelity price data.*