"""Reproducible encode/decode experiment without a game server."""
import argparse
import json
from pathlib import Path

from .board import load_words, random_board
from .bots import DemoEncoder
from .communication import CommunicationConfig
from .embeddings import model_config_from_env
from .service import EmbeddingService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--team', choices=['red', 'blue'], default='red')
    parser.add_argument('--max-words', type=int, default=3)
    parser.add_argument('--coefficients', action='store_true')
    parser.add_argument('--precision', type=int, default=2)
    parser.add_argument('--gap', type=float, default=.001)
    parser.add_argument('--seconds', type=float, default=5.0)
    parser.add_argument('--evaluations', type=int, default=2000)
    parser.add_argument('--continue-search', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    config = CommunicationConfig(max_words=args.max_words, coefficients=args.coefficients,
        precision=args.precision, target_gap=args.gap, time_limit=args.seconds,
        max_evaluations=args.evaluations, stop_at_one_shot=not args.continue_search)
    vocabulary = load_words(clues=True)
    service = (EmbeddingService(DemoEncoder(), vocabulary) if args.synthetic else
               EmbeddingService.from_gemma(vocabulary, model_config_from_env()))
    board = random_board(load_words(), args.seed)
    result = service.communicate(board, args.team, config, progress=print)
    result.update(seed=args.seed, source='demo' if args.synthetic else 'gemma')
    report = result['communication']
    print('SYNTHETIC VECTORS' if args.synthetic else 'REAL GEMMA EMBEDDINGS')
    print(result['explanation'])
    print('Wire message:', json.dumps(report['message']))
    print('Ideal upper bound:', report['ideal'].get('upper_bound'))
    print('Decoded all-target gap:', report['decoded_gap'])
    print('Encode/decode reconstruction error:', report['reconstruction_error'])
    print('Stopping reason:', report['stop_reason'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
