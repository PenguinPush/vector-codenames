import hashlib
import json
import tempfile
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
        identity = resolved or f"session-{uuid.uuid4().hex}"
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
    """Cache an ordered word list against the actual model revision and encoding settings."""

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

    def encode(self, words: list[str]) -> np.ndarray:
        metadata = self.metadata
        payload = json.dumps({"schema": 1, "model": metadata, "words": words}, sort_keys=True)
        key = hashlib.sha256(payload.encode()).hexdigest()
        path = self.cache_dir / f"{key}.npz"
        try:
            with np.load(path, allow_pickle=False) as saved:
                if saved["metadata"].item() != payload:
                    raise ValueError("Cache metadata mismatch.")
                result = self._validate(saved["vectors"], len(words), metadata["dimensions"])
            self.hits += 1
            return result
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            pass
        result = self._validate(self.encoder.encode(words), len(words), metadata["dimensions"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Atomic replacement prevents partially written caches from concurrent processes.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.cache_dir, suffix=".npz", delete=False) as f:
                temporary = Path(f.name)
                np.savez_compressed(f, vectors=result, metadata=payload)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.misses += 1
        return result


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
