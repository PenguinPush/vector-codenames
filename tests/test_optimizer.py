from itertools import combinations

import numpy as np
import pytest

from gemma_codenames.board import Card, load_words, random_board
from gemma_codenames.optimizer import CluePolicy, SearchConfig, cosine_matrix, optimize


def test_coverage_beats_mean_and_weak_target_cannot_hide():
    board = [Card("planet", "red"), Card("moon", "red"), Card("comet", "blue")]
    result = optimize(["orbit", "space"], board, [[0.99, 0.52, 0.60], [0.76, 0.75, 0.60]])
    assert result["best"]["clue"] == "space"
    assert result["best"]["count"] == 2
    assert result["alternatives"][0]["count"] == 1


def test_margin_then_mean_then_deterministic_name_break_ties():
    board = [Card("planet", "red"), Card("moon", "red"), Card("comet", "blue")]
    result = optimize(
        ["orbit", "space", "cosmos", "galaxy"],
        board,
        [[0.99, 0.70, 0.60], [0.80, 0.75, 0.60], [0.90, 0.75, 0.60], [0.90, 0.75, 0.60]],
    )
    assert result["best"]["clue"] == "cosmos"
    assert [p["clue"] for p in result["alternatives"]] == ["galaxy", "space", "orbit"]


def test_assassin_can_limit_even_when_not_closest_raw_danger():
    board = [
        Card("planet", "red"),
        Card("moon", "red"),
        Card("comet", "blue"),
        Card("rocket", "assassin"),
    ]
    config = SearchConfig(assassin_margin=0.15)
    result = optimize(["orbit"], board, [[0.90, 0.74, 0.65, 0.62]], config=config)
    assert result["best"]["count"] == 1
    assert result["best"]["closest_danger"]["word"] == "comet"
    assert result["best"]["limiting_danger"]["word"] == "rocket"
    assert result["best"]["danger_threshold"] == pytest.approx(0.77)
    assert result["coverage_checks"][1]["feasible"] is False


def test_fallback_is_explicit_and_does_not_relax_thresholds():
    board = [Card("planet", "red"), Card("rocket", "assassin")]
    result = optimize(["orbit", "space"], board, [[0.80, 0.85], [0.45, 0.10]])
    assert result["fallback"] is True
    assert result["maximum_safe_count"] == 0
    assert result["best"]["clue"] == "space"
    assert result["best"]["qualified"] is False
    assert result["best"]["failed_constraints"] == ["minimum_similarity"]


def test_boundary_qualifies_and_revealed_cards_are_ignored():
    board = [Card("planet", "red"), Card("rocket", "assassin"), Card("moon", "red", True)]
    result = optimize(
        ["moon"], board, [[0.75, 0.5, 0.99]], config=SearchConfig(assassin_margin=0.25)
    )
    assert result["maximum_safe_count"] == 1
    assert len(result["best"]["rankings"]) == 2
    assert result["best"]["safety_slack"] == 0


def test_no_dangers_is_json_safe_and_has_no_gap():
    result = optimize(["orbit"], [Card("planet", "red")], [[0.8]])
    assert result["best"]["count"] == 1
    assert result["best"]["raw_gap"] is None
    assert result["best"]["danger_threshold"] is None


def test_blue_targets_and_revealed_enemy():
    result = optimize(
        ["orbit"], [Card("planet", "blue"), Card("rocket", "red", True)], [[0.8, 0.99]], team="blue"
    )
    assert result["best"]["targets"] == ["planet"]


def test_illegal_words_stems_compounds_and_duplicate_board():
    board = [Card("planet", "red"), Card("star", "blue"), Card("running", "neutral")]
    policy = CluePolicy(board)
    for word in ["planet", "planets", "starfish", "run", "two words", "42"]:
        assert not policy.allows(word)
    result = optimize(["planets", "orbit"], board, [[0.99, 0.1, 0.1], [0.8, 0.2, 0.2]])
    assert result["excluded_candidates"] == 1
    assert result["best"]["clue"] == "orbit"
    with pytest.raises(ValueError, match="No legal"):
        optimize(["planet"], board, [[0.8, 0.2, 0.2]])
    with pytest.raises(ValueError, match="unique"):
        optimize(["orbit"], [Card("MOON", "red"), Card("moon", "blue")], [[0.8, 0.2]])


@pytest.mark.parametrize("scores", [[[float("nan"), 0.2]], [[1.2, 0.2]], [[0.2]]])
def test_invalid_scores_rejected(scores):
    with pytest.raises(ValueError):
        optimize(["orbit"], [Card("planet", "red"), Card("rocket", "blue")], scores)


def test_no_friendly_cards_rejected():
    with pytest.raises(ValueError, match="no unrevealed"):
        optimize(["orbit"], [Card("planet", "red", True)], [[0.8]])


def test_cosine_normalizes_inputs_and_rejects_zero_vectors():
    np.testing.assert_allclose(cosine_matrix([[2, 0]], [[4, 0], [0, 3], [-2, 0]]), [[1, 0, -1]])
    with pytest.raises(ValueError, match="nonzero"):
        cosine_matrix([[0, 0]], [[1, 0]])


def test_random_boards_are_seeded_with_standard_distribution():
    board = random_board(load_words(), 42)
    assert board == random_board(load_words(), 42)
    assert board != random_board(load_words(), 43)
    assert len({card.word for card in board}) == 25
    assert [
        sum(card.kind == kind for card in board) for kind in ("red", "blue", "neutral", "assassin")
    ] == [9, 8, 7, 1]
    assert sum(c.kind == "blue" for c in random_board(load_words(), 42, "blue")) == 9


def test_exact_search_matches_exhaustive_target_subsets():
    """Independent oracle enumerates every subset, not the optimizer's prefix method."""
    rng = np.random.default_rng(2026)
    board = [Card(w, "red") for w in ["planet", "moon", "glass", "spoon"]]
    board += [Card("comet", "blue"), Card("tree", "neutral"), Card("rocket", "assassin")]
    candidates = ["alpha", "beta", "gamma", "delta", "epsilon"]
    config = SearchConfig()
    for _ in range(100):
        scores = rng.uniform(0.1, 0.95, (len(candidates), len(board)))
        options = []
        for row, clue in enumerate(candidates):
            danger = max(scores[row, i] + config.margin(board[i].kind) for i in range(4, 7))
            for k in range(1, 5):
                for subset in combinations(range(4), k):
                    weakest = min(scores[row, i] for i in subset)
                    if weakest >= max(config.min_similarity, danger):
                        mean = np.mean([scores[row, i] for i in subset])
                        options.append(((-k, -(weakest - danger), -mean, clue), clue, k))
        result = optimize(candidates, board, scores, config=config)
        if options:
            _, clue, k = min(options)
            assert result["best"]["clue"] == clue
            assert result["best"]["count"] == k
            assert not result["fallback"]
        else:
            assert result["fallback"]
