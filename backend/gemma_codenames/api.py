"""Optional local HTTP interface. This endpoint returns a full spymaster analysis."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .board import Card, load_words, validate_board
from .embeddings import model_config_from_env
from .optimizer import SearchConfig
from .service import EmbeddingService


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CardInput(StrictModel):
    word: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z]+$")
    kind: Literal["red", "blue", "neutral", "assassin"]
    revealed: bool = False


class ConfigInput(StrictModel):
    min_similarity: float = Field(default=0.50, ge=-1, le=1)
    neutral_margin: float = Field(default=0.02, gt=0, le=2)
    opponent_margin: float = Field(default=0.035, gt=0, le=2)
    assassin_margin: float = Field(default=0.07, gt=0, le=2)


class ClueRequest(StrictModel):
    board: list[CardInput] = Field(min_length=1, max_length=25)
    team: Literal["red", "blue"] = "red"
    config: ConfigInput = Field(default_factory=ConfigInput)
    top_n: int = Field(default=5, ge=1, le=100)


def create_app(service: EmbeddingService | None = None) -> FastAPI:
    lock = Lock()

    @asynccontextmanager
    async def lifespan(app):
        if service is None:
            vocabulary_path = os.environ.get("GEMMA_VOCABULARY")
            vocabulary = load_words(Path(vocabulary_path) if vocabulary_path else None)
            app.state.service = EmbeddingService.from_gemma(vocabulary, model_config_from_env())
        else:
            app.state.service = service
        yield

    app = FastAPI(title="Gemma Codenames laboratory", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "model_loading": "lazy"}

    @app.post("/clues")
    def clues(request: ClueRequest):
        try:
            board = [Card(**card.model_dump()) for card in request.board]
            validate_board(board, request.team)
            # Sync route runs in FastAPI's thread pool. Serialize access to one model.
            with lock:
                return app.state.service.propose_clue(
                    board,
                    request.team,
                    SearchConfig(**request.config.model_dump()),
                    request.top_n,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


app = create_app()
