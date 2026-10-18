import random
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

Team = Literal["red", "blue"]
Kind = Literal["red", "blue", "neutral", "assassin"]
WORD = re.compile(r"[a-z]{2,30}\Z")


@dataclass(frozen=True)
class Card:
    word: str
    kind: Kind
    revealed: bool = False

    def __post_init__(self):
        word = self.word.strip().lower()
        if not WORD.fullmatch(word):
            raise ValueError("Words must contain 2–30 English letters, with no spaces.")
        if self.kind not in ("red", "blue", "neutral", "assassin"):
            raise ValueError(f"Unknown card kind: {self.kind}")
        object.__setattr__(self, "word", word)


def validate_board(board: list[Card], team: Team) -> None:
    if team not in ("red", "blue"):
        raise ValueError("Team must be red or blue.")
    if not 1 <= len(board) <= 25:
        raise ValueError("Supply between 1 and 25 cards.")
    if len({card.word for card in board}) != len(board):
        raise ValueError("Board words must be unique, ignoring case.")
    if not any(card.kind == team and not card.revealed for card in board):
        raise ValueError("The team has no unrevealed friendly cards.")


def load_words(path: Path | None = None) -> list[str]:
    """One word per line, with optional # comments; reject malformed custom files."""
    source = path if path is not None else files(__package__).joinpath("data/words.txt")
    result: set[str] = set()
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        word = line.partition("#")[0].strip().lower()
        if not word:
            continue
        if not WORD.fullmatch(word):
            raise ValueError(f"Invalid vocabulary word on line {number}: {word!r}")
        result.add(word)
    if not result:
        raise ValueError("Vocabulary is empty.")
    return sorted(result)


def random_board(words: list[str], seed: int, starting_team: Team = "red") -> list[Card]:
    if starting_team not in ("red", "blue"):
        raise ValueError("Starting team must be red or blue.")
    pool = sorted({Card(word, "neutral").word for word in words})
    if len(pool) < 25:
        raise ValueError("A random board needs at least 25 distinct words.")
    rng = random.Random(seed)
    other = "blue" if starting_team == "red" else "red"
    kinds = [starting_team] * 9 + [other] * 8 + ["neutral"] * 7 + ["assassin"]
    rng.shuffle(kinds)
    return [Card(word, kind) for word, kind in zip(rng.sample(pool, 25), kinds)]
