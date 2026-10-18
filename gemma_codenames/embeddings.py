import hashlib
import json
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Protocol
from zipfile import BadZipFile

import numpy as np

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".cache"


class Encoder(Protocol):
    @property
    def metadata(self) -> dict: ...

    def encode(self, words: list[str]) -> np.ndarray: ...


@dataclass(frozen=True)
class ModelConfig:
    model_id: str = "google/embeddinggemma-2"
    revision: str | None = None
    device: str = "cpu"
    batch_size: int = 32
    cache_dir: Path = DEFAULT_CACHE
    local_files_only: bool = False

    def __post_init__(self):
        if self.batch_size < 1:
            raise ValueError("Batch size must be positive.")
        if not self.model_id.strip():
            raise ValueError("Model ID cannot be empty.")


class GemmaEncoder:
    """Load once on first use; both clues and cards follow the same STS encoding."""

    def __init__(self, config: ModelConfig = ModelConfig()):
        self.config = config
        self._model = None
        self._metadata = None

    def _load(self):
        if self._model is not None:
            return
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install the model dependencies: pip install -e '.[gemma]'") from exc
        try:
            model = SentenceTransformer(
                self.config.model_id,
                revision=self.config.revision,
                device=self.config.device,
                cache_folder=str(self.config.cache_dir / "models"),
                local_files_only=self.config.local_files_only,
                trust_remote_code=False,
                config_kwargs={"vision_config": None, "audio_config": None},
                model_kwargs={"torch_dtype": torch.float32},
            )
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(
                f"Could not load {self.config.model_id}. Check network/model access and the "
                "installed Sentence Transformers/Transformers versions. For a gated model, "
                "accept its terms on Hugging Face and run `hf auth login` or set HF_TOKEN. "
                f"Original error: {exc}"
            ) from exc
        if "STS" not in model.prompts:
            raise RuntimeError("The model has no STS prompt; refusing to silently change encoding.")
        model.eval()
        backbone = model[0].auto_model.config
        resolved = getattr(backbone, "_commit_hash", None)
        # A local, mutable model without a commit hash must not reuse an old disk cache.
        # A caller-supplied immutable commit also pins identity when Transformers
        # omits _commit_hash (as it does for some Gemma configurations).
        import re
        pinned = self.config.revision if re.fullmatch(r"[0-9a-f]{40}", self.config.revision or "") else None
        identity = resolved or pinned or f"session-{uuid.uuid4().hex}"
        self._metadata = {
            "model_id": self.config.model_id,
            "requested_revision": self.config.revision,
            "resolved_revision": identity,
            "prompt_name": "STS",
            "prompt": model.prompts["STS"],
            "dimensions": model.get_sentence_embedding_dimension(),
            "normalized": True,
            "dtype": "float32",
            "text_only": True,
            "device": str(model.device),
            "sentence_transformers": version("sentence-transformers"),
            "transformers": version("transformers"),
            "torch": version("torch"),
        }
        self._model = model

    @property
    def metadata(self) -> dict:
        self._load()
        return dict(self._metadata)

    def encode(self, words: list[str]) -> np.ndarray:
        self._load()
        if not words:
            return np.empty((0, self._metadata["dimensions"]), dtype=np.float32)
        return self._model.encode(
            words,
            prompt_name="STS",
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=self.config.batch_size,
            show_progress_bar=False,
        ).astype(np.float32)


class CachedEncoder:
    """Per-word durable cache, namespaced by model revision and encoding settings."""

    def __init__(self, encoder: Encoder, cache_dir: Path):
        self.encoder = encoder
        self.cache_dir = cache_dir
        self.hits = 0
        self.misses = 0

    @property
    def metadata(self) -> dict:
        return self.encoder.metadata

    @staticmethod
    def _validate(values, count: int, dimensions: int):
        values = np.asarray(values, dtype=np.float32)
        if values.shape != (count, dimensions) or not np.isfinite(values).all():
            raise ValueError("Encoder returned malformed or nonfinite embeddings.")
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("Encoder returned a zero vector.")
        return values / norms

    def encode(self, words: list[str], progress=None) -> np.ndarray:
        last_output = 0.0

        def notify(message, *, force=False):
            nonlocal last_output
            if progress:
                progress(message)
            now = time.monotonic()
            if force or now - last_output >= 2:
                print(message, file=sys.stderr, flush=True)
                last_output = now

        notify("Loading embedding model / resolving model identity (first load may download weights)", force=True)
        metadata = self.metadata
        dimensions = metadata["dimensions"]
        if not words:
            return np.empty((0, dimensions), dtype=np.float32)
        unique = list(dict.fromkeys(words))
        model_key = hashlib.sha256(json.dumps(
            {"schema": 2, "model": metadata}, sort_keys=True).encode()).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.cache_dir / "words.sqlite3", timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("CREATE TABLE IF NOT EXISTS embeddings "
                               "(model TEXT NOT NULL, word TEXT NOT NULL, vector BLOB NOT NULL, "
                               "PRIMARY KEY (model, word))")
            found = {}
            for offset in range(0, len(unique), 500):
                chunk = unique[offset:offset+500]
                placeholders = ','.join('?' for _ in chunk)
                rows = connection.execute(
                    f"SELECT word, vector FROM embeddings WHERE model=? AND word IN ({placeholders})",
                    [model_key, *chunk])
                for word, blob in rows:
                    try:
                        value = np.frombuffer(blob, dtype='<f4').reshape(1, -1)
                        found[word] = self._validate(value, 1, dimensions)[0]
                    except (ValueError, TypeError):
                        # Recompute malformed rows; never feed corrupt vectors into the solver.
                        continue

            def persist(batch, values):
                # Commit BEFORE reporting progress. An interruption loses at most the active batch.
                with connection:
                    connection.executemany(
                        "INSERT OR REPLACE INTO embeddings (model, word, vector) VALUES (?, ?, ?)",
                        [(model_key, word, value.astype('<f4').tobytes())
                         for word, value in zip(batch, values)])
                found.update(zip(batch, values))

            # Import the old whole-list cache when this exact request already exists.
            # Keep the old file intact; subsequent requests use the per-word database.
            if len(found) < len(unique):
                payload = json.dumps({"schema": 1, "model": metadata, "words": words}, sort_keys=True)
                legacy = self.cache_dir / (hashlib.sha256(payload.encode()).hexdigest() + '.npz')
                try:
                    with np.load(legacy, allow_pickle=False) as saved:
                        if saved["metadata"].item() != payload:
                            raise ValueError("Cache metadata mismatch")
                        values = self._validate(saved["vectors"], len(words), dimensions)
                    persist(words, values)
                except (OSError, ValueError, KeyError, EOFError, BadZipFile):
                    pass
            cached = len(found)
            missing = [word for word in unique if word not in found]
            total = len(unique)
            if not missing:
                self.hits += 1
                notify(f"Embeddings ready · {total:,}/{total:,} words cached · no inference needed", force=True)
            else:
                self.misses += 1
                batch_size = getattr(getattr(self.encoder, 'config', None), 'batch_size', 32)
                batches = (len(missing) + batch_size - 1) // batch_size
                device = metadata.get('device', 'configured device')
                notify(f"Embedding {len(missing):,} new words on {device} · {cached:,}/{total:,} cached · "
                       f"{batches:,} batches of up to {batch_size}", force=True)
                started = time.monotonic()
                for offset in range(0, len(missing), batch_size):
                    batch = missing[offset:offset+batch_size]
                    values = self._validate(self.encoder.encode(batch), len(batch), dimensions)
                    persist(batch, values)
                    completed = offset + len(batch)
                    elapsed = time.monotonic() - started
                    remaining = elapsed / completed * (len(missing) - completed)
                    notify(f"Embedding batch {offset // batch_size + 1:,}/{batches:,} · "
                           f"{cached + completed:,}/{total:,} words ready "
                           f"({100 * (cached + completed) / total:.1f}%) · "
                           f"{cached:,} reused · {completed:,} newly saved · "
                           f"elapsed {elapsed:.0f}s · ETA {remaining:.0f}s",
                           force=completed == len(missing))
            return np.stack([found[word] for word in words])
        finally:
            connection.close()


def model_config_from_env() -> ModelConfig:
    """Shared API defaults; the CLI offers explicit flags instead."""
    import os

    return ModelConfig(
        model_id=os.environ.get("GEMMA_MODEL_ID", ModelConfig.model_id),
        revision=os.environ.get("GEMMA_REVISION") or None,
        device=os.environ.get("GEMMA_DEVICE", "cpu"),
        batch_size=int(os.environ.get("GEMMA_BATCH_SIZE", "32")),
        cache_dir=Path(os.environ.get("GEMMA_CACHE_DIR", str(DEFAULT_CACHE))),
        local_files_only=os.environ.get("GEMMA_OFFLINE", "0") == "1",
    )
