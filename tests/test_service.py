import json
import hashlib
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from gemma_codenames.api import create_app
from gemma_codenames.board import Card
from gemma_codenames.embeddings import CachedEncoder
from gemma_codenames.service import EmbeddingService


class FixtureEncoder:
    """Controlled vectors used only in unit tests, never as a Gemma fallback."""

    metadata = {"model_id": "test-fixture", "resolved_revision": "one", "dimensions": 3}

    def __init__(self):
        self.calls = []

    def encode(self, words):
        self.calls.append(words)
        vectors = {
            "orbit": [1, 0, 0],
            "planet": [0.9, 0.1, 0],
            "moon": [0.8, 0.2, 0],
            "rocket": [0, 0, 1],
        }
        return np.array([vectors[word] for word in words], dtype=np.float32)


def test_cache_survives_new_instance_and_separates_words_and_revisions(tmp_path):
    encoder = FixtureEncoder()
    cache = CachedEncoder(encoder, tmp_path)
    first = cache.encode(["orbit", "moon"])
    second = CachedEncoder(encoder, tmp_path).encode(["orbit", "moon"])
    np.testing.assert_allclose(first, second)
    assert len(encoder.calls) == 1
    cache.encode(["moon", "orbit"])
    assert len(encoder.calls) == 1
    encoder.metadata = {**encoder.metadata, "resolved_revision": "two"}
    cache.encode(["orbit", "moon"])
    assert len(encoder.calls) == 2


def test_bad_cache_rebuilt_and_zero_vectors_rejected(tmp_path):
    encoder = FixtureEncoder()
    cache = CachedEncoder(encoder, tmp_path)
    cache.encode(["orbit"])
    with sqlite3.connect(tmp_path / "words.sqlite3") as connection:
        connection.execute("UPDATE embeddings SET vector=?", (b"broken",))
    cache.encode(["orbit"])
    assert len(encoder.calls) == 2
    with pytest.raises(ValueError, match="zero"):
        CachedEncoder._validate(np.zeros((1, 3)), 1, 3)


def test_service_composes_embeddings_search_and_metadata():
    encoder = FixtureEncoder()
    service = EmbeddingService(encoder, ["orbit"])
    board = [Card("planet", "red"), Card("moon", "red"), Card("rocket", "assassin")]
    result = service.propose_clue(board)
    assert result["best"]["count"] == 2
    assert result["model"]["model_id"] == "test-fixture"
    json.dumps(result, allow_nan=False)
    service.propose_clue(board)
    assert encoder.calls.count(["orbit"]) == 1


def test_api_validates_requests_and_returns_full_analysis():
    encoder = FixtureEncoder()
    with TestClient(create_app(EmbeddingService(encoder, ["orbit"]))) as client:
        assert client.get("/health").status_code == 200
        assert encoder.calls == []  # Health checks don't load the model.
        board = [{"word": "planet", "kind": "red"}, {"word": "rocket", "kind": "assassin"}]
        response = client.post("/clues", json={"board": board})
        assert response.status_code == 200
        assert response.json()["best"]["count"] == 1
        assert client.post("/clues", json={"board": board, "team": "green"}).status_code == 422
        assert client.post("/clues", json={"board": board * 2}).status_code == 422
        assert client.post("/clues", json={"board": board, "top_n": 0}).status_code == 422
        assert client.post("/clues", json={"board": board, "unknown": 1}).status_code == 422


def test_api_reports_model_failure_instead_of_fake_scores():
    class UnavailableEncoder(FixtureEncoder):
        def encode(self, words):
            raise RuntimeError("model unavailable")

    with TestClient(create_app(EmbeddingService(UnavailableEncoder(), ["orbit"]))) as client:
        response = client.post("/clues", json={"board": [{"word": "planet", "kind": "red"}]})
        assert response.status_code == 503
        assert response.json()["detail"] == "model unavailable"


def test_incremental_cache_resumes_after_failure_and_reuses_changed_vocabulary(tmp_path):
    class InterruptedEncoder(FixtureEncoder):
        config = SimpleNamespace(batch_size=2)

        def encode(self, words):
            if len(self.calls) == 1:
                raise RuntimeError('interrupted during second batch')
            return super().encode(words)

    interrupted = InterruptedEncoder()
    progress = []
    with pytest.raises(RuntimeError, match='interrupted'):
        CachedEncoder(interrupted, tmp_path).encode(['orbit', 'moon', 'planet'], progress.append)
    assert any('2/3 words ready' in message and 'newly saved' in message for message in progress)
    resumed = FixtureEncoder()
    cache = CachedEncoder(resumed, tmp_path)
    actual = cache.encode(['planet', 'orbit', 'rocket', 'moon', 'orbit'])
    assert resumed.calls == [['planet', 'rocket']]
    assert actual.shape == (5, 3)
    np.testing.assert_array_equal(actual[1], actual[4])
    cache.encode(['rocket', 'moon'])
    assert resumed.calls == [['planet', 'rocket']]


def test_legacy_cache_import_and_prompt_isolation(tmp_path):
    encoder = FixtureEncoder()
    words = ['orbit', 'moon']
    payload = json.dumps({'schema': 1, 'model': encoder.metadata, 'words': words}, sort_keys=True)
    path = tmp_path / (hashlib.sha256(payload.encode()).hexdigest() + '.npz')
    np.savez_compressed(path, vectors=encoder.encode(words), metadata=payload)
    encoder.calls.clear()
    CachedEncoder(encoder, tmp_path).encode(words)
    CachedEncoder(encoder, tmp_path).encode(['moon'])
    assert encoder.calls == []
    assert path.exists()
    encoder.metadata = {**encoder.metadata, 'prompt': 'different task'}
    CachedEncoder(encoder, tmp_path).encode(words)
    assert encoder.calls == [words]


def test_service_forwards_batch_progress(tmp_path):
    encoder = CachedEncoder(FixtureEncoder(), tmp_path)
    service = EmbeddingService(encoder, ['orbit'])
    progress = []
    service.propose_clue([Card('planet', 'red'), Card('rocket', 'assassin')], progress=progress.append)
    assert any('newly saved' in message for message in progress)
