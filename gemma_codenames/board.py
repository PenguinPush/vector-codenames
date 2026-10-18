import csv
from math import isqrt
from typing import Annotated
from pydantic import AfterValidator, Field
import io
import logging
import os
import random
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

Team = Literal["red", "blue"]
Kind = Literal["red", "blue", "neutral", "assassin"]
BOARD_WORD = re.compile(r"[a-z][a-z .'’-]{0,58}[a-z.]\Z")
WORD = re.compile(r"[a-z]{1,30}\Z")
LOG = logging.getLogger(__name__)
MAX_BOARD_CARDS = 100


def validate_board_size(size: int) -> int:
    if type(size) is not int or not 4 <= size <= MAX_BOARD_CARDS or isqrt(size) ** 2 != size:
        raise ValueError("Board size must be N × N cards with N from 2 to 10.")
    return size


BoardSize = Annotated[int, Field(strict=True), AfterValidator(validate_board_size)]


@dataclass(frozen=True)
class Card:
    word: str
    kind: Kind
    revealed: bool = False

    def __post_init__(self):
        word = " ".join(self.word.strip().lower().split())
        if not BOARD_WORD.fullmatch(word):
            raise ValueError("Board entries must be 2–60 characters: letters, spaces, periods, apostrophes or hyphens.")
        if self.kind not in ("red", "blue", "neutral", "assassin"):
            raise ValueError(f"Unknown card kind: {self.kind}")
        object.__setattr__(self, "word", word)


def validate_board(board: list[Card], team: Team) -> None:
    if team not in ("red", "blue"):
        raise ValueError("Team must be red or blue.")
    if not 1 <= len(board) <= MAX_BOARD_CARDS:
        raise ValueError(f"Supply between 1 and {MAX_BOARD_CARDS} cards.")
    if len({card.word for card in board}) != len(board):
        raise ValueError("Board words must be unique, ignoring case.")
    if not any(card.kind == team and not card.revealed for card in board):
        raise ValueError("The team has no unrevealed friendly cards.")


def load_words(path: Path | None = None, *, clues=False) -> list[str]:
    """CSV with a word column (other columns ignored), or legacy one-entry-per-line TXT."""
    if path is None:
        variable = "GEMMA_VOCABULARY" if clues else "GEMMA_BOARD_WORDS"
        configured = os.environ.get(variable)
        source = Path(configured) if configured else files(__package__).joinpath(
            "data/clue_words.csv" if clues else "data/board_words.csv")
    else:
        source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    entries = []
    if source.name.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if reader.fieldnames is None or "word" not in reader.fieldnames:
            raise ValueError("CSV vocabulary requires a 'word' column header.")
        try:
            for row in reader:
                if None in row or row.get("word") is None:
                    raise ValueError(f"Malformed CSV row {reader.line_num}.")
                entries.append((reader.line_num, row["word"]))
        except csv.Error as exc:
            raise ValueError(f"Invalid CSV vocabulary: {exc}") from exc
    else:
        entries = [(n, line.partition("#")[0]) for n, line in enumerate(text.splitlines(), 1)]
    result = set()
    skipped = 0
    for number, entry in entries:
        word = " ".join(entry.strip().lower().split())
        if not word:
            continue
        if not (WORD if clues else BOARD_WORD).fullmatch(word):
            if clues:
                skipped += 1
                continue
            raise ValueError(f"Invalid board entry on line {number}: {word!r}")
        result.add(word)
    if skipped:
        LOG.warning("Skipped %s unsupported clue entries in %s; clues require 1–30 ASCII letters.",
                    skipped, source)
    if not result:
        raise ValueError("Vocabulary has no supported entries.")
    return sorted(result)


def random_board(words: list[str], seed: int, starting_team: Team = "red", size: int = 25) -> list[Card]:
    validate_board_size(size)
    if starting_team not in ("red", "blue"):
        raise ValueError("Starting team must be red or blue.")
    pool = sorted({Card(word, "neutral").word for word in words})
    if len(pool) < size:
        raise ValueError(f"A random board needs at least {size} distinct words.")
    rng = random.Random(seed)
    other = "blue" if starting_team == "red" else "red"
    opponents = size // 3
    kinds = [starting_team] * (opponents + 1) + [other] * opponents + ["neutral"] * (size - 2 * opponents - 2) + ["assassin"]
    rng.shuffle(kinds)
    return [Card(word, kind) for word, kind in zip(rng.sample(pool, size), kinds)]
