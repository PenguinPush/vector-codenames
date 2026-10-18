import json

import numpy as np
import pytest

from gemma_codenames.board import Card
from gemma_codenames.geometry import ideal_direction, projection
from gemma_codenames.optimizer import SearchConfig


def test_pca_preserves_two_dimensional_distances_and_projects_clue_consistently():
    vectors = np.array([[1, 0], [0, 1], [-1, 0], [0, -1]])
    result = projection(['a', 'b', 'c', 'd'], vectors, [('clue', vectors[0])])
    xy = np.array([[p['x'], p['y']] for p in result['points']])
    np.testing.assert_allclose(xy[0], xy[-1])
    for i in range(4):
        for j in range(4):
            assert np.linalg.norm(xy[i] - xy[j]) == pytest.approx(
                np.linalg.norm(vectors[i] - vectors[j]))
    assert result['variance'] == pytest.approx(1)
    json.dumps(result, allow_nan=False)


def test_continuous_bound_dominates_every_discrete_qualifying_direction():
    pytest.importorskip('cvxpy')
    rng = np.random.default_rng(42)
    vectors = np.array([[1., .1, 0], [1, -.1, 0], [0, 1, 0]])
    vocabulary_vectors = rng.normal(size=(100, 3))
    vocabulary = [f'word{i}' for i in range(100)]
    board = [Card('moon', 'red'), Card('planet', 'red'), Card('rocket', 'assassin')]
    config = SearchConfig(min_similarity=.3)
    result = ideal_direction(vectors, board, 'red', config, vocabulary_vectors, vocabulary)
    assert result['status'] == 'optimal'
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    vocabulary_vectors /= np.linalg.norm(vocabulary_vectors, axis=1, keepdims=True)
    scores = vocabulary_vectors @ vectors.T
    feasible = scores[:, :2].min(axis=1) >= config.min_similarity
    gap = scores[feasible, :2].min(axis=1) - scores[feasible, 2] - config.assassin_margin
    assert result['upper_bound'] >= gap.max() - 1e-6
    assert result['norm'] <= 1 + 1e-6


def test_identical_target_and_danger_cannot_have_positive_margin():
    pytest.importorskip('cvxpy')
    board = [Card('moon', 'red'), Card('rocket', 'assassin')]
    vectors = np.array([[1., 0], [1., 0]])
    result = ideal_direction(vectors, board, 'red', SearchConfig(), vectors, ['moon', 'rocket'])
    assert result['status'] == 'optimal'
    assert result['upper_bound'] == pytest.approx(-.07, abs=1e-6)
