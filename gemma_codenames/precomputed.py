"""Portable embeddings: validated arrays and model identity, without model imports."""
import json
import os
import re
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np

from .embeddings import CachedEncoder, GemmaEncoder


def pinned_revision(metadata):
    """Recognize legacy exports whose resolved identity was a session UUID."""
    for key in ('resolved_revision', 'requested_revision'):
        value = metadata.get(key, '') or ''
        if re.fullmatch(r'[0-9a-f]{40}', value):
            return value
    raise ValueError('Incremental embedding requires an immutable model commit.')


def extend_embeddings(existing, words, encoder, output):
    """Embed only absent words; reject incompatible models before writing anything."""
    words = sorted(set(existing.words) | set(words))
    missing = sorted(set(words) - set(existing.words))
    metadata = existing.metadata
    if missing:
        new_metadata = encoder.metadata
        keys = ('model_id', 'dimensions', 'prompt_name', 'prompt', 'normalized',
                'dtype', 'text_only')
        if (any(metadata.get(k) != new_metadata.get(k) for k in keys)
                or pinned_revision(metadata) != pinned_revision(new_metadata)):
            raise ValueError('Cannot merge embeddings from different model revisions or encoding settings.')
        added = CachedEncoder._validate(encoder.encode(missing), len(missing), metadata['dimensions'])
        vectors = np.concatenate([existing.encode(existing.words), added])
        indices = {w: i for i, w in enumerate(existing.words + missing)}
        vectors = vectors[[indices[w] for w in words]]
        metadata = {**metadata, 'resolved_revision': pinned_revision(new_metadata),
                    'incremental_encoder': new_metadata}
    else:
        vectors = existing.encode(words)
    save_embeddings(output, words, vectors, metadata)
    return missing


class PrecomputedEncoder:
    def __init__(self, path, *, model_id=None, revision=None):
        self.path = Path(path)
        with np.load(self.path, allow_pickle=False) as saved:
            manifest = json.loads(saved['manifest'].item())
            words = saved['words']
            vectors = saved['vectors']
        if manifest.get('format') != 'gemma-codenames-embeddings-v1':
            raise ValueError('Unsupported embedding file format')
        metadata = manifest.get('model', {})
        if (not isinstance(metadata.get('dimensions'), int) or metadata['dimensions'] <= 0
                or not metadata.get('model_id') or not metadata.get('resolved_revision')
                or metadata.get('prompt_name') != 'STS' or not metadata.get('prompt')
                or metadata.get('normalized') is not True):
            raise ValueError('Embedding file is missing required model/STS metadata')
        if model_id and metadata['model_id'] != model_id:
            raise ValueError('Embedding file model differs from GEMMA_MODEL_ID')
        if revision and revision not in (metadata['resolved_revision'], metadata.get('requested_revision')):
            raise ValueError('Embedding file revision differs from GEMMA_REVISION')
        if words.ndim != 1 or words.dtype.kind != 'U' or not len(words):
            raise ValueError('Embedding file requires a nonempty string word array')
        self.words = words.tolist()
        if len(set(self.words)) != len(self.words) or any(
                not word or word != ' '.join(word.lower().split()) for word in self.words):
            raise ValueError('Embedding file words must be unique and normalized')
        self._vectors = CachedEncoder._validate(vectors, len(words), metadata['dimensions'])
        self._indices = {word: index for index, word in enumerate(self.words)}
        self._metadata = metadata

    @property
    def metadata(self):
        return dict(self._metadata)

    def encode(self, words):
        missing = sorted(set(words) - self._indices.keys())
        if missing:
            preview = ', '.join(missing[:8])
            raise ValueError(f'Precomputed embeddings lack {len(missing)} word(s): {preview}. '
                             'Regenerate the Colab file with the updated board and clue CSVs.')
        return self._vectors[[self._indices[word] for word in words]].copy()


class MatchingLiveEncoder:
    """Expose the export's identity for cache lookup; load Gemma only on a cache miss."""
    def __init__(self, metadata, config):
        self._metadata = dict(metadata)
        self.config = config
        self._encoder = None

    @property
    def metadata(self):
        return dict(self._metadata)

    def encode(self, words):
        if self._encoder is None:
            config = replace(self.config, model_id=self._metadata['model_id'],
                             revision=pinned_revision(self._metadata))
            encoder = GemmaEncoder(config)
            actual = encoder.metadata
            keys = ('model_id', 'dimensions', 'prompt_name', 'prompt', 'normalized')
            optional = ('dtype', 'text_only')
            if (any(actual.get(k) != self._metadata.get(k) for k in keys)
                    or any(k in self._metadata and actual.get(k) != self._metadata[k] for k in optional)
                    or pinned_revision(actual) != pinned_revision(self._metadata)):
                raise ValueError('Live Gemma does not match the precomputed model revision or encoding settings.')
            self._encoder = encoder
        return self._encoder.encode(words)


class HybridEncoder:
    """Read the portable file first; persist missing words in a local SQLite sidecar."""
    def __init__(self, precomputed, config):
        self.precomputed = precomputed
        self.live = CachedEncoder(MatchingLiveEncoder(precomputed.metadata, config),
                                  config.cache_dir / 'live_embeddings')
        self._lock = threading.RLock()

    @property
    def metadata(self):
        return self.precomputed.metadata

    def encode(self, words, progress=None):
        with self._lock:
            missing = sorted(set(words) - self.precomputed._indices.keys())
            if not missing:
                return self.precomputed.encode(words)
            if progress:
                progress(f'Looking up {len(missing):,} words absent from the export · live Gemma if not cached')
            added = self.live.encode(missing, progress=progress)
            lookup = dict(zip(missing, added))
            existing = [word for word in dict.fromkeys(words) if word not in lookup]
            if existing:
                lookup.update(zip(existing, self.precomputed.encode(existing)))
            return np.stack([lookup[word] for word in words])


def save_embeddings(path, words, vectors, metadata):
    """Write atomically and verify through the same reader used by the game."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.dumps({'format': 'gemma-codenames-embeddings-v1', 'model': metadata}, sort_keys=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.npz', delete=False) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(stream, words=np.asarray(words, dtype=str), vectors=vectors,
                                manifest=manifest)
        PrecomputedEncoder(temporary)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
