"""Your wallet, on your machine. The key never leaves it.

The kit signs one plain text message per entry, to prove you own the wallet. A signed
message can't move money. For a paid game the kit also signs the one USDC transfer that
pays the stake (see payment.py). StratPit never sees the key, and never asks for a seed
phrase.

The key comes from the STRATPIT_WALLET_KEY environment variable, or a .env file in the
working folder with a line like `STRATPIT_WALLET_KEY=...`:
- Arbitrum: the private key as 64 hex characters, with or without 0x (as MetaMask exports it).
- Solana: the secret key in base58 (as Phantom exports it), or the JSON list of numbers that
  solana-keygen writes to its key file.
A seed phrase isn't a key: export the account's private key from the wallet app first.
"""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import base58
from eth_account import Account
from eth_account.messages import encode_defunct
from nacl.signing import SigningKey

EVM_KEY = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
ENV_NAME = "STRATPIT_WALLET_KEY"


@dataclass(frozen=True)
class Wallet:
    family: str  # evm | solana
    address: str
    _sign: Callable[[str], str] = field(repr=False)
    # The key itself (an Arbitrum private key, or a Solana seed), for signing the stake payment. Never printed.
    secret: bytes = field(repr=False, default=b"")

    def sign(self, message: str) -> str:
        """The signature of the exact text of `message`, in the form the API expects."""
        return self._sign(message)


def wallet_from_key(key: str) -> Wallet:
    key = key.strip()
    if EVM_KEY.match(key):
        account = Account.from_key(key if key.startswith("0x") else "0x" + key)

        def sign_evm(message: str) -> str:
            signed = Account.sign_message(encode_defunct(text=message), account.key)
            return "0x" + bytes(signed.signature).hex()

        return Wallet("evm", account.address.lower(), sign_evm, bytes(account.key))

    try:
        raw = bytes(json.loads(key)) if key.startswith("[") else base58.b58decode(key)
    except (ValueError, TypeError) as error:
        raise ValueError("The wallet key isn't a hex Arbitrum key, a base58 Solana key or solana-keygen's JSON list.") from error
    if len(raw) == 64:
        seed = raw[:32]
    elif len(raw) == 32:
        seed = raw
    else:
        raise ValueError("A Solana secret key decodes to 64 bytes (or a 32-byte seed).")
    signing_key = SigningKey(seed)
    address = base58.b58encode(signing_key.verify_key.encode()).decode()

    def sign_solana(message: str) -> str:
        return base58.b58encode(signing_key.sign(message.encode("utf-8")).signature).decode()

    return Wallet("solana", address, sign_solana, bytes(seed))


def _read_dotenv(folder: Path) -> str | None:
    path = folder / ".env"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(ENV_NAME + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def load_wallet(key: str | None = None) -> Wallet:
    """The wallet from an explicit key, the environment, or a .env file in the working folder."""
    key = key or os.environ.get(ENV_NAME) or _read_dotenv(Path.cwd())
    if not key:
        raise ValueError(f"No wallet key. Set {ENV_NAME} in the environment or in a .env file in this folder.")
    return wallet_from_key(key)
