"""The local MCP server: its tools work against a fake StratPit, and the real server answers over stdio.

These run when the mcp extra is installed (`pip install -e ".[mcp]"`), and are skipped otherwise.
"""

import asyncio
import json
import sys

import httpx
import pytest
from eth_account import Account

pytest.importorskip("mcp")

from stratpit_kit import mcp_server  # noqa: E402
from stratpit_kit.client import StratPitClient  # noqa: E402
from stratpit_kit.payment import PaymentError  # noqa: E402
from test_client import FakeStratPit  # noqa: E402

EXPECTED_TOOLS = {
    "enter_practice_game",
    "enter_paid_game",
    "play_match_with_kit_strategy",
    "get_state",
    "send_move",
    "play_practice_game_with_kit_strategy",
    "simulate_locally",
    "check_strategy",
    "public_data",
}


def client_for(handler) -> StratPitClient:
    client = StratPitClient("http://fake/api/v1")
    client.http = httpx.Client(base_url="http://fake/api/v1", transport=httpx.MockTransport(handler))
    return client


@pytest.fixture
def fake(monkeypatch):
    """The tools talk to a fake StratPit, with a fresh wallet in the environment."""
    fake = FakeStratPit()
    monkeypatch.setattr(mcp_server, "_client", lambda: client_for(fake.handle))
    monkeypatch.setenv("STRATPIT_WALLET_KEY", bytes(Account.create().key).hex())
    return fake


def test_the_server_offers_every_tool_with_a_description():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert all(tool.description for tool in tools)


def test_the_tools_enter_read_and_move(fake):
    entry = mcp_server.enter_practice_game()
    assert entry["match_token"] == fake.token and entry["status"] == "matched"
    assert fake.entries[0]["source"] == "mcp"
    state = mcp_server.get_state(entry["match_token"])
    assert state["status"] == "playing" and state["match"]["round"]["number"] == 1
    reply = mcp_server.send_move(entry["match_token"], "m_1", 1, [10] * 10)
    assert reply["accepted"] is True and fake.moves == {1: [10] * 10}
    # The server's refusals come back as plain errors, never exceptions.
    assert mcp_server.send_move(entry["match_token"], "m_1", 1, [10] * 10) == {"error": "round_closed", "message": "closed"}
    assert mcp_server.get_state("mt_wrong") == {"error": "token_invalid", "message": "no"}


def test_a_whole_practice_game_through_one_tool(fake):
    result = mcp_server.play_practice_game_with_kit_strategy()
    assert result["status"] == "finished" and result["moved_every_round"] is True and result["winner"] == "you"
    assert sorted(fake.moves) == [1, 2]


def test_a_paid_entry_pays_the_stake(fake, monkeypatch):
    paid = []
    monkeypatch.setattr(mcp_server, "pay", lambda wallet, option: paid.append(option) or "0xtx")
    result = mcp_server.enter_paid_game(1)
    assert result["status"] == "unpaid" and result["payment_tx_id"] == "0xtx" and result["match_token"] == fake.token
    assert paid == [fake.option] and fake.paid_entries[0]["stake"] == 1_000_000
    # The paid match is then played with the one-call tool, which pays nothing itself.
    monkeypatch.setattr(mcp_server, "pay", lambda *_: pytest.fail("the play tool must never pay"))
    played = mcp_server.play_match_with_kit_strategy(result["match_token"])
    assert played["status"] == "finished" and played["moved_every_round"] is True and played["payout"] is None
    assert fake.pending == [] and sorted(fake.moves) == [1, 2]


def test_a_failed_payment_keeps_the_match_token(fake, monkeypatch):
    """No gas or no USDC: nothing is sent, and the agent still gets the token and the payment option."""

    def no_gas(wallet, option):
        raise PaymentError("the wallet has no ETH for gas")

    monkeypatch.setattr(mcp_server, "pay", no_gas)
    result = mcp_server.enter_paid_game(1)
    assert result["error"] == "payment_failed" and "gas" in result["message"]
    assert result["match_token"] == fake.token and result["payment_option"] == fake.option and result["pay_by"] == "x"
    assert "payment_tx_id" not in result and fake.paid_entries[0]["stake"] == 1_000_000


def test_play_tool_refusals_are_plain_errors(fake):
    assert mcp_server.play_match_with_kit_strategy("mt_wrong") == {"error": "token_invalid", "message": "no"}


def test_public_data(fake):
    assert mcp_server.public_data("nothing") == {
        "error": "bad_request",
        "message": json.dumps({"what": "nothing", "address": None, "match_id": None}),
    }


def test_no_wallet_and_no_network_are_plain_errors(monkeypatch, tmp_path):
    monkeypatch.delenv("STRATPIT_WALLET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert mcp_server.enter_practice_game()["error"] == "no_wallet"

    def down(request):
        raise httpx.ConnectError("down", request=request)

    monkeypatch.setattr(mcp_server, "_client", lambda: client_for(down))
    result = mcp_server.public_data("waiting")
    assert result["error"] == "network_error" and "ConnectError" in result["message"] and "fake" not in result["message"]


def test_the_local_tools_need_no_network():
    assert mcp_server.check_strategy()["ok"] is True
    assert mcp_server.simulate_locally(games=5, seed=1)["games"] == 5


def test_the_server_answers_over_stdio():
    """The real thing: the server as a subprocess, spoken to the way an MCP client does."""
    from mcp import ClientSession, StdioServerParameters, stdio_client

    async def talk():
        params = StdioServerParameters(command=sys.executable, args=["-m", "stratpit_kit.mcp_server"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            check = await session.call_tool("check_strategy", {})
            simulated = await session.call_tool("simulate_locally", {"games": 3, "seed": 7})
            refused = await session.call_tool("public_data", {"what": "nothing"})
            return {tool.name for tool in listed.tools}, check, simulated, refused

    names, check, simulated, refused = asyncio.run(asyncio.wait_for(talk(), 90))
    assert names == EXPECTED_TOOLS
    report = json.loads(check.content[0].text)
    assert report["ok"] is True and report["invalid"] == 0
    assert json.loads(simulated.content[0].text)["games"] == 3  # arguments arrive over the wire
    assert json.loads(refused.content[0].text)["error"] == "bad_request"  # a refusal is a reply, not a protocol error
