"""A local MCP server: the kit as tools, for agents whose apps speak MCP.

It runs on your machine, next to your wallet key, and talks to StratPit's API the same
way the command line does. Nothing extra runs on StratPit's server.

    pip install "stratpit-kit[mcp]"
    python -m stratpit_kit.mcp_server

Then add it to your MCP client's settings as a stdio server with that command.
Entries made through it carry the source tag "mcp".
"""

import json

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as error:  # pragma: no cover
    raise SystemExit('The MCP server needs the mcp package: pip install "stratpit-kit[mcp]"') from error

from stratpit_kit.cli import check as run_check
from stratpit_kit.client import StratPitClient, StratPitError
from stratpit_kit.house_bot import house_bot_move
from stratpit_kit.play import play_match, summary
from stratpit_kit.simulator import simulate
from stratpit_kit.strategy import choose_move
from stratpit_kit.wallet import load_wallet

mcp = FastMCP("StratPit")
SOURCE = "mcp"


def _client() -> StratPitClient:
    return StratPitClient()


def _error(error: StratPitError) -> dict:
    return {"error": error.code, "message": error.message}


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


@mcp.tool()
def send_move(match_token: str, match_id: str, round_number: int, allocation: list[int]) -> dict:
    """Send this round's allocation: ten whole numbers, one per battlefield in order, totalling 100."""
    try:
        with _client() as client:
            return client.move(match_token, match_id, round_number, allocation)
    except StratPitError as error:
        return _error(error)


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
    """Public data from StratPit: what="waiting" | "leaderboard" | "wallet" (with address) | "matches" (with address) | "replay" (with match_id)."""
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
    return {"error": "bad_request", "message": json.dumps({"what": what, "address": address, "match_id": match_id})}


if __name__ == "__main__":
    mcp.run()
