import argparse
import json
import secrets
import sys
import time
from pathlib import Path

from .board import load_words, random_board
from .embeddings import DEFAULT_CACHE, ModelConfig
from .optimizer import SearchConfig
from .service import EmbeddingService


def print_result(result: dict):
    print(f"\nBOARD seed={result['seed']} | searching for {result['team'].upper()}")
    for offset in range(0, 25, 5):
        print(
            "  ".join(
                f"{card['word'].upper():<13} {card['kind'][0].upper()}"
                for card in result["board"][offset : offset + 5]
            )
        )
    print("R=red B=blue N=neutral A=assassin (full spymaster view)")
    best = result["best"]
    label = "FALLBACK — thresholds NOT satisfied" if result["fallback"] else "QUALIFIED"
    print(f"\n{best['clue'].upper()} · {best['count']} [{label}]")
    print("Targets: " + ", ".join(best["targets"]))
    print(result["explanation"])
    print(
        f"Searched {result['legal_candidates']} legal candidates; "
        f"excluded {result['excluded_candidates']}."
    )
    print(
        f"Weakest target: {best['weakest_target']['similarity']:.4f}; "
        f"required threshold: {best['required_threshold']:.4f}"
    )
    if best["closest_danger"]:
        print(f"Closest raw danger: {best['closest_danger']['word']}; gap: {best['raw_gap']:.4f}")
        print(
            f"Margin-limiting danger: {best['limiting_danger']['word']}; "
            f"safety slack: {best['safety_slack']:.4f}"
        )
    if best["failed_constraints"]:
        print("Failed: " + ", ".join(best["failed_constraints"]))
    print("\nWORD            ROLE       COSINE    TARGET")
    for item in best["rankings"]:
        print(
            f"{item['word'].upper():<15} {item['kind']:<10} "
            f"{item['similarity']: .4f}   {'*' if item['target'] else ''}"
        )
    print("\nCoverage check (best slack across all legal clues):")
    for item in result["coverage_checks"]:
        print(
            f"  {item['count']}: {'yes' if item['feasible'] else 'no ':3} "
            f"{item['best_constraint_slack']:+.4f} ({item['best_candidate']})"
        )
    if result["alternatives"]:
        print("\nAlternatives:")
        for item in result["alternatives"]:
            slack = item["safety_slack"]
            gap = f"{slack:+.4f}" if slack is not None else "n/a"
            print(
                f"  {item['clue']} · {item['count']} | slack {gap} | "
                f"mean {item['mean_target_similarity']:.4f}"
            )
    print(
        f"\nElapsed: {result['elapsed_seconds']:.2f}s | "
        f"model: {result['model']['model_id']} | "
        f"revision: {result['model']['resolved_revision']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Gemma clues on random Codenames boards.")
    parser.add_argument("--seed", type=int, help="Reproduce a board; random when omitted.")
    parser.add_argument("--boards", type=int, default=1)
    parser.add_argument("--team", choices=["red", "blue"], default="red")
    parser.add_argument("--starting-team", choices=["red", "blue"], default="red")
    parser.add_argument("--vocabulary", type=Path, help="One candidate clue per line.")
    parser.add_argument("--board-words", type=Path, help="One board word per line.")
    parser.add_argument("--model", default=ModelConfig.model_id)
    parser.add_argument("--revision", help="Pin a Hugging Face model commit.")
    parser.add_argument("--device", default="cpu", help="cpu, mps, cuda, cuda:0, etc.")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--offline", action="store_true", help="Use already downloaded weights.")
    parser.add_argument("--min-similarity", type=float, default=0.50)
    parser.add_argument("--neutral-margin", type=float, default=0.02)
    parser.add_argument("--opponent-margin", type=float, default=0.035)
    parser.add_argument("--assassin-margin", type=float, default=0.07)
    parser.add_argument("--top", type=int, default=5, help="Total proposals, including the winner.")
    parser.add_argument("--json", type=Path, help="Save complete reports as a JSON array.")
    args = parser.parse_args(argv)
    if args.boards < 1 or not 1 <= args.top <= 100:
        parser.error("--boards must be positive and --top must be between 1 and 100.")
    try:
        config = SearchConfig(
            args.min_similarity, args.neutral_margin, args.opponent_margin, args.assassin_margin
        )
        model = ModelConfig(
            args.model, args.revision, args.device, args.batch_size, args.cache_dir, args.offline
        )
        vocabulary = load_words(args.vocabulary, clues=True)
        board_words = load_words(args.board_words)
        seed = args.seed if args.seed is not None else secrets.randbits(32)
        # Validate the board before any download or expensive encoding.
        random_board(board_words, seed, args.starting_team)
        print(
            f"Preparing {len(vocabulary)} clue embeddings with {args.model} "
            f"on {args.device}; initial board seed={seed}. "
            "First run downloads weights and builds the cache.",
            flush=True,
        )
        service = EmbeddingService.from_gemma(vocabulary, model)
        reports = []
        for number in range(args.boards):
            board = random_board(board_words, seed + number, args.starting_team)
            start = time.perf_counter()
            result = service.propose_clue(board, args.team, config, args.top)
            result.update(seed=seed + number, elapsed_seconds=time.perf_counter() - start)
            reports.append(result)
            print_result(result)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(reports, indent=2, allow_nan=False) + "\n")
            print(f"\nSaved {args.json}")
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
