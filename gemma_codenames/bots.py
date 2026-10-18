"""Adapters for real inference and explicitly selected, deterministic demo mode."""

import hashlib
from threading import Lock

import numpy as np

from .board import Card
from .communication import CommunicationConfig
from .optimizer import SearchConfig
from .service import EmbeddingService


class DemoEncoder:
    """Synthetic vectors for UI testing. Never used as a model-error fallback."""

    metadata = {"model_id": "demo-fixture", "resolved_revision": "1", "dimensions": 24}

    def encode(self, words):
        vectors = []
        for word in words:
            seed = int.from_bytes(hashlib.sha256(word.lower().encode()).digest()[:8], "big")
            vectors.append(np.random.default_rng(seed).normal(size=24))
        return np.asarray(vectors, dtype=np.float32)


class BotService:
    def __init__(self, service: EmbeddingService, mode="gemma", config=None):
        self.service = service
        self.mode = mode
        self.config = config or SearchConfig()
        self.lock = Lock()

    def propose(self, board: list[dict], team: str, progress=None, geometry=False, communication=None) -> dict:
        cards = [Card(c["word"], c["kind"], c["revealed"]) for c in board]
        with self.lock:
            result = self.service.communicate(cards, team, CommunicationConfig(**(communication or {})), progress)
        best = result["best"]
        scores = {row["word"]: row["similarity"] for row in best["rankings"]}

        def detail(value):
            return {"word": value["word"].upper(), "score": value["similarity"]} if value else None

        return {
            "word": best["clue"], "count": best["count"], "team": team,
            "message": result["communication"]["message"],
            "plot": result["plot"],
            "scores": {c["id"]: scores[c["word"].lower()] for c in board
                       if c["word"].lower() in scores},
            "analysis": {
                "heatmap": result["heatmap"], "geometry": result["communication"]["ideal"],
                "communication": result["communication"],
                "matrixShape": result["matrix_shape"], "elapsed": result["elapsed_seconds"],
                "legalCandidates": result["legal_candidates"],
                "requiredThreshold": best["required_threshold"],
                "source": self.mode, "summary": result["explanation"],
                "targets": [word.upper() for word in best["targets"]],
                "weakestTarget": detail(best["weakest_target"]),
                "closestDanger": detail(best["closest_danger"]),
                "limitingDanger": detail(best["closest_danger"]),
                "gap": best["raw_gap"], "safetySlack": best["safety_slack"],
                "fallback": result["fallback"], "coverageChecks": [],
                "alternatives": [{"word": p["clue"], "count": p["count"]}
                                 for p in []],
                "model": result["model"], "config": result["config"],
            },
        }

    def score(self, clue: str, board: list[dict]) -> dict:
        # The caller passes only public fields, even for human spymaster clues.
        with self.lock:
            result = self.service.inspect_clue(clue, [c["word"] for c in board])
        return {"scores": {c["id"]: result["scores"][c["word"]] for c in board},
                "plot": result["plot"]}


def choose_guess(cards: list[dict], clue: dict, guesses: int, source: str) -> dict:
    """This function has no access to a hidden key or spymaster targets."""
    if guesses >= clue["count"]:
        return {"cardId": None, "reason": "Reached the clue count. Ending the turn."}
    available = [c for c in cards if not c["revealed"]]
    best = max(available, key=lambda c: clue["scores"][c["id"]])
    label = "demo score" if source == "demo" else "cosine similarity"
    return {"cardId": best["id"], "reason": (
        f"{best['word']} has the highest remaining {label} "
        f"({clue['scores'][best['id']]:.3f})."
    )}
