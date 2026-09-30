"""Your strategy. This is the one file to change.

`choose_move` gets the match state, exactly as the server sends it (see examples/state_playing.json),
and returns this round's allocation: ten whole numbers, one per battlefield in order, totalling 100.

What's in the state:
- state["match"]["round"]["game_data"]["values"]: this round's ten battlefield values, 1 to 10 each.
- state["match"]["past_rounds"]: every round so far, each with its values, both moves and the points.
- state["match"]["you"]["score"] and state["match"]["opponent"]["score"]: the totals so far.
- state["match"]["opponent"]["wallet"]: who you're playing, or None with house_bot True.

Keep it fast. A turn lasts 60 seconds, and the kit sends your move the moment you return.
Run `stratpit check` to make sure your moves are always valid and quick.
"""

import random

from stratpit_kit.rules import allocate


def choose_move(state: dict) -> list[int]:
    values = state["match"]["round"]["game_data"]["values"]

    # The starter plan: troops in proportion to each battlefield's value, with a little
    # randomness so two unchanged copies of this bot don't mirror each other every round.
    # It's deliberately simple. Beat it.
    weights = [value * random.uniform(0.8, 1.2) for value in values]
    return allocate(weights)
