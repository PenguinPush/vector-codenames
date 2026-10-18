"""Exact lexicographic optimization over a finite vocabulary and cosine matrix."""

import math
import re
from dataclasses import dataclass

import numpy as np
import snowballstemmer

from .board import WORD, Card, Team, validate_board


@dataclass(frozen=True)
class SearchConfig:
    # Starting values for experiments, not calibrated human-error probabilities.
    min_similarity: float = 0.50
    neutral_margin: float = 0.02
    opponent_margin: float = 0.035
    assassin_margin: float = 0.07

    def __post_init__(self):
        if not math.isfinite(self.min_similarity) or not -1 <= self.min_similarity <= 1:
            raise ValueError("Minimum similarity must be finite and between -1 and 1.")
        for margin in (self.neutral_margin, self.opponent_margin, self.assassin_margin):
            if not math.isfinite(margin) or not 0 < margin <= 2:
                raise ValueError("Safety margins must be finite, greater than 0, and at most 2.")

    def margin(self, kind: str) -> float:
        if kind == "assassin":
            return self.assassin_margin
        return self.neutral_margin if kind == "neutral" else self.opponent_margin


class CluePolicy:
    """Conservative English spelling policy, not a complete semantic rules judge."""

    def __init__(self, board: list[Card]):
        self.stemmer = snowballstemmer.stemmer("english")
        self.words = sorted({part for card in board if not card.revealed
                             for part in [card.word, *re.findall(r"[a-z]+", card.word)]})
        self.stems = {self.stemmer.stemWord(word) for word in self.words}

    def allows(self, clue: str) -> bool:
        if not WORD.fullmatch(clue):
            return False
        parts = [clue, *re.findall(r"[a-z]+", clue)]
        if any(self.stemmer.stemWord(part) in self.stems for part in parts):
            return False
        # Catch obvious compound reuse; this intentionally also rejects some legal words.
        return not any(
            (len(word) >= 4 and word in clue) or (len(clue) >= 4 and clue in word)
            for word in self.words
        )


def cosine_matrix(clues: np.ndarray, board: np.ndarray) -> np.ndarray:
    def normalize(values):
        values = np.asarray(values, dtype=np.float64)
        if values.ndim != 2 or not np.isfinite(values).all():
            raise ValueError("Embeddings must be a finite two-dimensional matrix.")
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if values.shape[1] == 0 or np.any(norms == 0):
            raise ValueError("Embedding vectors must have nonzero length.")
        return values / norms

    left, right = normalize(clues), normalize(board)
    if left.shape[1] != right.shape[1]:
        raise ValueError("Clue and board embeddings must have the same dimension.")
    return np.clip(left @ right.T, -1, 1)


def optimize(
    candidates: list[str],
    board: list[Card],
    scores: np.ndarray,
    team: Team = "red",
    config: SearchConfig = SearchConfig(),
    top_n: int = 5,
) -> dict:
    """Scores have one row per clue and one column per card, including revealed cards.

    The top-k friendly scores maximize the weakest score for every fixed k, so
    examining their prefixes is equivalent to searching every target subset.
    """
    validate_board(board, team)
    if not 1 <= top_n <= 100:
        raise ValueError("top_n must be between 1 and 100.")
    candidates = [word.strip().lower() for word in candidates]
    if not candidates or len(set(candidates)) != len(candidates):
        raise ValueError("Supply a nonempty list of unique candidate clues.")
    scores = np.asarray(scores, dtype=np.float64)
    if scores.shape != (len(candidates), len(board)):
        raise ValueError("Similarity matrix must have shape (candidate count, board size).")
    if not np.isfinite(scores).all() or np.any(np.abs(scores) > 1 + 1e-6):
        raise ValueError("Cosine similarities must be finite and within [-1, 1].")
    scores = np.clip(scores, -1, 1)
    policy = CluePolicy(board)
    legal = [i for i, word in enumerate(candidates) if policy.allows(word)]
    if not legal:
        raise ValueError("No legal clue candidates remain for this board.")
    friendly = [i for i, card in enumerate(board) if not card.revealed and card.kind == team]
    unsafe = [i for i, card in enumerate(board) if not card.revealed and card.kind != team]
    values = scores[legal]
    sorted_friendly = np.sort(values[:, friendly], axis=1)[:, ::-1]
    if unsafe:
        danger = np.max(
            values[:, unsafe] + np.array([config.margin(board[i].kind) for i in unsafe]),
            axis=1,
        )
    else:
        # No dangerous cards remain. -1 is the lowest possible cosine score.
        danger = np.full(len(legal), -1.0)
    thresholds = np.maximum(config.min_similarity, danger)
    coverage = np.sum(sorted_friendly >= thresholds[:, None], axis=1)
    feasible = [row for row, count in enumerate(coverage) if count > 0]
    fallback = not feasible

    def key(row):
        k = int(coverage[row]) if not fallback else 1
        weakest = float(sorted_friendly[row, k - 1])
        # A fallback maximizes separation even if the similarity floor is unmet.
        return (
            -k,
            -(weakest - danger[row]),
            -float(sorted_friendly[row, :k].mean()),
            candidates[legal[row]],
        )

    ranked = sorted(feasible if feasible else range(len(legal)), key=key)

    def proposal(row):
        source = legal[row]
        s = scores[source]
        k = int(coverage[row]) if not fallback else 1
        ordered = sorted(friendly, key=lambda i: (-s[i], board[i].word))
        targets = ordered[:k]
        weakest = targets[-1]
        closest = max(unsafe, key=lambda i: s[i]) if unsafe else None
        limiting = (
            max(unsafe, key=lambda i: s[i] + config.margin(board[i].kind)) if unsafe else None
        )

        def detail(index):
            if index is None:
                return None
            return {
                "word": board[index].word,
                "kind": board[index].kind,
                "similarity": float(s[index]),
            }

        failed = []
        if s[weakest] < config.min_similarity:
            failed.append("minimum_similarity")
        if s[weakest] < danger[row]:
            failed.append("danger_margin")
        return {
            "clue": candidates[source],
            "count": k,
            "qualified": not fallback,
            "targets": [board[i].word for i in targets],
            "weakest_target": detail(weakest),
            "closest_danger": detail(closest),
            "limiting_danger": detail(limiting),
            "danger_threshold": float(danger[row]) if unsafe else None,
            "required_threshold": float(thresholds[row]),
            "raw_gap": float(s[weakest] - s[closest]) if closest is not None else None,
            "safety_slack": float(s[weakest] - danger[row]) if unsafe else None,
            "mean_target_similarity": float(s[targets].mean()),
            "failed_constraints": failed,
            "rankings": [
                {**detail(i), "target": i in targets}
                for i in sorted(
                    (i for i, card in enumerate(board) if not card.revealed),
                    key=lambda i: (-s[i], board[i].word),
                )
            ],
        }

    maximum = int(coverage.max())
    # A witness for each k: best available minimum slack after BOTH constraints.
    coverage_checks = []
    for k in range(1, len(friendly) + 1):
        slacks = sorted_friendly[:, k - 1] - thresholds
        witness = int(np.argmax(slacks))
        coverage_checks.append(
            {
                "count": k,
                "feasible": bool(slacks[witness] >= 0),
                "best_constraint_slack": float(slacks[witness]),
                "best_candidate": candidates[legal[witness]],
            }
        )
    return {
        "team": team,
        "legal_candidates": len(legal),
        "excluded_candidates": len(candidates) - len(legal),
        "friendly_remaining": len(friendly),
        "maximum_safe_count": maximum,
        "fallback": fallback,
        "explanation": (
            "No clue satisfies the thresholds, even for one target. This is the "
            "single-target fallback with the best danger separation; it may fail."
            if fallback
            else f"Selected the largest qualifying group ({maximum}), then the greatest "
            "danger-margin slack, then mean target similarity."
        ),
        "best": proposal(ranked[0]),
        "alternatives": [proposal(row) for row in ranked[1:top_n]],
        "coverage_checks": coverage_checks,
    }
