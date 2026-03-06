# ⚡ SignalForge

> AI-powered prediction market trading bot using Pyth Network real-time price feeds

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Deployed on Railway](https://img.shields.io/badge/Deployed-Railway-purple)](https://railway.app)
[![Pyth Network](https://img.shields.io/badge/Data-Pyth%20Network-orange)](https://pyth.network)
[![Limitless Exchange](https://img.shields.io/badge/Market-Limitless%20Exchange-green)](https://limitless.exchange)

---

## Answer Capsule

SignalForge is an automated prediction market trading bot that uses Pyth Network's real-time DOGE/USD price feed as its sole data source. It polls Pyth every 10 seconds, runs a 3-voter ensemble of RSI, momentum, and TWAP indicators, and fires Telegram alerts when signals converge — with live market edge calculation and Kelly Criterion bet sizing.

---

## What It Does

SignalForge monitors DOGE/USD prediction markets on [Limitless Exchange](https://limitless.exchange) 24/7. Every 5 minutes it silently evaluates market direction using three independent technical indicators powered by Pyth price data. When all indicators converge on the same direction for 15+ consecutive minutes, it fires a Telegram alert with the signal, live market odds, edge calculation, and a Kelly-sized paper trade recommendation.

At market close it evaluates whether the signal was correct, updates a running win/loss record, and reports PnL against a simulated $100 bankroll — giving users a live track record before committing real money.

---

## Key Features

- **Real-time Pyth price feed** — polls `hermes.pyth.network` every 10 seconds for DOGE/USD
- **3-voter ensemble signal** — RSI/Momentum gate, TWAP alignment, z-score probability
- **Convergence tracking** — signal must hold for 15+ minutes before firing, filtering noise
- **Live market odds** — pulls YES/NO prices from Limitless API at signal time
- **Edge calculation** — compares model probability vs market implied odds, only alerts on positive edge
- **Kelly Criterion sizing** — quarter Kelly with 3 confidence tiers (Full / Half / Quarter)
- **Paper trading PnL** — simulated $100 bankroll with hourly and daily PnL tracking
- **Win/loss record** — persistent across Railway restarts, tracks accuracy over time
- **Auto-execution ready** — `executor.py` handles EIP-712 signing and live trade submission

---

## How It Works

```
Pyth Network (DOGE/USD)
        ↓  every 10s
  Price History Buffer
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
        ↓
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
        ↓
  Expiry → WIN/LOSS → PnL Update
```

---

## Pyth Integration

SignalForge uses Pyth's off-chain Hermes API for low-latency price updates:

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

**Why Pyth?** Pyth provides sub-second DOGE/USD price updates directly from institutional market makers, making it the only reliable source for the real-time price analysis the ensemble requires. The Limitless prediction markets themselves resolve using Pyth data — so using the same feed means SignalForge and the market are evaluating the exact same price at resolution.

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
├── checker.py       — Main bot loop, ensemble logic, convergence tracker
├── executor.py      — Live trade execution (EIP-712 signing, Limitless API)
├── requirements.txt — Python dependencies
├── Procfile         — Railway deployment config
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
| Notifications | Telegram Bot API |
| On-chain Execution | web3.py + EIP-712 signing |
| Blockchain | Base (chain ID 8453) |

---

## Setup

### Prerequisites

- Python 3.10+
- Railway account (free tier works)
- Telegram bot token + chat ID
- Limitless API key (for live trading)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/signalforge
cd signalforge
pip install -r requirements.txt
```

### Configuration

Set the following in your environment (Railway dashboard or `.env` file):

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# For live trading only
LIMITLESS_API_KEY=lmts_...
PRIVATE_KEY=0x...
LIVE_TRADING=false   # set to true when ready
```

### Deploy to Railway

```bash
# 1. Push to GitHub
git add .
git commit -m "initial"
git push

# 2. Connect repo in Railway dashboard
# 3. Set environment variables
# 4. Railway auto-deploys from Procfile:
#    worker: python checker.py
```

### Run Locally

```bash
python checker.py
```

---

## Paper Trading vs Live Trading

SignalForge ships with `LIVE_TRADING=false` by default. In this mode:

- Full signal analysis runs normally
- Paper trades are simulated against a $100 virtual bankroll
- No real money is ever moved
- All signals and PnL are logged

To enable live trading, set `LIVE_TRADING=true` and ensure your wallet has USDC on Base. The executor handles USDC approval, EIP-712 order signing, and FOK order submission automatically.

**Recommended:** Run paper trading for 50+ markets before enabling live trading.

---

## Kelly Criterion Sizing

SignalForge uses Quarter Kelly to size bets conservatively:

```
Full Kelly  = Win% - (Loss% / Payout ratio)
Quarter Kelly = Full Kelly / 4

Tiers:
  3/3 votes + prob > 0.80  → Full Quarter Kelly
  2/3 votes + prob > 0.65  → Half Quarter Kelly
  2/3 votes + prob > 0.60  → Quarter Quarter Kelly
  Below $3 natural size    → Skip (no bet)
```

This protects the bankroll during losing streaks while compounding aggressively during winning runs.

---

## Safety Guards

- `LIVE_TRADING=false` by default — must explicitly enable
- Daily loss limit (`$20`) — halts trading if hit
- Pool size check — skips markets with insufficient liquidity
- USDC balance check before every trade
- Maximum 20% of bankroll per single bet
- Private key stored in environment variables only, never in code

---

## Roadmap

- [ ] Multi-asset support (BTC, ETH, SOL markets)
- [ ] Telegram Mini App dashboard with live win rate chart
- [ ] Multi-user subscription gating (Stripe / Telegram Stars)
- [ ] Backtesting framework against historical Pyth price data
- [ ] Hurst exponent regime detection (mean reversion vs trend)

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Built For

[Pyth Community Hackathon](https://dev-forum.pyth.network) — March 4 – April 1, 2026

*SignalForge uses Pyth Network price feeds as its core data source. Without Pyth's real-time, high-fidelity price data, the ensemble signal system cannot function.*