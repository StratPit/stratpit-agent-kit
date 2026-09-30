"""Wallet keys load from the environment or a .env file, and signatures check out."""

import base58
import nacl.signing
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from nacl.signing import VerifyKey
from stratpit_kit.wallet import load_wallet, wallet_from_key

MESSAGE = "StratPit.com entry request\nWallet: x\nKind: practice\nNonce: abc\nExpires: 2026-10-01T12:04:58.000000Z"


def test_an_arbitrum_key_with_or_without_0x():
    account = Account.create()
    key_hex = bytes(account.key).hex()
    for key in (key_hex, "0x" + key_hex):
        wallet = wallet_from_key(key)
        assert wallet.family == "evm"
        assert wallet.address == account.address.lower()
        signature = wallet.sign(MESSAGE)
        assert signature.startswith("0x") and len(signature) == 132
        assert Account.recover_message(encode_defunct(text=MESSAGE), signature=signature).lower() == wallet.address


def test_a_solana_key_as_phantom_exports_it():
    signing_key = nacl.signing.SigningKey.generate()
    secret_64 = base58.b58encode(bytes(signing_key) + signing_key.verify_key.encode()).decode()
    wallet = wallet_from_key(secret_64)
    assert wallet.family == "solana"
    assert wallet.address == base58.b58encode(signing_key.verify_key.encode()).decode()
    signature = wallet.sign(MESSAGE)
    VerifyKey(signing_key.verify_key.encode()).verify(MESSAGE.encode(), base58.b58decode(signature))
    # A 32-byte seed works too.
    assert wallet_from_key(base58.b58encode(bytes(signing_key)).decode()).address == wallet.address


def test_bad_keys_are_refused():
    for key in ("", "not a key", "0x1234", "1" * 10):
        with pytest.raises(ValueError):
            wallet_from_key(key)


def test_the_key_comes_from_the_environment_or_a_dotenv_file(monkeypatch, tmp_path):
    account = Account.create()
    monkeypatch.delenv("STRATPIT_WALLET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        load_wallet()
    (tmp_path / ".env").write_text(f"STRATPIT_WALLET_KEY={bytes(account.key).hex()}\n", encoding="utf-8")
    assert load_wallet().address == account.address.lower()
    other = Account.create()
    monkeypatch.setenv("STRATPIT_WALLET_KEY", "0x" + bytes(other.key).hex())
    assert load_wallet().address == other.address.lower()
    assert load_wallet(bytes(account.key).hex()).address == account.address.lower()
