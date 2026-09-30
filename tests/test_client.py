"""The client and the play loop, against a small fake StratPit that follows the API shapes."""

import json

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from stratpit_kit.client import StratPitClient, StratPitError
from stratpit_kit.play import play_practice, summary
from stratpit_kit.wallet import wallet_from_key

VALUES = [3, 10, 1, 7, 7, 2, 9, 5, 10, 4]


class FakeStratPit:
    """Two rounds of Blotto, then a result. Checks the signature like the real server."""

    def __init__(self):
        self.nonce = "b7f3c2a91e5d4f08"
        self.message = None
        self.token = "mt_test"
        self.round = 0
        self.moves = {}
        self.state_calls = 0
        self.entries = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/sign-challenges"):
            self.message = f"StratPit.com entry request\nWallet: {body['wallet']}\nKind: {body['kind']}\nNonce: {self.nonce}"
            return httpx.Response(200, json={"nonce": self.nonce, "message": self.message, "expires_at": "x", "server_time": "x"})
        if path.endswith("/entries/practice"):
            recovered = Account.recover_message(encode_defunct(text=self.message), signature=body["signature"]).lower()
            if recovered != body["wallet"] or body["nonce"] != self.nonce:
                return httpx.Response(400, json={"error": {"code": "signature_invalid", "message": "no"}, "server_time": "x"})
            self.entries.append(body)
            return httpx.Response(
                200,
                json={
                    "entry_id": "e_1",
                    "match_token": self.token,
                    "status": "matched",
                    "match_id": "m_1",
                    "game": "blotto",
                    "rules_version": "v1",
                    "starts_at": "x",
                    "server_time": "x",
                },
            )
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": {"code": "token_invalid", "message": "no"}, "server_time": "x"})
        if path.endswith("/state"):
            self.state_calls += 1
            if self.round == 0:
                self.round = 1  # the first long poll "waits" for the match to start
            return httpx.Response(200, json=self.state())
        if path.endswith("/moves"):
            if body["round"] != self.round:
                return httpx.Response(409, json={"error": {"code": "round_closed", "message": "closed"}, "server_time": "x"})
            if self.round in self.moves:
                return httpx.Response(409, json={"error": {"code": "already_moved", "message": "already"}, "server_time": "x"})
            if sum(body["move"]["allocation"]) != 100:
                return httpx.Response(
                    400, json={"error": {"code": "move_invalid", "message": "total", "reason": "wrong_total"}, "server_time": "x"}
                )
            self.moves[self.round] = body["move"]["allocation"]
            reply = {
                "accepted": True,
                "match_id": "m_1",
                "round": self.round,
                "received_at": "x",
                "move_time_us": 1500000,
                "deadline": "x",
                "next_round_opens_at": "x",
                "server_time": "x",
            }
            self.round += 1  # the round closes as soon as the move is in, to keep the test quick
            return httpx.Response(200, json=reply)
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "no"}, "server_time": "x"})

    def state(self) -> dict:
        past = [
            {
                "number": n,
                "game_data": {"values": VALUES},
                "your_move": {"allocation": m},
                "opponent_move": {"allocation": [10] * 10},
                "your_points": 20,
                "opponent_points": 10,
            }
            for n, m in sorted(self.moves.items())
        ]
        base = {"server_time": "x", "entry_id": "e_1", "kind": "practice", "game": "blotto", "rules_version": "v1", "stake": 0}
        match = {
            "match_id": "m_1",
            "starts_at": "x",
            "total_rounds": 2,
            "you": {"seat": 1, "wallet": "w", "score": 20 * len(past)},
            "opponent": {"wallet": None, "house_bot": True, "score": 10 * len(past)},
            "round": None,
            "past_rounds": past,
        }
        if self.round > 2:
            result = {
                "winner": "you",
                "reason": "points",
                "your_score": 40,
                "opponent_score": 20,
                "your_move_time_us": 3000000,
                "opponent_move_time_us": 4000000,
                "ended_at": "x",
            }
            return {**base, "status": "finished", "check_back_at": None, "match": match, "result": result, "payout": None}
        match["round"] = {
            "number": self.round,
            "opens_at": "x",
            "deadline": "x",
            "next_round_opens_at": "x",
            "game_data": {"values": VALUES},
            "your_move": None,
        }
        return {**base, "status": "playing", "check_back_at": "x", "match": match}


@pytest.fixture
def fake():
    return FakeStratPit()


@pytest.fixture
def client(fake):
    client = StratPitClient("http://fake/api/v1")
    client.http = httpx.Client(base_url="http://fake/api/v1", transport=httpx.MockTransport(fake.handle))
    return client


@pytest.fixture
def wallet():
    return wallet_from_key(bytes(Account.create().key).hex())


def test_a_practice_game_from_entry_to_result(fake, client, wallet):
    lines = []
    final = play_practice(client, wallet, lambda state: [10] * 10, source="test-tag", log=lines.append)
    assert final["status"] == "finished"
    assert fake.entries[0]["source"] == "test-tag"
    assert fake.moves == {1: [10] * 10, 2: [10] * 10}
    assert summary(final) == {
        "status": "finished",
        "match_id": "m_1",
        "rounds": 2,
        "moved_every_round": True,
        "winner": "you",
        "reason": "points",
        "your_score": 40,
        "opponent_score": 20,
    }
    assert any("round 1: sent" in line for line in lines)


def test_a_bad_strategy_still_moves(fake, client, wallet):
    lines = []
    calls = []

    def flaky(state):
        calls.append(state["match"]["round"]["number"])
        if len(calls) == 1:
            raise RuntimeError("oops")
        return [10] * 9 + [5]  # totals 95: invalid

    final = play_practice(client, wallet, flaky, log=lines.append)
    assert final["status"] == "finished"
    assert fake.moves == {1: [10] * 10, 2: [10] * 10}
    assert any("raised RuntimeError" in line for line in lines)
    assert any("invalid move (wrong_total" in line for line in lines)


def test_errors_carry_the_server_code(client):
    with pytest.raises(StratPitError) as error:
        client.state("mt_wrong")
    assert error.value.code == "token_invalid" and error.value.status == 401
