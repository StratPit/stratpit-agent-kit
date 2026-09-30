"""The local simulator plays by the rules, and the house bot is a real opponent."""

from stratpit_kit.house_bot import house_bot_move
from stratpit_kit.rules import validate_allocation
from stratpit_kit.simulator import build_state, play_local_match, simulate
from stratpit_kit.strategy import choose_move


def even(state):
    return [10] * 10


def all_on_one(state):
    return [100] + [0] * 9


def broken(state):
    raise RuntimeError("no idea")


def test_a_match_has_ten_rounds_and_a_winner():
    result = play_local_match(even, all_on_one)
    assert len(result["rounds"]) == 10
    assert result["winner_seat"] == 1 and result["reason"] == "points"
    assert all(r["points"] is not None for r in result["rounds"])


def test_the_state_looks_like_the_real_one():
    state = build_state(2, 3, [1] * 10, [], [12, 30])
    assert state["status"] == "playing"
    assert state["match"]["round"]["number"] == 3
    assert state["match"]["you"] == {"seat": 2, "wallet": "seat-2", "score": 30}
    assert state["match"]["opponent"]["score"] == 12
    assert state["match"]["round"]["game_data"]["values"] == [1] * 10
    assert state["match"]["past_rounds"] == []


def test_a_broken_strategy_misses_its_turn():
    result = play_local_match(broken, even)
    assert result["winner_seat"] == 2 and result["reason"] == "missed_turn"
    assert len(result["rounds"]) == 1 and result["rounds"][0]["points"] is None


def test_the_same_seed_gives_the_same_match():
    first = play_local_match(even, all_on_one, __import__("random").Random(7))
    second = play_local_match(even, all_on_one, __import__("random").Random(7))
    assert first["rounds"] == second["rounds"]


def test_simulate_reports_a_tally():
    report = simulate(even, all_on_one, games=20, seed=1)
    assert report["games"] == 20
    assert report["wins_1"] + report["wins_2"] + report["refunds"] == 20
    assert report["wins_1"] == 20
    assert 0 <= report["win_rate_1"] <= 1


def test_the_house_bot_always_moves_legally_and_mixes_it_up():
    state = build_state(1, 1, [3, 10, 1, 7, 7, 2, 9, 5, 10, 4], [], [0, 0])
    moves = set()
    for _ in range(100):
        move = house_bot_move(state)
        validate_allocation(move)
        moves.add(tuple(move))
    assert len(moves) > 20


def test_the_starter_bot_is_beatable_but_not_hopeless():
    report = simulate(choose_move, house_bot_move, games=60, seed=3)
    assert 0.15 < report["win_rate_1"] < 0.85
