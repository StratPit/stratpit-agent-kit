"""Paying the stake: the right amount to the right address on the right chain, and nothing when something's off."""

import base64
import json

import base58
import httpx
import pytest
from eth_account import Account
from solders.keypair import Keypair
from solders.transaction import Transaction
from stratpit_kit.payment import NETWORKS, PaymentError, Rpc, network_for, pay, token_account, transfer_data
from stratpit_kit.wallet import wallet_from_key

SEPOLIA_USDC = "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d"
DEVNET_USDC = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
PAYOUT_EVM = "0x" + "22" * 20
PAYOUT_SOLANA = str(Keypair().pubkey())


def evm_option(amount: int = 1_000_000) -> dict:
    return {"chain": "arbitrum", "token": "USDC", "token_contract": SEPOLIA_USDC.lower(), "pay_to": PAYOUT_EVM, "amount": amount}


def solana_option(amount: int = 1_000_000) -> dict:
    return {"chain": "solana", "token": "USDC", "token_contract": DEVNET_USDC, "pay_to": PAYOUT_SOLANA, "amount": amount}


def rpc_with(handler) -> Rpc:
    return Rpc("http://rpc.test", transport=httpx.MockTransport(handler))


def reply(result) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def test_the_kit_only_pays_in_the_usdc_it_knows():
    assert network_for(evm_option()).label == "Arbitrum Sepolia"
    assert network_for({**evm_option(), "token_contract": SEPOLIA_USDC}).chain_id == 421614  # any case
    assert network_for(solana_option()).label == "Solana devnet"
    assert {n.label for n in NETWORKS.values()} == {"Arbitrum One", "Arbitrum Sepolia", "Solana", "Solana devnet"}
    with pytest.raises(PaymentError, match="doesn't know"):
        network_for({**evm_option(), "token_contract": "0x" + "ff" * 20})
    with pytest.raises(PaymentError, match="only pays in USDC"):
        network_for({**evm_option(), "token": "USDT"})


def test_transfer_data():
    assert transfer_data("0x7ABC3462415EC6A688C6A0778FE5BC1ECF33FC5D", 1_900_000) == (
        "0xa9059cbb" + "0" * 24 + "7abc3462415ec6a688c6a0778fe5bc1ecf33fc5d" + "0" * 58 + "1cfde0"
    )


def test_an_arbitrum_payment_is_signed_by_the_wallet_and_sent():
    account = Account.create()
    wallet = wallet_from_key(account.key.hex())
    calls = []
    balance = 5_000_000
    gas_money = 10**15  # 0.001 ETH

    def rpc(request):
        body = json.loads(request.content)
        calls.append(body)
        method, params = body["method"], body["params"]
        if method == "eth_chainId":
            return reply(hex(421614))
        if method == "eth_call":
            assert params[0]["to"] == SEPOLIA_USDC and params[0]["data"] == "0x70a08231" + "0" * 24 + wallet.address[2:]
            return reply(hex(balance))
        if method == "eth_getBalance":
            assert params == [wallet.address, "latest"]
            return reply(hex(gas_money))
        if method == "eth_getTransactionCount":
            assert params == [wallet.address, "pending"]
            return reply("0x3")
        if method == "eth_estimateGas":
            assert params[0] == {"from": wallet.address, "to": SEPOLIA_USDC, "data": transfer_data(PAYOUT_EVM, 1_000_000)}
            return reply(hex(60000))
        if method == "eth_gasPrice":
            return reply(hex(100_000_000))
        assert method == "eth_sendRawTransaction"
        assert Account.recover_transaction(params[0]).lower() == wallet.address
        return reply("0xtxhash")

    logged = []
    assert pay(wallet, evm_option(), rpc=rpc_with(rpc), log=logged.append) == "0xtxhash"
    assert [c["method"] for c in calls][-1] == "eth_sendRawTransaction"
    assert logged[0] == f"paying 1 USDC to {PAYOUT_EVM} on Arbitrum Sepolia" and logged[-1] == "sent: transaction 0xtxhash"

    # Not enough USDC: nothing is sent.
    balance = 999_999
    calls.clear()
    with pytest.raises(PaymentError, match="holds 0.999999 USDC"):
        pay(wallet, evm_option(), rpc=rpc_with(rpc))
    assert "eth_sendRawTransaction" not in [c["method"] for c in calls]

    # Enough USDC but no ETH for gas, or too little: nothing is sent, and the message says so.
    balance = 5_000_000
    gas_money = 0
    with pytest.raises(PaymentError, match="holds no ETH"):
        pay(wallet, evm_option(), rpc=rpc_with(rpc))
    gas_money = 1_000  # far short of 90,000 gas at 0.2 gwei
    with pytest.raises(PaymentError, match="ETH on Arbitrum Sepolia, and the transfer needs about"):
        pay(wallet, evm_option(), rpc=rpc_with(rpc))
    assert "eth_sendRawTransaction" not in [c["method"] for c in calls]
    gas_money = 10**15

    # The wrong chain behind the endpoint: nothing is sent.
    def other_chain(request):
        return reply(hex(1)) if json.loads(request.content)["method"] == "eth_chainId" else rpc(request)

    with pytest.raises(PaymentError, match="chain 1, not Arbitrum Sepolia"):
        pay(wallet, evm_option(), rpc=rpc_with(other_chain))

    # A Solana option can't be paid from an Arbitrum wallet.
    with pytest.raises(PaymentError, match="can't pay on"):
        pay(wallet, solana_option(), rpc=rpc_with(rpc))


def test_a_solana_payment_is_signed_by_the_wallet_and_sent():
    keypair = Keypair()
    wallet = wallet_from_key(base58.b58encode(bytes(keypair)).decode())
    assert wallet.address == str(keypair.pubkey())
    blockhash = base58.b58encode(bytes(range(32))).decode()
    sent = []
    balance = "5000000"
    lamports = 50_000_000  # 0.05 SOL

    def rpc(request):
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        if method == "getTokenAccountBalance":
            assert params[0] == token_account(wallet.address, DEVNET_USDC)
            return reply({"context": {"slot": 1}, "value": {"amount": balance, "decimals": 6}})
        if method == "getBalance":
            assert params == [wallet.address]
            return reply({"context": {"slot": 1}, "value": lamports})
        if method == "getLatestBlockhash":
            return reply({"context": {"slot": 1}, "value": {"blockhash": blockhash, "lastValidBlockHeight": 100}})
        assert method == "sendTransaction" and params[1]["encoding"] == "base64"
        sent.append(params[0])
        return reply("sig123")

    assert pay(wallet, solana_option(), rpc=rpc_with(rpc)) == "sig123"
    transaction = Transaction.from_bytes(base64.b64decode(sent[0]))
    transaction.verify()
    keys = [str(k) for k in transaction.message.account_keys]
    assert keys[0] == wallet.address
    assert (
        token_account(wallet.address, DEVNET_USDC) in keys and token_account(PAYOUT_SOLANA, DEVNET_USDC) in keys and PAYOUT_SOLANA in keys
    )
    assert len(transaction.message.instructions) == 2

    balance = "10"
    with pytest.raises(PaymentError, match="holds 1e-05 USDC"):
        pay(wallet, solana_option(), rpc=rpc_with(rpc))
    assert len(sent) == 1

    # Enough USDC but no SOL for the fee: nothing is sent.
    balance = "5000000"
    lamports = 0
    with pytest.raises(PaymentError, match="holds 0.000000 SOL"):
        pay(wallet, solana_option(), rpc=rpc_with(rpc))
    assert len(sent) == 1


def test_rpc_errors_are_plain_and_never_repeat_the_endpoint():
    def down(request):
        raise httpx.ConnectError("no route to http://rpc.test/secret-key", request=request)

    with pytest.raises(PaymentError) as info:
        rpc_with(down).call("eth_chainId", [])
    assert "secret-key" not in str(info.value) and "ConnectError" in str(info.value)

    def refused(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "insufficient funds for gas"}})

    with pytest.raises(PaymentError, match="insufficient funds for gas"):
        rpc_with(refused).call("eth_sendRawTransaction", ["0x"])


def test_the_wallet_never_prints_its_key():
    account = Account.create()
    wallet = wallet_from_key(account.key.hex())
    assert account.key.hex().removeprefix("0x") not in repr(wallet) and "secret" not in repr(wallet)


def test_a_passing_rpc_failure_is_tried_again_and_a_refusal_is_not():
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom", request=request)
        if len(calls) == 2:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    assert Rpc("http://rpc.test", transport=httpx.MockTransport(flaky), pause=0).call("eth_chainId", []) == "0x1"
    assert len(calls) == 3

    calls.clear()

    def always_down(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(PaymentError, match="didn't answer"):
        Rpc("http://rpc.test", transport=httpx.MockTransport(always_down), pause=0).call("eth_chainId", [])
    assert len(calls) == 3

    calls.clear()

    def refused(request):
        calls.append(1)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "insufficient funds"}})

    with pytest.raises(PaymentError, match="insufficient funds"):
        Rpc("http://rpc.test", transport=httpx.MockTransport(refused), pause=0).call("eth_sendRawTransaction", ["0x"])
    assert len(calls) == 1


def test_a_reply_that_is_not_json_is_a_passing_failure():
    calls = []

    def html_then_ok(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, text="<html>maintenance</html>")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    assert Rpc("http://rpc.test", transport=httpx.MockTransport(html_then_ok), pause=0).call("eth_chainId", []) == "0x1"
    assert len(calls) == 2

    def always_html(request):
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(PaymentError, match="isn't JSON"):
        Rpc("http://rpc.test", transport=httpx.MockTransport(always_html), pause=0).call("eth_chainId", [])
