from dataclasses import asdict

from .board import Card, Team, validate_board
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

    @classmethod
    def from_gemma(cls, vocabulary: list[str], config: ModelConfig = ModelConfig()):
        encoder = CachedEncoder(GemmaEncoder(config), config.cache_dir / "embeddings")
        return cls(encoder, vocabulary)

    def propose_clue(
        self,
        board: list[Card],
        team: Team = "red",
        config: SearchConfig = SearchConfig(),
        top_n: int = 5,
    ) -> dict:
        validate_board(board, team)
        if self._vocabulary_vectors is None:
            self._vocabulary_vectors = self.encoder.encode(self.vocabulary)
        board_vectors = self.encoder.encode([card.word for card in board])
        scores = cosine_matrix(self._vocabulary_vectors, board_vectors)
        result = optimize(self.vocabulary, board, scores, team, config, top_n)
        return {
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
