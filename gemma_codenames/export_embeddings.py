"""Generate a portable board+clue embedding file on a GPU (or explicitly chosen CPU)."""
import argparse
from pathlib import Path

from .board import load_words
from .embeddings import CachedEncoder, GemmaEncoder, ModelConfig
from .precomputed import PrecomputedEncoder, save_embeddings, extend_embeddings, pinned_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, required=True)
    parser.add_argument('--clues', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('gemma_embeddings.npz'))
    parser.add_argument('--cache-dir', type=Path, default=Path('.cache'))
    parser.add_argument('--model', default=ModelConfig.model_id)
    parser.add_argument('--revision', help='Optional model revision; resolved to an immutable commit')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--existing', type=Path, help='Reuse this NPZ; embed only missing words')
    parser.add_argument('--extra-words', type=Path, help='Additional CSV entries to embed verbatim, including hyphenated words')
    parser.add_argument('--offline', action='store_true', help='Use cached model files only')
    args = parser.parse_args()
    import torch
    from huggingface_hub import model_info
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('No CUDA GPU. In Colab choose Runtime → Change runtime type → GPU.')
    existing = PrecomputedEncoder(args.existing, model_id=args.model) if args.existing else None
    if existing:
        revision = pinned_revision(existing.metadata)
        if args.revision and args.revision != revision:
            raise ValueError('Requested revision differs from the existing embedding file')
    elif args.offline:
        revision = pinned_revision({'requested_revision': args.revision})
    else:
        revision = model_info(args.model, revision=args.revision).sha
    board = load_words(args.board)
    clues = load_words(args.clues, clues=True)
    words = sorted(set(board) | set(clues))
    if args.extra_words:
        words = sorted(set(words) | set(load_words(args.extra_words)))
    print(f'{len(words):,} unique words · {args.model} · revision {revision}', flush=True)
    config = ModelConfig(model_id=args.model, revision=revision, device=args.device,
                         batch_size=args.batch_size, cache_dir=args.cache_dir,
                         local_files_only=args.offline)
    encoder = CachedEncoder(GemmaEncoder(config), args.cache_dir / 'embeddings')
    if existing:
        missing = sorted(set(words) - set(existing.words))
        print(f'Reusing {len(existing.words):,} vectors; {len(missing):,} new words to embed', flush=True)
        extend_embeddings(existing, words, encoder, args.output)
        loaded = PrecomputedEncoder(args.output, model_id=args.model, revision=revision)
        loaded.encode(words)
        print(f'Validated {args.output}: {len(loaded.words):,} words; added {len(missing):,}.', flush=True)
        return
    values = encoder.encode(words)
    save_embeddings(args.output, words, values, encoder.metadata)
    loaded = PrecomputedEncoder(args.output, model_id=args.model, revision=revision)
    loaded.encode(words)
    print(f'Validated {args.output}: {len(words):,} words × {values.shape[1]} dimensions; '
          f'{args.output.stat().st_size / 1e6:.1f} MB. Download this file.', flush=True)


if __name__ == '__main__':
    main()
