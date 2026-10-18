"""One process: Python rules + one shared model worker + static frontend + WebSockets."""

import argparse
import asyncio
import copy
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError, Field
from typing import Literal
import time

from .board import BoardSize, load_words, random_board
from .communication import CommunicationConfig
from .bots import BotService, DemoEncoder, choose_guess
from .embeddings import model_config_from_env
from .game import (Command, GameError, accept_clue, active_slot, apply_action, event,
                   make_room, next_turn, project, reveal)
from .service import EmbeddingService

LOG = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
COOKIE = "gemma_session"


class RoomOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    board_size: BoardSize = 25
    geometry: bool = False
    communication: CommunicationConfig = Field(default_factory=CommunicationConfig)


class LabOptions(RoomOptions):
    seed: int = Field(default=42, ge=0, le=4294967295)
    team: Literal["red", "blue"] = "red"
    synthetic: bool = False


class Hub:
    def __init__(self, bot, words, delay=1.5):
        self.bot, self.words, self.delay = bot, words, delay
        self.rooms = {}
        self.connections = {}
        self.locks = {}
        self.tasks = set()
        self.runners = {}

    async def broadcast(self, code):
        room = self.rooms[code]
        peers = list(self.connections.get(code, {}).items())
        online = {session for _, session in peers}
        for ws, session in peers:
            try:
                await asyncio.wait_for(ws.send_json({"type": "state", "room": project(
                    room, session, self.bot.mode, online)}), timeout=3)
            except (RuntimeError, WebSocketDisconnect, OSError, asyncio.TimeoutError):
                self.connections[code].pop(ws, None)

    def schedule(self, code):
        if code in self.runners and not self.runners[code].done():
            return
        task = asyncio.create_task(self.advance(code))
        self.runners[code] = task
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def advance(self, code):
        """One per-room lock serializes moves; inference releases it while pending.

        Commands are rejected during pending inference, so a returned result belongs
        to exactly the same turn. Other rooms and network handling stay responsive.
        """
        while True:
            await asyncio.sleep(self.delay)
            async with self.locks[code]:
                room = self.rooms[code]
                if room["pending"] or room["botError"] or not active_slot(room):
                    return
                needs_scores = room["clue"] and not room["clue"]["scores"]
                if room["paused"] and not room["stepRequested"] and not needs_scores:
                    return
                seat = next(s for s in room["seats"] if s["id"] == active_slot(room))
                if seat["controller"] == "human" and not needs_scores:
                    return
                if room["phase"] == "guess" and not needs_scores:
                    # No hidden kind or target list is passed to the guesser.
                    public = [{k: c[k] for k in ("id", "word", "revealed")} for c in room["board"]]
                    clue = {k: room["clue"][k] for k in ("word", "count", "scores")}
                    guess = choose_guess(public, clue, room["guesses"], self.bot.mode)
                    if guess["cardId"]:
                        reveal(room, guess["cardId"], guess["reason"])
                    else:
                        event(room, "end", guess["reason"])
                        next_turn(room)
                    room["stepRequested"] = False
                    room["version"] += 1
                    await self.broadcast(code)
                    continue
                room["pending"] = True
                room["liveSearch"] = None
                room["stage"] = "Waiting for the shared embedding worker"
                room["version"] += 1
                snapshot = copy.deepcopy(room)
                await self.broadcast(code)
            loop = asyncio.get_running_loop()

            async def stage_update(stage):
                async with self.locks[code]:
                    self.rooms[code]["stage"] = stage["stage"] if isinstance(stage, dict) else stage
                    if isinstance(stage, dict):
                        self.rooms[code]["liveSearch"] = stage.get("search")
                    await self.broadcast(code)

            def progress(stage):
                asyncio.run_coroutine_threadsafe(stage_update(stage), loop).result()

            try:
                if needs_scores:
                    public = [{k: c[k] for k in ("id", "word")} for c in snapshot["board"]]
                    result = await asyncio.to_thread(self.bot.score, snapshot["clue"]["word"], public)
                else:
                    result = await asyncio.to_thread(self.bot.propose, snapshot["board"],
                                                     snapshot["turn"], progress, snapshot["geometry"], snapshot["communication"])
                async with self.locks[code]:
                    room = self.rooms[code]
                    if needs_scores:
                        room["clue"].update(result)
                        room["decisions"][-1]["clue"] = copy.deepcopy(room["clue"])
                    else:
                        accept_clue(room, result)
                    room.update(pending=False, stage=None, liveSearch=None, stepRequested=False)
                    room["version"] += 1
                    await self.broadcast(code)
            except Exception as exc:
                LOG.exception("Embedding worker failed")
                async with self.locks[code]:
                    room = self.rooms[code]
                    room.update(pending=False, stage=None, liveSearch=None, stepRequested=False,
                                botError=f"{type(exc).__name__}: Model computation failed. Check the server log and retry.")
                    room["version"] += 1
                    await self.broadcast(code)
                return


def same_origin(headers):
    origin = headers.get("origin")
    if not origin:
        return True  # CLI clients have no ambient browser cookies.
    parsed = urlsplit(origin)
    extra = os.environ.get("CODENAMES_ORIGINS", "").split(",")
    return (parsed.scheme in ("http", "https") and parsed.netloc == headers.get("host")) or origin in extra


def create_app(bot=None, delay=1.5):
    words = load_words()
    room_words = sorted({word.upper() for word in words if word.isascii() and word.isalpha() and len(word) <= 4})
    if bot is None:
        mode = os.environ.get("CODENAMES_MODE", "gemma")
        if mode not in ("gemma", "demo"):
            raise ValueError("CODENAMES_MODE must be gemma or demo")
        vocab_path = os.environ.get("GEMMA_VOCABULARY")
        vocabulary = load_words(Path(vocab_path) if vocab_path else None, clues=True)
        service = (EmbeddingService(DemoEncoder(), vocabulary) if mode == "demo"
                   else EmbeddingService.from_gemma(vocabulary, model_config_from_env()))
        bot = BotService(service, mode)
    hub = Hub(bot, words, delay)
    lab_jobs = {}
    lab_busy = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in list(hub.tasks):
            task.cancel()
        await asyncio.gather(*hub.tasks, return_exceptions=True)

    app = FastAPI(title="Gemma / Codenames", lifespan=lifespan)
    app.state.hub = hub
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def browser_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        return response

    @app.get("/lab")
    def laboratory(request: Request):
        response = FileResponse(STATIC / "lab.html", headers={"Cache-Control": "no-store"})
        if not request.cookies.get(COOKIE):
            response.set_cookie(COOKIE, secrets.token_urlsafe(32), httponly=True,
                                samesite="lax", secure=request.url.scheme == "https",
                                max_age=60 * 60 * 24 * 30)
        return response

    @app.post("/api/lab")
    async def run_experiment(request: Request, options: LabOptions):
        session = request.cookies.get(COOKIE)
        if not session or not same_origin(request.headers):
            raise HTTPException(403, "Open the laboratory page first.")
        if lab_busy.locked():
            raise HTTPException(429, "An experiment is already running. Wait for it to finish.")
        # A bounded set of owner-private reports; completed jobs expire after an hour.
        for key in list(lab_jobs):
            if lab_jobs[key]["status"] != "running" and time.time()-lab_jobs[key]["created"] > 3600:
                del lab_jobs[key]
        if len(lab_jobs) >= 32:
            completed = [key for key, value in lab_jobs.items() if value["status"] != "running"]
            if completed:
                del lab_jobs[completed[0]]
        job_id = secrets.token_urlsafe(18)
        job = {"owner": session, "created": time.time(), "status": "running",
               "stage": "Preparing seeded board", "result": None}
        lab_jobs[job_id] = job
        # Reserve before spawning so simultaneous HTTP requests cannot both acquire it.
        await lab_busy.acquire()
        loop = asyncio.get_running_loop()

        async def run():
            try:
                cards = random_board(words, options.seed, size=options.board_size)
                experiment_bot = hub.bot
                if options.synthetic:
                    experiment_bot = BotService(EmbeddingService(DemoEncoder(), load_words(clues=True)), "demo")
                elif hub.bot.mode == "demo":
                    experiment_bot = BotService(EmbeddingService.from_gemma(load_words(clues=True), model_config_from_env()), "gemma")
                def progress(stage):
                    loop.call_soon_threadsafe(job.update, {"stage": stage["stage"] if isinstance(stage, dict) else stage})
                def compute():
                    with experiment_bot.lock:
                        return experiment_bot.service.communicate(cards, options.team,
                                                                  options.communication, progress)
                result = await asyncio.to_thread(compute)
                result.update(seed=options.seed, team=options.team, source=experiment_bot.mode, board_size=options.board_size,
                              board=[{"word": c.word.upper(), "kind": c.kind, "revealed": False}
                                     for c in cards])
                job.update(status="complete", stage="Encoding and decoding complete", result=result)
            except Exception:
                LOG.exception("Laboratory experiment failed")
                job.update(status="error", stage="Model or solver failed. Check the server log. Synthetic mode is available for pipeline testing.")
            finally:
                lab_busy.release()

        task = asyncio.create_task(run())
        hub.tasks.add(task)
        task.add_done_callback(hub.tasks.discard)
        return {"job_id": job_id}

    @app.get("/api/lab/{job_id}")
    def experiment_status(job_id: str, request: Request):
        job = lab_jobs.get(job_id)
        if not job or job["owner"] != request.cookies.get(COOKIE):
            raise HTTPException(404, "Experiment not found")
        return {k: v for k,v in job.items() if k not in ("owner", "created")}

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": hub.bot.mode, "model": "loaded lazily"}

    @app.get("/")
    @app.get("/room/{code}")
    def index(request: Request):
        response = FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
        if not request.cookies.get(COOKIE):
            response.set_cookie(COOKIE, secrets.token_urlsafe(32), httponly=True,
                                samesite="lax", secure=request.url.scheme == "https",
                                max_age=60 * 60 * 24 * 30)
        return response

    @app.post("/api/rooms")
    async def create_room(request: Request, options: RoomOptions):
        if not same_origin(request.headers):
            raise HTTPException(403, "Origin not allowed")
        session = request.cookies.get(COOKIE)
        if not session:
            raise HTTPException(401, "Open the home page first.")
        # Deliberately bounded, in-memory MVP. Never evict an active room silently.
        if len(hub.rooms) >= 100:
            raise HTTPException(503, "Server room limit reached. Restart to clear old rooms.")
        owned = sum(r["hostId"] == session for r in hub.rooms.values())
        if owned >= 10:
            raise HTTPException(429, "You already have ten rooms on this server.")
        available = [word for word in room_words if word not in hub.rooms]
        if not available:
            raise HTTPException(503, "All word room codes are in use. Restart to clear old rooms.")
        code = secrets.choice(available)
        room = make_room(code, session, words, options.board_size)
        room["geometry"] = options.geometry
        room["communication"] = options.communication.model_dump()
        hub.rooms[code] = room
        hub.connections[code] = {}
        hub.locks[code] = asyncio.Lock()
        return JSONResponse({"code": code, "url": f"/room/{code}"})

    @app.websocket("/ws/{code}")
    async def socket(ws: WebSocket, code: str):
        code = code.upper()
        session = ws.cookies.get(COOKIE)
        if code not in hub.rooms or not session or not same_origin(ws.headers):
            await ws.close(code=1008)
            return
        if len(hub.connections[code]) >= 64:
            await ws.close(code=1013)
            return
        await ws.accept()
        hub.connections[code][ws] = session
        async with hub.locks[code]:
            await hub.broadcast(code)
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 4096:
                    await ws.close(code=1009)
                    break
                async with hub.locks[code]:
                    try:
                        command = Command.model_validate_json(raw)
                        room = hub.rooms[code]
                        if room["pending"]:
                            raise GameError("Model computation in progress. Wait for it to finish.")
                        apply_action(room, session, command, words, hub.bot.mode)
                        await hub.broadcast(code)
                        hub.schedule(code)
                    except (ValidationError, ValueError) as exc:
                        message = str(exc) if isinstance(exc, GameError) else "Invalid command."
                        await ws.send_json({"type": "error", "message": message})
                        await ws.send_json({"type": "state", "room": project(
                            hub.rooms[code], session, hub.bot.mode,
                            hub.connections[code].values())})
        except WebSocketDisconnect:
            pass
        finally:
            hub.connections[code].pop(ws, None)
            async with hub.locks[code]:
                await hub.broadcast(code)

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="Run the single-process Gemma Codenames server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--demo", action="store_true", help="Explicit synthetic vectors for UI testing")
    args = parser.parse_args()
    if args.demo:
        os.environ["CODENAMES_MODE"] = "demo"
    uvicorn.run(create_app(), host=args.host, port=args.port, ws_max_size=4096)


if __name__ == "__main__":
    main()
