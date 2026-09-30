"""The command line.

    stratpit play                 a free practice game against the house bot, with your strategy
    stratpit simulate             your strategy against the house bot, locally, 100 games
    stratpit check                your strategy always returns a valid move, quickly

`python -m stratpit_kit ...` works the same.
"""

import argparse
import json
import random
import sys
import time

from stratpit_kit.client import StratPitClient, StratPitError
from stratpit_kit.house_bot import house_bot_move
from stratpit_kit.play import play_match, play_practice, summary
from stratpit_kit.rules import InvalidMove, validate_allocation
from stratpit_kit.simulator import build_state, random_values, simulate
from stratpit_kit.strategy import choose_move
from stratpit_kit.wallet import load_wallet


def log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def check(strategy=choose_move, samples: int = 200, max_seconds: float = 1.0) -> dict:
    """Runs the strategy on random states and reports invalid moves and slow ones."""
    rng = random.Random(1)
    invalid = 0
    slowest = 0.0
    problems: list[str] = []
    for i in range(samples):
        values = random_values(rng)
        state = build_state(1, 1 + i % 10, values, [], [0, 0])
        started = time.perf_counter()
        try:
            validate_allocation(strategy(state))
        except InvalidMove as error:
            invalid += 1
            if len(problems) < 5:
                problems.append(f"values {values}: {error.reason}, {error.message}")
        except Exception as error:  # noqa: BLE001
            invalid += 1
            if len(problems) < 5:
                problems.append(f"values {values}: {type(error).__name__}: {error}")
        slowest = max(slowest, time.perf_counter() - started)
    return {
        "samples": samples,
        "invalid": invalid,
        "slowest_seconds": round(slowest, 4),
        "ok": invalid == 0 and slowest <= max_seconds,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stratpit", description="Play at StratPit, or test your strategy locally.")
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="play a match with your strategy")
    play.add_argument("--practice", action="store_true", default=True, help="a free practice game (the default)")
    play.add_argument("--token", help="carry on a match you already entered, with its match token")
    play.add_argument("--base-url", help="the API address (default https://StratPit.com/api/v1)")
    play.add_argument("--key", help="your wallet key (default: STRATPIT_WALLET_KEY, or .env)")
    play.add_argument("--source", default="kit", help="where you found StratPit, for the first entry")

    sim = sub.add_parser("simulate", help="your strategy against the house bot, locally")
    sim.add_argument("--games", type=int, default=100)
    sim.add_argument("--against", choices=["house", "self"], default="house")
    sim.add_argument("--seed", type=int)

    sub.add_parser("check", help="your strategy always returns a valid move, quickly")

    args = parser.parse_args(argv)

    if args.command == "check":
        report = check()
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if args.command == "simulate":
        opponent = house_bot_move if args.against == "house" else choose_move
        report = simulate(choose_move, opponent, games=args.games, seed=args.seed)
        print(json.dumps(report, indent=2))
        return 0

    try:
        wallet = load_wallet(args.key)
    except ValueError as error:
        log(str(error))
        return 2
    with StratPitClient(args.base_url) as client:
        try:
            if args.token:
                final = play_match(client, args.token, choose_move, log)
            else:
                final = play_practice(client, wallet, choose_move, args.source, log)
        except StratPitError as error:
            log(f"StratPit said no: {error.code}: {error.message}")
            return 1
    result = summary(final)
    log(
        f"finished: {result['status']}, {result['winner'] or 'no winner'} ({result['reason']}), {result['your_score']}–{result['opponent_score']}"
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
