"""The StratPit API client: the 10 calls, with the signing done for you.

Every call sits under https://StratPit.com/api/v1. Errors come back as StratPitError,
with the server's code and message. The full API is at https://StratPit.com/docs/api.
"""

import os

import httpx

from stratpit_kit import __version__
from stratpit_kit.wallet import Wallet

DEFAULT_BASE_URL = "https://StratPit.com/api/v1"


class StratPitError(Exception):
    """An error reply from the API. `code` is the server's error code."""

    def __init__(self, code: str, message: str, status: int, body: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.body = body or {}

    @property
    def retry_after(self) -> int | None:
        return self.body.get("error", {}).get("retry_after_seconds")


class StratPitClient:
    def __init__(self, base_url: str | None = None, timeout: float = 70.0):
        base_url = (base_url or os.environ.get("STRATPIT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.http = httpx.Client(base_url=base_url, timeout=timeout, headers={"User-Agent": f"stratpit-kit/{__version__}"})

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # The plumbing --------------------------------------------------------------------

    def _call(self, method: str, path: str, *, json: dict | None = None, token: str | None = None, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        reply = self.http.request(method, path, json=json, params=params, headers=headers)
        try:
            body = reply.json()
        except ValueError:
            body = {}
        if reply.status_code >= 400:
            error = body.get("error", {})
            raise StratPitError(
                error.get("code", "server_error"),
                error.get("message", f"HTTP {reply.status_code}"),
                reply.status_code,
                body,
            )
        return body

    # Playing ---------------------------------------------------------------------------

    def sign_challenge(self, wallet: Wallet, kind: str, stake: int | None = None) -> dict:
        body = {"wallet": wallet.address, "kind": kind}
        if stake is not None:
            body["stake"] = stake
        return self._call("POST", "/sign-challenges", json=body)

    def enter_practice(self, wallet: Wallet, source: str = "kit", game: str = "blotto") -> dict:
        """A free practice game against the house bot. The reply has the match token."""
        challenge = self.sign_challenge(wallet, "practice")
        body = {
            "wallet": wallet.address,
            "nonce": challenge["nonce"],
            "signature": wallet.sign(challenge["message"]),
            "game": game,
            "source": source,
        }
        return self._call("POST", "/entries/practice", json=body)

    def enter_paid(self, wallet: Wallet, stake: int, game: str = "blotto") -> dict:
        """A paid entry request. The reply has the match token and how to pay."""
        challenge = self.sign_challenge(wallet, "paid", stake)
        body = {
            "wallet": wallet.address,
            "stake": stake,
            "nonce": challenge["nonce"],
            "signature": wallet.sign(challenge["message"]),
            "game": game,
        }
        return self._call("POST", "/entries/paid", json=body)

    def state(self, token: str, wait: bool = False) -> dict:
        """The entry's state. With wait, the server holds the request until something changes (50 seconds at most)."""
        return self._call("GET", "/state", token=token, params={"wait": 1} if wait else None)

    def move(self, token: str, match_id: str, round_no: int, allocation: list[int]) -> dict:
        body = {"match_id": match_id, "round": round_no, "move": {"allocation": list(allocation)}}
        return self._call("POST", "/moves", json=body, token=token)

    # Public data -----------------------------------------------------------------------

    def waiting(self) -> dict:
        return self._call("GET", "/waiting")

    def leaderboard(self, game: str = "blotto", page: int = 1) -> dict:
        return self._call("GET", "/leaderboard", params={"game": game, "page": page})

    def wallet(self, address: str) -> dict:
        return self._call("GET", f"/wallets/{address}")

    def wallet_matches(self, address: str, game: str | None = None, page: int = 1) -> dict:
        params = {"page": page}
        if game:
            params["game"] = game
        return self._call("GET", f"/wallets/{address}/matches", params=params)

    def replay(self, match_id: str) -> dict:
        return self._call("GET", f"/replays/{match_id}")
