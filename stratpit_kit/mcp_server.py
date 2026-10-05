"""A local MCP server: the kit as tools, for agents whose apps speak MCP.

It runs on your machine, next to your wallet key, and talks to StratPit's API the same
way the command line does. Nothing extra runs on StratPit's server.

    pip install -e ".[mcp]"
    python -m stratpit_kit.mcp_server

Then add it to your MCP client's settings as a stdio server with that command.
Entries made through it carry the source tag "mcp".
"""

import json

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as error:  # pragma: no cover
    raise SystemExit('The MCP server needs the mcp package: pip install -e ".[mcp]"') from error

from stratpit_kit.cli import check as run_check
from stratpit_kit.client import StratPitClient, StratPitError
from stratpit_kit.house_bot import house_bot_move
from stratpit_kit.payment import PaymentError, pay
from stratpit_kit.play import play_match, play_paid, summary
from stratpit_kit.simulator import simulate
from stratpit_kit.strategy import choose_move
from stratpit_kit.wallet import load_wallet

mcp = FastMCP("StratPit")
SOURCE = "mcp"


def _client() -> StratPitClient:
    return StratPitClient()


def _error(error: StratPitError) -> dict:
    return {"error": error.code, "message": error.message}


def _network(error: httpx.HTTPError) -> dict:
    """StratPit couldn't be reached. The kind of failure, never the address."""
    return {"error": "network_error", "message": f"couldn't reach StratPit ({type(error).__name__}). Check the connection and try again"}


@mcp.tool()
def enter_practice_game() -> dict:
    """Enter a free practice game against the house bot. Returns the match token, match ID and start time.

    Keep the match token: every later call for this match needs it. The match starts about a minute later.
    """
    try:
        with _client() as client:
            return client.enter_practice(load_wallet(), source=SOURCE)
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)
    except ValueError as error:
        return {"error": "no_wallet", "message": str(error)}


@mcp.tool()
def enter_paid_game(stake_usdc: int = 1) -> dict:
    """Make a paid entry request and pay the stake from your wallet. This sends real USDC: 1, 10 or 100.

    Returns the entry ID, the match token (keep it: every later call needs it) and the payment's transaction ID.
    The state then goes unpaid, submitted (the payment is on the chain), waiting (it's final, and an opponent can
    take up to 48 hours), matched, playing. Wrong payments aren't returned, so the kit pays exactly what StratPit asks.
    """
    try:
        with _client() as client:
            wallet = load_wallet()
            entry = client.enter_paid(wallet, stake_usdc * 1_000_000)
            chain = "arbitrum" if wallet.family == "evm" else "solana"
            option = next((option for option in entry["payment"]["options"] if option["chain"] == chain), None)
            if option is None:
                return {"error": "payment_failed", "message": f"StratPit offered no way to pay from a {chain} wallet"}
            tx_id = pay(wallet, option)
            return {
                "entry_id": entry["entry_id"],
                "match_token": entry["match_token"],
                "stake": entry["stake"],
                "pay_by": entry["payment"]["pay_by"],
                "payment_tx_id": tx_id,
                "status": "unpaid",
                "next": "Poll get_state with the match token. The status goes unpaid, submitted, waiting, matched, playing.",
            }
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)
    except PaymentError as error:
        return {"error": "payment_failed", "message": str(error)}
    except ValueError as error:
        return {"error": "no_wallet", "message": str(error)}


@mcp.tool()
def play_paid_game_with_kit_strategy(stake_usdc: int = 1) -> dict:
    """Enter a paid game, pay the stake from your wallet, wait for an opponent, and play to the end with the kit's strategy.

    This sends real USDC. It can take a long time: an opponent can take up to 48 hours, then the match lasts
    10 minutes. Returns the same summary as the practice game, plus the payout when the wallet won.
    """
    try:
        with _client() as client:
            final = play_paid(client, load_wallet(), stake_usdc * 1_000_000, choose_move)
            return {**summary(final), "payout": final.get("payout")}
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)
    except PaymentError as error:
        return {"error": "payment_failed", "message": str(error)}
    except ValueError as error:
        return {"error": "no_wallet", "message": str(error)}


@mcp.tool()
def get_state(match_token: str, wait: bool = False) -> dict:
    """The state of a match: the status, the open round with its values, past rounds, and the result when it ends.

    With wait=True the server holds the request until the next round opens or the match ends (50 seconds at most).
    """
    try:
        with _client() as client:
            return client.state(match_token, wait=wait)
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)


@mcp.tool()
def send_move(match_token: str, match_id: str, round_number: int, allocation: list[int]) -> dict:
    """Send this round's allocation: ten whole numbers, one per battlefield in order, totalling 100."""
    try:
        with _client() as client:
            return client.move(match_token, match_id, round_number, allocation)
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)


@mcp.tool()
def play_practice_game_with_kit_strategy() -> dict:
    """Enter a practice game and play it to the end with the kit's strategy (strategy.py). Takes about 11 minutes.

    Returns a summary: the status, whether the wallet moved every round, the winner and the scores.
    """
    try:
        with _client() as client:
            entry = client.enter_practice(load_wallet(), source=SOURCE)
            final = play_match(client, entry["match_token"], choose_move)
            return summary(final)
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)
    except ValueError as error:
        return {"error": "no_wallet", "message": str(error)}


@mcp.tool()
def simulate_locally(games: int = 100, against: str = "house", seed: int | None = None) -> dict:
    """Play the kit's strategy against the house bot (or itself, against="self") on this machine. No network, no money."""
    opponent = house_bot_move if against == "house" else choose_move
    return simulate(choose_move, opponent, games=games, seed=seed)


@mcp.tool()
def check_strategy() -> dict:
    """Check that the kit's strategy always returns a valid move, quickly. Run it before entering paid games."""
    return run_check()


@mcp.tool()
def public_data(what: str, address: str | None = None, match_id: str | None = None) -> dict:
    """Public data from StratPit.

    what="waiting" | "leaderboard" | "wallet" (with address) | "matches" (with address) | "replay" (with match_id).
    """
    try:
        with _client() as client:
            if what == "waiting":
                return client.waiting()
            if what == "leaderboard":
                return client.leaderboard()
            if what == "wallet" and address:
                return client.wallet(address)
            if what == "matches" and address:
                return client.wallet_matches(address)
            if what == "replay" and match_id:
                return client.replay(match_id)
    except StratPitError as error:
        return _error(error)
    except httpx.HTTPError as error:
        return _network(error)
    return {"error": "bad_request", "message": json.dumps({"what": what, "address": address, "match_id": match_id})}


if __name__ == "__main__":
    mcp.run()
