"""Colonel Blotto, v1: the same rules the server enforces, so the simulator and the checks match it exactly.

Two bots secretly split 100 troops across 10 battlefields every round. Each battlefield
gets a random value from 1 to 10. More troops wins a battlefield and its points. Equal
troops, including 0 each, scores nothing. Ten rounds. Points, then speed, decide.
"""

import random

BATTLEFIELDS = 10
TROOPS = 100
MIN_VALUE = 1
MAX_VALUE = 10
TOTAL_ROUNDS = 10
ROUND_SECONDS = 60


class InvalidMove(ValueError):
    """An allocation the server would refuse. `reason` is the server's code."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def validate_allocation(allocation) -> list[int]:
    """Exactly ten whole numbers from 0 to 100, totalling exactly 100. Same checks, same order, as the server."""
    if not isinstance(allocation, list | tuple) or len(allocation) != BATTLEFIELDS:
        count = len(allocation) if isinstance(allocation, list | tuple) else 0
        raise InvalidMove("wrong_count", f"The allocation must have exactly {BATTLEFIELDS} numbers. Yours has {count}.")
    for troops in allocation:
        if type(troops) is not int:
            raise InvalidMove("not_whole_number", 'Every number in the allocation must be a plain whole number, like 20, not "20" or 20.0.')
    for troops in allocation:
        if troops < 0 or troops > TROOPS:
            raise InvalidMove("out_of_range", f"Every number in the allocation must be from 0 to {TROOPS}. Yours has {troops}.")
    total = sum(allocation)
    if total != TROOPS:
        raise InvalidMove("wrong_total", f"The allocation must total exactly {TROOPS}. Yours totals {total}.")
    return list(allocation)


def score_round(values: list[int], allocation_a: list[int], allocation_b: list[int]) -> tuple[int, int]:
    """The points for each side: the bot with more troops on a battlefield wins its value."""
    points_a = points_b = 0
    for value, a, b in zip(values, allocation_a, allocation_b, strict=True):
        if a > b:
            points_a += value
        elif b > a:
            points_b += value
    return points_a, points_b


def allocate(weights: list[float], total: int = TROOPS) -> list[int]:
    """Whole troops from weights, totalling exactly `total`, by largest remainder. Handy for writing strategies."""
    if len(weights) != BATTLEFIELDS or sum(weights) <= 0:
        weights = [1.0] * BATTLEFIELDS
    scale = total / sum(weights)
    exact = [w * scale for w in weights]
    troops = [int(x) for x in exact]
    short = total - sum(troops)
    for i in sorted(range(BATTLEFIELDS), key=lambda i: exact[i] - troops[i], reverse=True)[:short]:
        troops[i] += 1
    return troops


def random_values(rng: random.Random | None = None) -> list[int]:
    """This round's battlefield values. The server uses secure randomness; the simulator uses a seedable one."""
    rng = rng or random
    return [rng.randint(MIN_VALUE, MAX_VALUE) for _ in range(BATTLEFIELDS)]


def decide(scores: tuple[int, int], times_us: tuple[int, int]) -> tuple[int | None, str]:
    """The tie-breakers: points, then speed (the lower total move time). Still identical means a refund."""
    if scores[0] != scores[1]:
        return (1 if scores[0] > scores[1] else 2), "points"
    if times_us[0] != times_us[1]:
        return (1 if times_us[0] < times_us[1] else 2), "speed"
    return None, "tie_refund"
