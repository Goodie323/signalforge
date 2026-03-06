"""
executor.py — SignalForge Live Trade Executor
Handles EIP-712 order signing and submission to Limitless Exchange.
Import this into checker.py and call execute_trade() at convergence.

Required env vars (set in Railway dashboard):
  LIMITLESS_API_KEY   — from limitless.exchange → Profile → API Keys
  PRIVATE_KEY         — your wallet private key (0x...)
  LIVE_TRADING        — set to "true" to enable real trades, anything else = dry run

Required pip installs (add to requirements.txt):
  web3>=6.0.0
  eth-account>=0.10.0
"""

import os
import time
import random
import requests
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
from web3.middleware import geth_poa_middleware

# ────────────────────────────────────────────────
# CHAIN + CONTRACT CONFIG (Base mainnet)
# ────────────────────────────────────────────────
CHAIN_ID        = 8453
RPC_URL         = "https://mainnet.base.org"
API_URL         = "https://api.limitless.exchange"

# Confirmed contract addresses from Limitless CLI docs
USDC_ADDRESS    = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
CTF_ADDRESS     = Web3.to_checksum_address("0xC9c98965297Bc527861c898329Ee280632B76e18")

# EIP-712 domain for Limitless CTF Exchange
EIP712_DOMAIN_NAME    = "Limitless CTF Exchange"
EIP712_DOMAIN_VERSION = "1"

# Minimal USDC ABI — only what we need
USDC_ABI = [
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount",  "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "owner",   "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# ────────────────────────────────────────────────
# CREDENTIALS
# ────────────────────────────────────────────────
LIMITLESS_API_KEY = os.environ.get("LIMITLESS_API_KEY", "")
PRIVATE_KEY       = os.environ.get("PRIVATE_KEY", "")
LIVE_TRADING      = os.environ.get("LIVE_TRADING", "false").lower() == "true"

# Daily loss limit — stop trading if real losses exceed this
DAILY_LOSS_LIMIT  = 20.0   # $ — adjust as needed


# ────────────────────────────────────────────────
# WEB3 SETUP
# ────────────────────────────────────────────────
def get_w3():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3

def get_account():
    if not PRIVATE_KEY:
        raise ValueError("PRIVATE_KEY env var not set")
    return Account.from_key(PRIVATE_KEY)


# ────────────────────────────────────────────────
# USDC BALANCE + APPROVAL
# ────────────────────────────────────────────────
def get_usdc_balance(wallet_address):
    """Returns USDC balance in dollars."""
    try:
        w3       = get_w3()
        usdc     = w3.eth.contract(address=USDC_ADDRESS, abi=USDC_ABI)
        raw      = usdc.functions.balanceOf(
                       Web3.to_checksum_address(wallet_address)
                   ).call()
        return raw / 1_000_000   # 6 decimals
    except Exception as e:
        print(f"get_usdc_balance failed: {e}")
        return 0.0

def ensure_usdc_approved(exchange_address, wallet_address, amount_usdc):
    """
    Checks USDC allowance. If below required amount, sends approve(MAX) tx.
    Returns True if approved, False if failed.
    """
    try:
        w3       = get_w3()
        account  = get_account()
        usdc     = w3.eth.contract(address=USDC_ADDRESS, abi=USDC_ABI)

        allowance = usdc.functions.allowance(
            Web3.to_checksum_address(wallet_address),
            Web3.to_checksum_address(exchange_address)
        ).call()

        required = int(amount_usdc * 1_000_000)

        if allowance >= required:
            print(f"✅ USDC allowance sufficient: {allowance / 1_000_000:.2f}")
            return True

        print(f"⚠️  Approving USDC for {exchange_address}...")
        MAX_UINT = 2**256 - 1
        tx = usdc.functions.approve(
            Web3.to_checksum_address(exchange_address),
            MAX_UINT
        ).build_transaction({
            "from":     wallet_address,
            "nonce":    w3.eth.get_transaction_count(wallet_address),
            "gas":      100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId":  CHAIN_ID
        })

        signed  = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt.status == 1:
            print(f"✅ USDC approved. TX: {tx_hash.hex()}")
            return True
        else:
            print(f"❌ Approval tx failed")
            return False

    except Exception as e:
        print(f"ensure_usdc_approved failed: {e}")
        return False


# ────────────────────────────────────────────────
# EIP-712 ORDER SIGNING
# ────────────────────────────────────────────────
def sign_order(order_dict, verifying_contract):
    """
    Signs a Limitless CTF order using EIP-712.
    order_dict must contain all order fields.
    verifying_contract = market's venue.exchange address.
    """
    account = get_account()

    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name",              "type": "string"},
                {"name": "version",           "type": "string"},
                {"name": "chainId",           "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Order": [
                {"name": "salt",          "type": "uint256"},
                {"name": "maker",         "type": "address"},
                {"name": "signer",        "type": "address"},
                {"name": "taker",         "type": "address"},
                {"name": "tokenId",       "type": "uint256"},
                {"name": "makerAmount",   "type": "uint256"},
                {"name": "takerAmount",   "type": "uint256"},
                {"name": "expiration",    "type": "uint256"},
                {"name": "nonce",         "type": "uint256"},
                {"name": "feeRateBps",    "type": "uint256"},
                {"name": "side",          "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ]
        },
        "domain": {
            "name":              EIP712_DOMAIN_NAME,
            "version":           EIP712_DOMAIN_VERSION,
            "chainId":           CHAIN_ID,
            "verifyingContract": Web3.to_checksum_address(verifying_contract),
        },
        "primaryType": "Order",
        "message":     order_dict
    }

    signed    = account.sign_typed_data(typed_data)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    return signature


# ────────────────────────────────────────────────
# BUILD FOK ORDER
# ────────────────────────────────────────────────
def build_fok_order(market, signal, amount_usdc, wallet_address):
    """
    Builds a FOK (Fill or Kill) market order.

    signal       = "YES" or "NO"
    amount_usdc  = dollars to spend (e.g. 12.40)

    For a BUY order:
      side        = 0
      tokenId     = YES token id if signal==YES, NO token id if signal==NO
      makerAmount = USDC to spend (6 decimals)
      takerAmount = shares to receive = makerAmount / price (18 decimals)
    """
    tokens     = market.get("tokens", {})
    prices     = market.get("prices", [0.5, 0.5])

    if signal == "YES":
        token_id  = int(tokens.get("yes", 0))
        price     = float(prices[0])
    else:
        token_id  = int(tokens.get("no", 0))
        price     = float(prices[1])

    # Amounts
    maker_amount = int(amount_usdc * 1_000_000)          # USDC 6 decimals
    # taker = shares expected = USDC / price, in 18 decimals (shares are ERC1155)
    taker_amount = int((amount_usdc / price) * 10**6)    # shares at USDC scale

    # Expiration: FOK = 0 (fill immediately or kill)
    expiration = 0

    order = {
        "salt":          random.randint(1, 2**32),
        "maker":         Web3.to_checksum_address(wallet_address),
        "signer":        Web3.to_checksum_address(wallet_address),
        "taker":         "0x0000000000000000000000000000000000000000",
        "tokenId":       token_id,
        "makerAmount":   maker_amount,
        "takerAmount":   taker_amount,
        "expiration":    expiration,
        "nonce":         0,
        "feeRateBps":    0,
        "side":          0,             # 0 = BUY
        "signatureType": 0,             # 0 = EOA EIP712
    }

    return order


# ────────────────────────────────────────────────
# SUBMIT ORDER TO LIMITLESS API
# ────────────────────────────────────────────────
def submit_order(market, order_dict, signature, owner_id):
    """Posts signed order to Limitless API."""
    market_slug = market.get("slug", "")
    venue       = market.get("venue", {})

    payload = {
        "order": {
            **order_dict,
            "signature":    signature,
            "price":        order_dict["makerAmount"] / order_dict["takerAmount"]
                            if order_dict["takerAmount"] > 0 else 0,
        },
        "ownerId":    owner_id,
        "orderType":  "FOK",
        "marketSlug": market_slug,
    }

    headers = {
        "x-api-key":    LIMITLESS_API_KEY,
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{API_URL}/orders",
        json=payload,
        headers=headers,
        timeout=15
    )

    return response.status_code, response.json()


# ────────────────────────────────────────────────
# GET OWNER ID (needed for order submission)
# ────────────────────────────────────────────────
def get_owner_id():
    """Fetches profile ID associated with the API key."""
    try:
        headers  = {"x-api-key": LIMITLESS_API_KEY}
        response = requests.get(f"{API_URL}/profile", headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("id", 0)
    except Exception as e:
        print(f"get_owner_id failed: {e}")
    return 0


# ────────────────────────────────────────────────
# DAILY LOSS GUARD
# ────────────────────────────────────────────────
def check_daily_loss_limit(paper):
    """Returns True if safe to trade, False if daily loss limit hit."""
    if paper["daily_pnl"] <= -DAILY_LOSS_LIMIT:
        print(f"🛑 Daily loss limit hit (${paper['daily_pnl']:.2f}) — trading halted")
        return False
    return True


# ────────────────────────────────────────────────
# MAIN ENTRY — called from checker.py at convergence
# ────────────────────────────────────────────────
def execute_trade(market, signal, amount_usdc, paper, send_telegram_message):
    """
    Full trade execution flow:
    1. Check LIVE_TRADING flag
    2. Check daily loss limit
    3. Check USDC balance
    4. Ensure USDC approved
    5. Build + sign + submit FOK order
    6. Send Telegram confirmation

    Returns: dict with execution result
    """
    account      = get_account()
    wallet       = account.address
    venue        = market.get("venue", {})
    exchange_addr = venue.get("exchange", "")

    # ── Dry run check ──
    if not LIVE_TRADING:
        msg = (
            f"🔸 DRY RUN — trade not submitted\n"
            f"  Signal:  {signal}\n"
            f"  Amount:  ${amount_usdc:.2f}\n"
            f"  Market:  {market.get('slug', '')}\n\n"
            f"Set LIVE_TRADING=true in Railway to enable real trades."
        )
        print(msg)
        send_telegram_message(msg)
        return {"status": "dry_run", "amount": amount_usdc}

    # ── Daily loss limit ──
    if not check_daily_loss_limit(paper):
        msg = f"🛑 Trade blocked — daily loss limit of ${DAILY_LOSS_LIMIT} reached"
        send_telegram_message(msg)
        return {"status": "blocked_loss_limit"}

    # ── USDC balance check ──
    balance = get_usdc_balance(wallet)
    if balance < amount_usdc:
        msg = (
            f"⚠️ Insufficient USDC balance\n"
            f"  Required: ${amount_usdc:.2f}\n"
            f"  Available: ${balance:.2f}"
        )
        send_telegram_message(msg)
        return {"status": "insufficient_balance", "balance": balance}

    # ── USDC approval ──
    if not ensure_usdc_approved(exchange_addr, wallet, amount_usdc):
        msg = "❌ USDC approval failed — trade aborted"
        send_telegram_message(msg)
        return {"status": "approval_failed"}

    # ── Build order ──
    try:
        order     = build_fok_order(market, signal, amount_usdc, wallet)
        signature = sign_order(order, exchange_addr)
        owner_id  = get_owner_id()
    except Exception as e:
        msg = f"❌ Order build/sign failed: {e}"
        send_telegram_message(msg)
        return {"status": "build_failed", "error": str(e)}

    # ── Submit order ──
    try:
        status_code, response = submit_order(market, order, signature, owner_id)

        if status_code == 201:
            msg = (
                f"✅ TRADE EXECUTED\n\n"
                f"  Signal:  {signal}\n"
                f"  Amount:  ${amount_usdc:.2f}\n"
                f"  Market:  {market.get('title', '')}\n"
                f"  Wallet:  {wallet[:6]}...{wallet[-4:]}\n"
                f"  Balance: ${balance:.2f} → ${balance - amount_usdc:.2f}"
            )
            send_telegram_message(msg)
            return {"status": "executed", "response": response}

        else:
            msg = (
                f"❌ Order rejected (HTTP {status_code})\n"
                f"  Response: {response}\n"
                f"  Signal: {signal} | Amount: ${amount_usdc:.2f}"
            )
            send_telegram_message(msg)
            return {"status": "rejected", "code": status_code, "response": response}

    except Exception as e:
        msg = f"❌ Order submission failed: {e}"
        send_telegram_message(msg)
        return {"status": "submission_failed", "error": str(e)}