"""Paying the stake: one USDC transfer from your wallet to StratPit's payout wallet.

The kit builds the transfer on your machine, signs it with your key, and sends it to the
chain through a public RPC endpoint (or the one in STRATPIT_RPC_URL). It sends exactly
the amount the entry request reply names, to the address the reply names, and nothing
else. StratPit never holds your key and has no approval over your wallet.

Wrong payments aren't returned, so the kit is careful: it only pays in the native USDC it
knows (Circle's contracts), it checks your balance first, and it refuses to send if
anything doesn't add up.
"""

import base64
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from eth_account import Account
from eth_utils import to_checksum_address
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from stratpit_kit.wallet import Wallet

ENV_RPC = "STRATPIT_RPC_URL"


@dataclass(frozen=True)
class Network:
    family: str  # evm | solana
    label: str
    rpc_url: str  # a public endpoint, used unless STRATPIT_RPC_URL is set
    chain_id: int | None  # EVM only


# The native USDC contracts StratPit accepts, from Circle's list, and the networks they belong to.
NETWORKS = {
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831": Network("evm", "Arbitrum One", "https://arb1.arbitrum.io/rpc", 42161),
    "0x75faf114eafb1bdbe2f0316df893fd58ce46aa4d": Network("evm", "Arbitrum Sepolia", "https://sepolia-rollup.arbitrum.io/rpc", 421614),
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": Network("solana", "Solana", "https://api.mainnet-beta.solana.com", None),
    "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU": Network("solana", "Solana devnet", "https://api.devnet.solana.com", None),
}

TRANSFER_SELECTOR = "a9059cbb"  # ERC-20 transfer(address,uint256)
BALANCE_SELECTOR = "70a08231"  # ERC-20 balanceOf(address)
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
USDC_DECIMALS = 6

Log = Callable[[str], None]


class PaymentError(Exception):
    """The payment wasn't sent."""


def usdc(amount: int) -> str:
    return f"{amount / 1_000_000:g}"


def network_for(option: dict) -> Network:
    """The network a payment option belongs to, from its token contract. Unknown tokens are refused."""
    contract = str(option.get("token_contract") or "")
    network = NETWORKS.get(contract.lower() if contract.startswith("0x") else contract)
    if network is None:
        raise PaymentError(f"StratPit named a token the kit doesn't know ({contract}). Not paying.")
    if option.get("token") != "USDC":
        raise PaymentError(f"StratPit asked for {option.get('token')}. The kit only pays in USDC. Not paying.")
    return network


RPC_TRIES = 3  # a passing failure (the connection, a timeout, a 429 or a 5xx) is tried this many times
RPC_PAUSE = 1.0  # seconds between tries, doubled each time


class Rpc:
    """A small JSON-RPC client. Its errors never repeat the endpoint's address, which can hold a key.

    A passing failure is tried a few times before it's an error. A refusal (another HTTP status,
    or an error in the JSON-RPC reply, such as insufficient funds) is an error at once.
    """

    def __init__(self, url: str, transport: httpx.BaseTransport | None = None, pause: float = RPC_PAUSE):
        self._url = url
        self._client = httpx.Client(timeout=30, transport=transport)
        self._pause = pause

    def close(self) -> None:
        self._client.close()

    def call(self, method: str, params: list):
        for attempt in range(1, RPC_TRIES + 1):
            try:
                reply = self._client.post(self._url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            except Exception as error:  # noqa: BLE001 - whatever went wrong, the message names its kind and never the address
                problem = f"the chain's RPC endpoint didn't answer ({type(error).__name__})"
            else:
                if reply.status_code == 200:
                    try:
                        body = reply.json()
                    except ValueError:
                        body = None
                    if isinstance(body, dict):
                        if body.get("error"):
                            error = body["error"]
                            raise PaymentError(f"{method}: {error.get('message') if isinstance(error, dict) else error}")
                        return body.get("result")
                    problem = "the chain's RPC endpoint answered something that isn't JSON"
                else:
                    problem = f"the chain's RPC endpoint answered HTTP {reply.status_code}"
                    if reply.status_code != 429 and reply.status_code < 500:
                        raise PaymentError(problem)
            if attempt == RPC_TRIES:
                raise PaymentError(problem) from None
            time.sleep(self._pause * attempt)


def pay(wallet: Wallet, option: dict, rpc_url: str | None = None, log: Log = lambda line: None, rpc: Rpc | None = None) -> str:
    """Sends the stake named in a payment option from the wallet. Returns the transaction ID."""
    network = network_for(option)
    if network.family != wallet.family:
        raise PaymentError(f"the payment option is for {network.label}, which this wallet can't pay on")
    own_rpc = rpc is None
    rpc = rpc or Rpc(rpc_url or os.environ.get(ENV_RPC) or network.rpc_url)
    amount = int(option["amount"])
    to_address = str(option["pay_to"])
    log(f"paying {usdc(amount)} USDC to {to_address} on {network.label}")
    try:
        if wallet.family == "evm":
            tx_id = pay_evm(wallet, network, str(option["token_contract"]), to_address, amount, rpc)
        else:
            tx_id = pay_solana(wallet, network, str(option["token_contract"]), to_address, amount, rpc)
    finally:
        if own_rpc:
            rpc.close()
    log(f"sent: transaction {tx_id}")
    return tx_id


# Arbitrum -----------------------------------------------------------------------------


def pad(value: str | int) -> str:
    """A 32-byte argument of a contract call, as 64 hex characters."""
    if isinstance(value, int):
        return format(value, "x").rjust(64, "0")
    return value.lower().removeprefix("0x").rjust(64, "0")


def transfer_data(to_address: str, amount: int) -> str:
    return "0x" + TRANSFER_SELECTOR + pad(to_address) + pad(amount)


def pay_evm(wallet: Wallet, network: Network, token: str, to_address: str, amount: int, rpc: Rpc) -> str:
    chain_id = int(rpc.call("eth_chainId", []), 16)
    if chain_id != network.chain_id:
        raise PaymentError(f"the RPC endpoint is on chain {chain_id}, not {network.label} (chain {network.chain_id}). Not paying.")
    contract = to_checksum_address(token)
    balance = int(rpc.call("eth_call", [{"to": contract, "data": "0x" + BALANCE_SELECTOR + pad(wallet.address)}, "latest"]), 16)
    if balance < amount:
        raise PaymentError(f"your wallet holds {usdc(balance)} USDC on {network.label}, and the stake is {usdc(amount)}. Not paying.")
    data = transfer_data(to_address, amount)
    nonce = int(rpc.call("eth_getTransactionCount", [wallet.address, "pending"]), 16)
    gas = int(rpc.call("eth_estimateGas", [{"from": wallet.address, "to": contract, "data": data}]), 16)
    price = int(rpc.call("eth_gasPrice", []), 16)
    transaction = {
        "chainId": chain_id,
        "nonce": nonce,
        "to": contract,
        "value": 0,
        "data": data,
        "gas": int(gas * 1.5),
        "gasPrice": price * 2,
    }
    signed = Account.sign_transaction(transaction, wallet.secret)
    return str(rpc.call("eth_sendRawTransaction", ["0x" + bytes(signed.raw_transaction).hex()]))


# Solana -------------------------------------------------------------------------------


def token_account(owner: str, mint: str) -> str:
    """The owner's associated token account for the mint: where its USDC lives."""
    address, _ = Pubkey.find_program_address(
        [bytes(Pubkey.from_string(owner)), bytes(Pubkey.from_string(TOKEN_PROGRAM)), bytes(Pubkey.from_string(mint))],
        Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM),
    )
    return str(address)


def build_solana_transfer(keypair: Keypair, mint: str, to_wallet: str, amount: int, blockhash: str) -> Transaction:
    """A signed transfer to the payout wallet's USDC account, creating that account first if it doesn't exist."""
    payer = keypair.pubkey()
    mint_key = Pubkey.from_string(mint)
    source = Pubkey.from_string(token_account(str(payer), mint))
    destination = Pubkey.from_string(token_account(to_wallet, mint))
    create = Instruction(
        Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM),
        bytes([1]),  # create, idempotent
        [
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(destination, is_signer=False, is_writable=True),
            AccountMeta(Pubkey.from_string(to_wallet), is_signer=False, is_writable=False),
            AccountMeta(mint_key, is_signer=False, is_writable=False),
            AccountMeta(Pubkey.from_string(SYSTEM_PROGRAM), is_signer=False, is_writable=False),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM), is_signer=False, is_writable=False),
        ],
    )
    transfer = Instruction(
        Pubkey.from_string(TOKEN_PROGRAM),
        bytes([12]) + amount.to_bytes(8, "little") + bytes([USDC_DECIMALS]),  # transfer checked
        [
            AccountMeta(source, is_signer=False, is_writable=True),
            AccountMeta(mint_key, is_signer=False, is_writable=False),
            AccountMeta(destination, is_signer=False, is_writable=True),
            AccountMeta(payer, is_signer=True, is_writable=False),
        ],
    )
    recent = Hash.from_string(blockhash)
    return Transaction([keypair], Message.new_with_blockhash([create, transfer], payer, recent), recent)


def pay_solana(wallet: Wallet, network: Network, mint: str, to_wallet: str, amount: int, rpc: Rpc) -> str:
    keypair = Keypair.from_seed(wallet.secret)
    try:
        reply = rpc.call("getTokenAccountBalance", [token_account(wallet.address, mint), {"commitment": "confirmed"}])
        balance = int(reply["value"]["amount"])
    except (PaymentError, KeyError, TypeError, ValueError):
        raise PaymentError(f"your wallet has no USDC account on {network.label}. Not paying.") from None
    if balance < amount:
        raise PaymentError(f"your wallet holds {usdc(balance)} USDC on {network.label}, and the stake is {usdc(amount)}. Not paying.")
    latest = rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])
    transaction = build_solana_transfer(keypair, mint, to_wallet, amount, latest["value"]["blockhash"])
    raw = base64.b64encode(bytes(transaction)).decode()
    return str(rpc.call("sendTransaction", [raw, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}]))
