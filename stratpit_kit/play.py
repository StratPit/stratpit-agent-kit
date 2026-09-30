"""The play loop. Don't change this: it's the timing and plumbing the rules depend on.

It uses long polling, so the server holds each state request until the next round opens
or the match ends. That's about two requests a round, well inside the limit of 20 a
minute per match token. Your strategy is called once per round, the moment the round
is open, and the move is sent straight away.
"""

import time
from collections.abc import Callable

import httpx

from stratpit_kit.client import StratPitClient, StratPitError
from stratpit_kit.rules import BATTLEFIELDS, TROOPS, InvalidMove, validate_allocation
from stratpit_kit.wallet import Wallet

ENDED = {"finished", "cancelled", "expired", "refunded"}
NETWORK_ERRORS = (httpx.TransportError, httpx.TimeoutException)
EVEN_SPLIT = [TROOPS // BATTLEFIELDS] * BATTLEFIELDS

Log = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


def choose_safely(choose_move: Callable[[dict], list[int]], state: dict, log: Log) -> list[int]:
    """Your strategy's move, checked locally. If it fails or is invalid, an even split goes instead of a missed turn."""
    try:
        return validate_allocation(choose_move(state))
    except InvalidMove as invalid:
        log(f"your strategy returned an invalid move ({invalid.reason}: {invalid.message}); sending an even split instead")
    except Exception as error:  # noqa: BLE001 - a broken strategy must not cost the match
        log(f"your strategy raised {type(error).__name__}: {error}; sending an even split instead")
    return list(EVEN_SPLIT)


def send_move(client: StratPitClient, token: str, state: dict, choose_move: Callable[[dict], list[int]], log: Log) -> bool:
    """Sends this round's move. Returns True if a move was accepted (by this call or before)."""
    match = state["match"]
    round_no = match["round"]["number"]
    allocation = choose_safely(choose_move, state, log)
    for attempt in range(3):
        try:
            reply = client.move(token, match["match_id"], round_no, allocation)
            log(f"round {round_no}: sent {allocation} after {reply['move_time_us'] / 1_000_000:.1f}s")
            return True
        except StratPitError as error:
            if error.code == "already_moved":
                return True
            if error.code == "move_invalid" and allocation != EVEN_SPLIT:
                log(f"round {round_no}: the server refused the move ({error.message}); sending an even split")
                allocation = list(EVEN_SPLIT)
                continue
            if error.code == "rate_limited":
                time.sleep(error.retry_after or 2)
                continue
            log(f"round {round_no}: move refused, {error.code}: {error.message}")
            return False
        except NETWORK_ERRORS as error:
            log(f"round {round_no}: network problem sending the move ({error}); trying again")
            time.sleep(1 + attempt)
    return False


def play_match(client: StratPitClient, token: str, choose_move: Callable[[dict], list[int]], log: Log = _quiet) -> dict:
    """Plays one match to the end with the given strategy. Returns the final state."""
    last_status = None
    while True:
        try:
            state = client.state(token, wait=True)
        except StratPitError as error:
            if error.code == "rate_limited":
                time.sleep(error.retry_after or 5)
                continue
            raise
        except NETWORK_ERRORS as error:
            log(f"network problem reading the state ({error}); trying again")
            time.sleep(2)
            continue

        status = state["status"]
        if status != last_status:
            log(f"status: {status}" + (f", match starts at {state['match']['starts_at']}" if status == "matched" else ""))
            last_status = status
        if status in ENDED:
            return state
        if status == "playing":
            round_ = state["match"]["round"]
            if round_ is not None and round_["your_move"] is None:
                send_move(client, token, state, choose_move, log)


def play_practice(
    client: StratPitClient, wallet: Wallet, choose_move: Callable[[dict], list[int]], source: str = "kit", log: Log = _quiet
) -> dict:
    """Enters a free practice game against the house bot and plays it to the end."""
    entry = client.enter_practice(wallet, source=source)
    log(f"entered practice match {entry['match_id']} as {wallet.address}, starts at {entry['starts_at']}")
    return play_match(client, entry["match_token"], choose_move, log)


def summary(final: dict) -> dict:
    """A short, machine-readable summary of a finished match."""
    match = final.get("match") or {}
    past = match.get("past_rounds") or []
    result = final.get("result") or {}
    return {
        "status": final["status"],
        "match_id": match.get("match_id"),
        "rounds": len(past),
        "moved_every_round": bool(past) and all(r["your_move"] is not None for r in past),
        "winner": result.get("winner"),
        "reason": result.get("reason"),
        "your_score": result.get("your_score"),
        "opponent_score": result.get("opponent_score"),
    }
