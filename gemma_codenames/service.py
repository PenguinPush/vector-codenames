from dataclasses import asdict
import os
import time


from .geometry import projection, ideal_direction

from .board import Card, Team, validate_board, load_words
from importlib.resources import files
from .embeddings import CachedEncoder, Encoder, GemmaEncoder, ModelConfig
from .optimizer import SearchConfig, cosine_matrix, optimize


class EmbeddingService:
    """Reusable model-backed service, independently callable by CLI or HTTP."""

    def __init__(self, encoder: Encoder, vocabulary: list[str]):
        self.encoder = encoder
        self.vocabulary = sorted(set(word.strip().lower() for word in vocabulary))
        if not self.vocabulary:
            raise ValueError("Clue vocabulary cannot be empty.")
        self._vocabulary_vectors = None
        self._common_service = None

    @classmethod
    def from_gemma(cls, vocabulary: list[str], config: ModelConfig = ModelConfig()):
        precomputed = os.environ.get("GEMMA_EMBEDDINGS_FILE")
        if precomputed:
            from .precomputed import PrecomputedEncoder, HybridEncoder
            encoder = HybridEncoder(PrecomputedEncoder(precomputed, model_id=config.model_id, revision=config.revision), config)
        else:
            encoder = CachedEncoder(GemmaEncoder(config), config.cache_dir / "embeddings")
        return cls(encoder, vocabulary)

    def _encode(self, words, progress=None):
        from .precomputed import HybridEncoder
        if isinstance(self.encoder, (CachedEncoder, HybridEncoder)):
            return self.encoder.encode(words, progress=progress)
        return self.encoder.encode(words)

    def propose_clue(
        self,
        board: list[Card],
        team: Team = "red",
        config: SearchConfig = SearchConfig(),
        top_n: int = 5,
        progress=None,
        geometry=False,
    ) -> dict:
        started = time.perf_counter()
        notify = progress or (lambda stage: None)
        validate_board(board, team)
        notify("Encoding vocabulary · loading Gemma or reading cached embeddings")
        if self._vocabulary_vectors is None:
            self._vocabulary_vectors = self._encode(self.vocabulary, notify)
        notify("Encoding board · same STS prompt, normalized vectors")
        board_vectors = self._encode([card.word for card in board], notify)
        notify("Computing cosine matrix · C × Bᵀ")
        scores = cosine_matrix(self._vocabulary_vectors, board_vectors)
        notify("Searching every legal clue · coverage, separation, then mean similarity")
        result = optimize(self.vocabulary, board, scores, team, config, top_n)
        notify("Projecting embeddings · PCA for display only")
        chosen = self.vocabulary.index(result["best"]["clue"])
        plot = projection([c.word for c in board], board_vectors,
                          [(result["best"]["clue"], self._vocabulary_vectors[chosen])])
        experiment = {"status": "disabled", "note": "Enable the ideal-direction experiment when creating a room."}
        if geometry:
            notify("Solving ideal direction · continuous upper bound")
            experiment = ideal_direction(board_vectors, board, team, config,
                                         self._vocabulary_vectors, self.vocabulary)
            # Never serialize a high-dimensional vector into the game payload.
            experiment.pop("vector", None)
        proposals = [result["best"], *result["alternatives"]]
        heatmap = {"words": [c.word.upper() for c in board], "rows": [
            {"clue": p["clue"], "count": p["count"],
             "scores": scores[self.vocabulary.index(p["clue"])].tolist()}
            for p in proposals]}
        return {
            "plot": plot, "heatmap": heatmap, "geometry": experiment,
            "elapsed_seconds": time.perf_counter() - started,
            "matrix_shape": list(scores.shape),
            "model": self.encoder.metadata,
            "config": asdict(config),
            "board": [asdict(card) for card in board],
            **result,
        }

    def score_clue(self, clue: str, words: list[str]) -> dict[str, float]:
        """Score a human clue using public words only; no hidden key is needed."""
        query = self.encoder.encode([clue.lower()])
        vectors = self.encoder.encode([word.lower() for word in words])
        values = cosine_matrix(query, vectors)[0]
        return {word: float(score) for word, score in zip(words, values)}

    def inspect_clue(self, clue: str, words: list[str]) -> dict:
        query = self.encoder.encode([clue.lower()])
        vectors = self.encoder.encode([word.lower() for word in words])
        values = cosine_matrix(query, vectors)[0]
        return {"scores": {word: float(score) for word, score in zip(words, values)},
                "plot": projection(words, vectors, [(clue, query[0])])}

    def decode_message(self, message: dict, public_words: list[str]) -> dict:
        """Independent receiver: only the wire message, model, and public board words."""
        from .communication import decode_vectors, identity
        if message.get("model") != identity(self.encoder.metadata):
            raise ValueError("Encoder and decoder model identities differ")
        words = [c["word"] for c in message["components"]]
        from .board import WORD
        if any(not isinstance(w, str) or not WORD.fullmatch(w) for w in words):
            raise ValueError("Message components must be single words")
        components = self.encoder.encode(words)
        direction = decode_vectors(message, components)
        board_vectors = self.encoder.encode([w.lower() for w in public_words])
        values = cosine_matrix([direction], board_vectors)[0]
        return {"scores": values, "vector": direction, "component_vectors": components,
                "board_vectors": board_vectors}

    def communicate(self, board, team, config, progress=None):
        """Encode, serialize, then independently decode a bot-only vector message."""
        import json
        import numpy as np
        from .communication import evaluate, identity, search
        from .geometry import normalized
        from .transmission_plot import transmission_projection

        if config.common_words_only and self._common_service is None:
            common = set(load_words(files(__package__).joinpath("data/clue_words_common.csv"), clues=True))
            vocabulary = [w for w in self.vocabulary if w in common]
            self._common_service = EmbeddingService(self.encoder, vocabulary)
        if config.common_words_only:
            result = self._common_service.communicate(
                board, team, config.model_copy(update={"common_words_only": False}), progress)
            result["config"]["common_words_only"] = True
            result["communication"]["config"]["common_words_only"] = True
            return result

        start = time.perf_counter()
        notify = progress or (lambda stage: None)
        validate_board(board, team)
        notify("Embedding vocabulary and board · loading Gemma or cached vectors")
        if self._vocabulary_vectors is None:
            self._vocabulary_vectors = self._encode(self.vocabulary, notify)
        board_vectors = self._encode([c.word for c in board], notify)
        report = search(self.vocabulary, self._vocabulary_vectors, board, board_vectors,
                        team, config, notify)
        encoded = report.pop("_encoded_vector")
        ideal_vector = report.pop("_ideal_vector")
        report["message"]["model"] = identity(self.encoder.metadata)
        # Simulate the real wire boundary: no private arrays or target labels cross it.
        packet = json.dumps(report["message"], sort_keys=True, allow_nan=False)
        message = json.loads(packet)
        notify("Decoding transmitted words and coefficients · no hidden key supplied")
        received = self.decode_message(message, [c.word for c in board])
        direction = received["vector"]
        friendly = np.array([i for i, c in enumerate(board) if c.kind == team and not c.revealed])
        danger = np.array([i for i, c in enumerate(board) if c.kind != team and not c.revealed], dtype=int)
        # The evaluator has the key; the decoder above does not.
        stats = evaluate(direction, normalized(received["board_vectors"]), friendly, danger,
                         config.target_gap)
        ranking = sorted((i for i,c in enumerate(board) if not c.revealed),
                         key=lambda i: (-received["scores"][i], board[i].word))
        simulated = []
        for i in ranking[:message["count"]]:
            simulated.append({"word": board[i].word.upper(), "kind": board[i].kind,
                              "similarity": float(received["scores"][i]),
                              "correct": board[i].kind == team})
            if board[i].kind != team:
                break
        one_shot = stats["coverage"] == len(friendly)
        fallback = stats["coverage"] == 0
        target_ids = set(stats["targets"].tolist())
        weakest = board[stats["weakest"]]
        danger_id = stats["danger"]
        plot = transmission_projection([c.word for c in board], received["board_vectors"],
                message, received["component_vectors"], direction, ideal_vector)
        # Only the full-analysis view sees the ideal point. Component/decoded directions
        # are public because anyone can reconstruct them from the transmitted message.
        public_plot = {**plot, "points": [p for p in plot["points"] if p["type"] != "ideal"]}
        best = {"clue": " + ".join(c["word"] for c in message["components"]),
                "count": message["count"], "qualified": not fallback,
                "targets": [board[i].word for i in stats["targets"]],
                "weakest_target": {"word": weakest.word, "similarity": float(received["scores"][stats["weakest"]])},
                "closest_danger": {"word": board[danger_id].word, "similarity": float(received["scores"][danger_id])} if danger_id is not None else None,
                "raw_gap": stats["gap"], "safety_slack": stats["gap"]-config.target_gap,
                "required_threshold": stats["threshold"],
                "rankings": [{"word": board[i].word, "kind": board[i].kind,
                              "similarity": float(received["scores"][i]), "target": i in target_ids}
                             for i in ranking]}
        report.update({"decoded_gap": stats["full_gap"], "one_shot": one_shot,
                       "decoded_coverage": stats["coverage"], "friendly_count": len(friendly),
                       "reconstruction_error": float(np.linalg.norm(encoded-direction)),
                       "ideal_alignment": float(direction @ ideal_vector) if ideal_vector is not None else None,
                       "ideal_distance": float(np.linalg.norm(direction-ideal_vector)) if ideal_vector is not None else None,
                       "packet_bytes": len(packet.encode()), "simulation": simulated,
                       "plot": plot,
                       "vectors": {"encoded": encoded.tolist(), "decoded": direction.tolist(),
                                   "ideal": ideal_vector.tolist() if ideal_vector is not None else None,
                                   "components": normalized(received["component_vectors"]).tolist()},
                       "elapsed_seconds": time.perf_counter()-start})
        explanation = (f"One-shot encoding found using {len(message['components'])} words."
                       if one_shot else f"Best encoding found covers {stats['coverage']} of {len(friendly)} targets; search stopped: {report['stop_reason']}.")
        if fallback:
            explanation += " No safe target qualifies; the one-guess fallback is risky."
        return {"best": best, "fallback": fallback, "communication": report,
                "plot": public_plot, "model": self.encoder.metadata,
                "config": config.model_dump(), "explanation": explanation,
                "matrix_shape": [len(self.vocabulary), len(board)],
                "legal_candidates": report["legal_candidates"],
                "elapsed_seconds": report["elapsed_seconds"],
                "heatmap": {"words": [c.word.upper() for c in board], "rows": [
                    {"clue": c["word"], "count": None,
                     "scores": cosine_matrix([v], board_vectors)[0].tolist()}
                    for c,v in zip(message["components"], received["component_vectors"])
                ] + [{"clue": "decoded sum", "count": message["count"], "scores": received["scores"].tolist()}]}}
