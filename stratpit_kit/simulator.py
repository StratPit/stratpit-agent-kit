"""The local simulator: matches on your own machine, with the same rules and the same state shape as the real server.

Try a strategy against the house bot, or against itself, a few hundred times, and see
whether it wins more than it loses. Speed ties are broken by how long each strategy
took to decide, so slow code shows up here too.
"""

import random
import time
from collections.abc import Callable

from stratpit_kit.rules import TOTAL_ROUNDS, InvalidMove, decide, random_values, score_round, validate_allocation

Strategy = Callable[[dict], list[int]]


def build_state(seat: int, round_no: int, values: list[int], past: list[dict], scores: list[int]) -> dict:
    """What a strategy sees: the same shape as GET /state while playing."""
    other = 2 if seat == 1 else 1
    return {
        "status": "playing",
        "kind": "practice",
        "game": "blotto",
        "rules_version": "v1",
        "stake": 0,
        "match": {
            "match_id": "local",
            "starts_at": None,
            "total_rounds": TOTAL_ROUNDS,
            "you": {"seat": seat, "wallet": f"seat-{seat}", "score": scores[seat - 1]},
            "opponent": {"wallet": f"seat-{other}", "house_bot": False, "score": scores[other - 1]},
            "round": {
                "number": round_no,
                "opens_at": None,
                "deadline": None,
                "next_round_opens_at": None,
                "game_data": {"values": values},
                "your_move": None,
            },
            "past_rounds": [
                {
                    "number": r["number"],
                    "game_data": r["game_data"],
                    "your_move": r["moves"][seat - 1],
                    "opponent_move": r["moves"][other - 1],
                    "your_points": r["points"][seat - 1] if r["points"] else None,
                    "opponent_points": r["points"][other - 1] if r["points"] else None,
                }
                for r in past
            ],
        },
    }


def play_local_match(strategy_1: Strategy, strategy_2: Strategy, rng: random.Random | None = None) -> dict:
    """One match to the end. Returns the winner, the reason, the scores, the times and every round."""
    rng = rng or random.Random()
    past: list[dict] = []
    scores = [0, 0]
    times_us = [0, 0]
    for round_no in range(1, TOTAL_ROUNDS + 1):
        values = random_values(rng)
        moves: list[dict | None] = []
        for seat, strategy in ((1, strategy_1), (2, strategy_2)):
            state = build_state(seat, round_no, values, past, scores)
            started = time.perf_counter()
            try:
                moves.append({"allocation": validate_allocation(strategy(state))})
            except (InvalidMove, Exception):  # noqa: BLE001 - an invalid or broken move is a missed turn here
                moves.append(None)
            times_us[seat - 1] += int((time.perf_counter() - started) * 1_000_000)
        if moves[0] is None or moves[1] is None:
            past.append({"number": round_no, "game_data": {"values": values}, "moves": moves, "points": None})
            if moves[0] is None and moves[1] is None:
                winner, reason = decide(tuple(scores), tuple(times_us))
            else:
                winner, reason = (2 if moves[0] is None else 1), "missed_turn"
            return {"winner_seat": winner, "reason": reason, "scores": scores, "times_us": times_us, "rounds": past}
        points = score_round(values, moves[0]["allocation"], moves[1]["allocation"])
        scores[0] += points[0]
        scores[1] += points[1]
        past.append({"number": round_no, "game_data": {"values": values}, "moves": moves, "points": list(points)})
    winner, reason = decide(tuple(scores), tuple(times_us))
    return {"winner_seat": winner, "reason": reason, "scores": scores, "times_us": times_us, "rounds": past}


def simulate(strategy_1: Strategy, strategy_2: Strategy, games: int = 100, seed: int | None = None) -> dict:
    """Many matches. Returns how often each side won, and the average scores."""
    rng = random.Random(seed)
    tally = {"games": games, "wins_1": 0, "wins_2": 0, "refunds": 0, "points_1": 0, "points_2": 0, "missed_turns_1": 0, "missed_turns_2": 0}
    for _ in range(games):
        result = play_local_match(strategy_1, strategy_2, rng)
        if result["winner_seat"] == 1:
            tally["wins_1"] += 1
        elif result["winner_seat"] == 2:
            tally["wins_2"] += 1
        else:
            tally["refunds"] += 1
        tally["points_1"] += result["scores"][0]
        tally["points_2"] += result["scores"][1]
        if result["reason"] == "missed_turn":
            tally["missed_turns_1" if result["winner_seat"] == 2 else "missed_turns_2"] += 1
    tally["win_rate_1"] = round(tally["wins_1"] / games, 3) if games else 0.0
    tally["average_points_1"] = round(tally["points_1"] / games, 1) if games else 0.0
    tally["average_points_2"] = round(tally["points_2"] / games, 1) if games else 0.0
    return tally
