"""Your strategy always returns a valid move, quickly, and doesn't mirror itself.

Run these before you enter paid games. `stratpit check` does the same from the command line.
"""

import json
from pathlib import Path

from stratpit_kit.cli import check
from stratpit_kit.rules import validate_allocation
from stratpit_kit.strategy import choose_move

EXAMPLE = json.loads((Path(__file__).parent.parent / "examples" / "state_playing.json").read_text(encoding="utf-8"))


def test_the_strategy_handles_the_example_state():
    move = choose_move(EXAMPLE)
    assert validate_allocation(move) == move


def test_the_strategy_passes_the_check():
    report = check(choose_move, samples=300)
    assert report["invalid"] == 0, report["problems"]
    assert report["slowest_seconds"] < 1.0
    assert report["ok"] is True


def test_two_copies_do_not_mirror_each_other():
    moves = {tuple(choose_move(EXAMPLE)) for _ in range(30)}
    assert len(moves) > 1
