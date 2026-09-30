"""The rules in the kit match the server's: same checks, same scoring, same tie-breakers."""

import pytest
from stratpit_kit.rules import InvalidMove, allocate, decide, score_round, validate_allocation

SPEC_ROUND_VALUES = [6, 2, 9, 4, 10, 1, 8, 3, 5, 7]
SPEC_MOVE_A = [10, 0, 20, 5, 25, 0, 20, 0, 5, 15]
SPEC_MOVE_B = [12, 5, 15, 8, 20, 5, 15, 5, 5, 10]


def test_a_legal_allocation():
    assert validate_allocation([10] * 10) == [10] * 10
    assert validate_allocation((100, 0, 0, 0, 0, 0, 0, 0, 0, 0)) == [100] + [0] * 9


@pytest.mark.parametrize(
    "allocation, reason",
    [
        ([10] * 9, "wrong_count"),
        ([10] * 11, "wrong_count"),
        ("10,10,10,10,10,10,10,10,10,10", "wrong_count"),
        (["20"] + [10] * 8 + [0], "not_whole_number"),
        ([20.0] + [10] * 8 + [0], "not_whole_number"),
        ([True] + [11] * 9, "not_whole_number"),
        ([-1, 11] + [10] * 8, "out_of_range"),
        ([101] + [0] * 9, "out_of_range"),
        ([10] * 9 + [5], "wrong_total"),
        ([0] * 10, "wrong_total"),
    ],
)
def test_illegal_allocations(allocation, reason):
    with pytest.raises(InvalidMove) as error:
        validate_allocation(allocation)
    assert error.value.reason == reason


def test_scoring_matches_the_published_example():
    assert score_round(SPEC_ROUND_VALUES, SPEC_MOVE_A, SPEC_MOVE_B) == (34, 16)
    assert score_round([10] * 10, [10] * 10, [10] * 10) == (0, 0)


def test_allocate_always_totals_100():
    assert allocate([1.0] * 10) == [10] * 10
    assert sum(allocate([7.1, 0.9, 3.3, 5.5, 2.2, 0.0, 9.9, 1.1, 4.4, 6.6])) == 100
    assert allocate([0.0] * 10) == [10] * 10
    assert allocate([100.0] + [0.0] * 9) == [100] + [0] * 9


def test_tie_breakers():
    assert decide((238, 202), (1, 2)) == (1, "points")
    assert decide((10, 20), (1, 2)) == (2, "points")
    assert decide((10, 10), (5000, 4000)) == (2, "speed")
    assert decide((10, 10), (4000, 4000)) == (None, "tie_refund")
