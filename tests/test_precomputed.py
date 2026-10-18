import json

import numpy as np
import pytest

from gemma_codenames.board import Card
from gemma_codenames.communication import CommunicationConfig
from gemma_codenames.embeddings import ModelConfig
from gemma_codenames.precomputed import PrecomputedEncoder, save_embeddings
from gemma_codenames.service import EmbeddingService


META = {'model_id': 'google/embeddinggemma-2', 'resolved_revision': 'a'*40,
        'requested_revision': 'a'*40, 'prompt_name': 'STS', 'prompt': 'task: sentence similarity | query: ',
        'dimensions': 3, 'normalized': True, 'device': 'cuda:0'}


def make_file(path):
    save_embeddings(path, ['orbit', 'moon', 'rocket'],
                    np.array([[1., 0, 0], [.9, .1, 0], [0, 0, 1]]), META)


def test_file_only_service_runs_without_loading_gemma(tmp_path, monkeypatch):
    path = tmp_path / 'vectors.npz'
    make_file(path)
    monkeypatch.setenv('GEMMA_EMBEDDINGS_FILE', str(path))
    def no_model(*args, **kwargs):
        raise AssertionError('Must not load Gemma for precomputed embeddings')
    monkeypatch.setattr('gemma_codenames.embeddings.GemmaEncoder._load', no_model)
    service = EmbeddingService.from_gemma(['orbit'], ModelConfig(device='cpu'))
    result = service.communicate([Card('moon', 'red'), Card('rocket', 'assassin')],
                                 'red', CommunicationConfig(max_words=1))
    assert result['communication']['one_shot']
    assert result['communication']['reconstruction_error'] < 1e-7
    json.dumps(result, allow_nan=False)
    encoder = service.encoder
    np.testing.assert_array_equal(encoder.encode(['moon', 'orbit', 'moon'])[0], encoder.encode(['moon'])[0])
    assert encoder.encode([]).shape == (0, 3)
    with pytest.raises(ValueError, match='lack 1 word'):
        encoder.precomputed.encode(['newword'])


def test_file_rejects_model_revision_mismatch_and_bad_vectors(tmp_path):
    path = tmp_path / 'vectors.npz'
    make_file(path)
    with pytest.raises(ValueError, match='model differs'):
        PrecomputedEncoder(path, model_id='different')
    with pytest.raises(ValueError, match='revision differs'):
        PrecomputedEncoder(path, revision='wrong')
    with pytest.raises(ValueError, match='zero'):
        save_embeddings(path, ['moon'], np.zeros((1, 3)), META)
    # Failed replacement preserves the previous valid file.
    assert len(PrecomputedEncoder(path).words) == 3
    with pytest.raises(ValueError, match='unique'):
        save_embeddings(path, ['moon', 'moon'], np.ones((2, 3)), META)


def test_colab_bundle_contains_only_expected_code_and_current_csvs():
    from pathlib import Path
    from zipfile import ZipFile
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / 'colab/gemma_colab_bundle.zip') as bundle:
        names = bundle.namelist()
        assert len(names) == 7
        assert not any('.env' in name or 'token' in name for name in names)
        for name in names:
            assert bundle.read(name) == (root / name).read_bytes()
    notebook = json.loads((root / 'colab/Generate_Gemma_Embeddings.ipynb').read_text())
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            source = ''.join(line for line in cell['source'] if not line.startswith('%'))
            compile(source, '<colab cell>', 'exec')
            assert cell['outputs'] == []


def test_incremental_export_only_encodes_missing_words_and_preserves_old_vectors(tmp_path):
    from gemma_codenames.precomputed import extend_embeddings
    path = tmp_path / 'old.npz'
    make_file(path)
    old = PrecomputedEncoder(path)
    class Encoder:
        metadata = {**META, 'device': 'cpu'}
        calls = []
        def encode(self, words):
            self.calls.append(words)
            return np.array([[0., 1., 0.] for _ in words])
    encoder = Encoder()
    target = tmp_path / 'updated.npz'
    assert extend_embeddings(old, ['moon', 'newword'], encoder, target) == ['newword']
    assert encoder.calls == [['newword']]
    updated = PrecomputedEncoder(target)
    np.testing.assert_allclose(updated.encode(old.words), old.encode(old.words), atol=1e-7)
    assert extend_embeddings(updated, ['newword'], encoder, target) == []
    assert encoder.calls == [['newword']]
    encoder.metadata = {**META, 'resolved_revision': 'b'*40}
    with pytest.raises(ValueError, match='different model'):
        extend_embeddings(old, ['otherword'], encoder, target)
    assert PrecomputedEncoder(target).words == updated.words


def test_legacy_session_export_uses_pinned_requested_revision(tmp_path):
    from gemma_codenames.precomputed import pinned_revision
    assert pinned_revision({**META, 'resolved_revision': 'session-old'}) == 'a'*40
    with pytest.raises(ValueError, match='immutable'):
        pinned_revision({'resolved_revision': 'session-old', 'requested_revision': 'main'})


@pytest.mark.parametrize('word', ['about-face', "a'man", 'st.patrick'])
def test_precomputed_keeps_punctuated_board_entries(tmp_path, word):
    path = tmp_path / 'vectors.npz'
    save_embeddings(path, [word], np.array([[1., 0, 0]]), META)
    assert PrecomputedEncoder(path).encode([word]).shape == (1, 3)


def test_live_fallback_only_embeds_missing_words_and_survives_restart(tmp_path, monkeypatch):
    from gemma_codenames.precomputed import HybridEncoder
    path = tmp_path / 'vectors.npz'
    make_file(path)
    original = path.read_bytes()
    calls = []
    loads = []
    class FakeGemma:
        metadata = {**META, 'device': 'cpu'}
        def __init__(self, config):
            loads.append(config)
        def encode(self, words):
            calls.append(words)
            return np.array([[0., 1, 0] for word in words])
    monkeypatch.setattr('gemma_codenames.precomputed.GemmaEncoder', FakeGemma)
    config = ModelConfig(cache_dir=tmp_path / 'cache')
    hybrid = HybridEncoder(PrecomputedEncoder(path), config)
    hybrid.encode(['moon'])
    assert loads == []
    stages = []
    result = hybrid.encode(['newword', 'moon', 'newword'], progress=stages.append)
    assert calls == [['newword']]
    assert loads[0].revision == META['resolved_revision']
    np.testing.assert_array_equal(result[0], result[2])
    assert any('newly saved' in stage for stage in stages)
    restarted = HybridEncoder(PrecomputedEncoder(path), config)
    np.testing.assert_allclose(restarted.encode(['newword', 'moon', 'newword']), result)
    assert len(loads) == 1 and calls == [['newword']]
    assert path.read_bytes() == original
    assert hybrid.metadata == META


def test_live_fallback_rejects_model_mismatch_before_embedding(tmp_path, monkeypatch):
    from gemma_codenames.precomputed import HybridEncoder
    path = tmp_path / 'vectors.npz'
    make_file(path)
    class WrongGemma:
        metadata = {**META, 'prompt': 'wrong task'}
        def __init__(self, config):
            pass
        def encode(self, words):
            raise AssertionError('Must reject incompatible embeddings before computation')
    monkeypatch.setattr('gemma_codenames.precomputed.GemmaEncoder', WrongGemma)
    hybrid = HybridEncoder(PrecomputedEncoder(path), ModelConfig(cache_dir=tmp_path))
    with pytest.raises(ValueError, match='does not match'):
        hybrid.encode(['unknown'])
    assert hybrid.precomputed.encode(['moon']).shape == (1, 3)
