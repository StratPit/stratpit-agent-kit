"""The house bot, as a sparring partner. The same mix of plans it uses in practice games at StratPit.

One level, with a fixed strength. It picks one of several simple plans at random each
round, so it can't be beaten by learning one pattern. Beat it consistently in the
simulator before you risk money.
"""

import random

from stratpit_kit.rules import BATTLEFIELDS, allocate


def proportional(values, past_rounds, rng):
    return [v * rng.uniform(0.8, 1.2) for v in values]


def top_heavy(values, past_rounds, rng):
    keep = rng.randint(4, 6)
    ranked = sorted(range(BATTLEFIELDS), key=lambda i: (-values[i], rng.random()))
    chosen = set(ranked[:keep])
    return [v * rng.uniform(1.0, 2.0) if i in chosen else 0.05 * v for i, v in enumerate(values)]


def spread(values, past_rounds, rng):
    return [1 + v / 10 + rng.uniform(0, 0.5) for v in values]


def counter(values, past_rounds, rng):
    last = past_rounds[-1]["opponent_move"]["allocation"]
    return [v * (1 + rng.uniform(0, 0.3)) / (1 + last[i] / 10) for i, v in enumerate(values)]


def house_bot_move(state: dict, rng: random.Random | None = None) -> list[int]:
    """This round's allocation, the way the house bot would choose it."""
    rng = rng or random.Random()
    values = state["match"]["round"]["game_data"]["values"]
    past_rounds = state["match"]["past_rounds"]
    plans = [proportional, top_heavy, spread]
    if past_rounds and past_rounds[-1].get("opponent_move") is not None:
        plans.append(counter)
    plan = rng.choice(plans)
    return allocate(plan(values, past_rounds, rng))
