"""Authoritative game rules. This module has no browser or model dependencies."""

import copy
import secrets
import time
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .board import BoardSize, Card, random_board
from .communication import CommunicationConfig
from .optimizer import CluePolicy

SLOTS = ("red-spymaster", "blue-spymaster", "red-guesser", "blue-guesser")
Slot = Literal["red-spymaster", "blue-spymaster", "red-guesser", "blue-guesser"]


class GameError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require(condition, message, status=400):
    if not condition:
        raise GameError(message, status)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Claim(Strict):
    type: Literal["claim"]
    slotId: Slot
    controller: Literal["human", "bot"]
    name: str = Field(default="Guest", max_length=24)


class ClueAction(Strict):
    type: Literal["clue"]
    word: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z]+$")
    count: int = Field(ge=1, le=34)


class Configure(Strict):
    type: Literal["configure"]
    communication: CommunicationConfig
    board_size: BoardSize = 25


class Guess(Strict):
    type: Literal["guess"]
    cardId: str = Field(pattern=r"^w(?:[0-9]|[1-9][0-9])$")


class Replace(Strict):
    type: Literal["replace"]
    slotId: Slot


class SimpleAction(Strict):
    type: Literal["leave", "ready", "start", "end-turn", "pause", "step", "rematch", "retry", "spectate"]


class Command(Strict):
    actionId: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9-]+$")
    version: int = Field(ge=0)
    action: Annotated[Claim | ClueAction | Guess | Replace | SimpleAction | Configure,
                      Field(discriminator="type")]


def make_room(code, host, words, board_size=25):
    cards = random_board(words, secrets.randbits(64), size=board_size)
    return {
        "code": code, "hostId": host, "createdAt": datetime.now(timezone.utc).isoformat(),
        "version": 0, "gameNumber": 1, "board_size": board_size,
        "board": [{"id": f"w{i}", "word": c.word.upper(), "kind": c.kind, "revealed": False}
                  for i, c in enumerate(cards)],
        "seats": [{"id": slot, "team": slot.split("-")[0], "role": slot.split("-")[1],
                   "controller": "bot", "ownerId": None, "name": None, "ready": True}
                  for slot in SLOTS],
        "phase": "lobby", "turn": "red", "turnNumber": 1, "clue": None, "guesses": 0,
        "winner": None, "winReason": None, "events": [], "decisions": [], "paused": False,
        "processedActions": [], "roleLocks": {}, "pending": False, "botError": None,
        "stepRequested": False, "nextBotAt": 0, "stage": None, "geometry": False, "communication": {},
    }


def remaining(room, team):
    return sum(c["kind"] == team and not c["revealed"] for c in room["board"])


def active_slot(room):
    if room["phase"] not in ("clue", "guess"):
        return None
    return f"{room['turn']}-{'spymaster' if room['phase'] == 'clue' else 'guesser'}"


def event(room, kind, text):
    room["events"].append({"id": len(room["events"]) + 1, "turn": room["turnNumber"],
                           "team": room["turn"], "kind": kind, "text": text})


def next_turn(room):
    room.update(turn="blue" if room["turn"] == "red" else "red", phase="clue",
                turnNumber=room["turnNumber"] + 1, clue=None, guesses=0)


def finish(room, winner, reason):
    room.update(phase="finished", winner=winner, winReason=reason)
    event(room, "system", f"{winner.title()} wins. {reason}")


def reveal(room, card_id, reason=None):
    require(room["phase"] == "guess" and room["clue"], "Wait for a clue.")
    card = next((c for c in room["board"] if c["id"] == card_id), None)
    require(card and not card["revealed"], "That word is not available.")
    card["revealed"] = True
    room["guesses"] += 1
    label = "bystander" if card["kind"] == "neutral" else card["kind"]
    event(room, "guess", f"{card['word']} · {label}" + (f" — {reason}" if reason else ""))
    if card["kind"] == "assassin":
        finish(room, "blue" if room["turn"] == "red" else "red", "The assassin was revealed.")
    elif remaining(room, "red") == 0:
        finish(room, "red", "All red agents were found.")
    elif remaining(room, "blue") == 0:
        finish(room, "blue", "All blue agents were found.")
    elif card["kind"] != room["turn"] or room["guesses"] >= room["clue"]["count"] + 1:
        next_turn(room)


def accept_clue(room, clue):
    room.update(clue=clue, phase="guess", guesses=0)
    room["decisions"].append({"turn": room["turnNumber"], "clue": copy.deepcopy(clue)})
    event(room, "clue", f"{clue['word'].upper()} · {clue['count']}")


def apply_action(room, session, command: Command, words, mode):
    receipt = f"{session}:{command.actionId}"
    if receipt in room["processedActions"]:
        return False
    action = command.action.model_dump()
    kind = action["type"]
    if kind not in ("claim", "leave", "ready", "retry"):
        require(command.version == room["version"],
                "The room changed. Review the board and try again.", 409)
    yours = next((s for s in room["seats"] if s["ownerId"] == session), None)
    all_bots = all(s["controller"] == "bot" for s in room["seats"])
    if kind in ("start", "pause", "step", "replace", "rematch", "retry", "configure"):
        require(session == room["hostId"], "Only the host can do that.", 403)
    if kind in ("clue", "guess", "end-turn"):
        require(yours and yours["controller"] == "human" and yours["id"] == active_slot(room),
                "It is not your turn.", 403)
        require(not room["pending"] and not room["botError"], "Wait for the scores to finish.")
    if kind == "configure":
        require(room["phase"] == "lobby", "Configuration is locked during a game.")
        room["communication"] = action["communication"]
        if action["board_size"] != room["board_size"]:
            fresh = make_room(room["code"], room["hostId"], words, action["board_size"])
            room["board"] = fresh["board"]
            room["board_size"] = action["board_size"]
            for seat in room["seats"]:
                seat["ready"] = seat["controller"] == "bot"
    elif kind == "spectate":
        require(not yours, "Leave your slot before choosing analysis spectator.")
        require(session not in room["roleLocks"] or room["roleLocks"][session] == "spectator",
                "Your role is locked until the next board.")
        room["roleLocks"][session] = "spectator"
    elif kind == "claim":
        target = next(s for s in room["seats"] if s["id"] == action["slotId"])
        require(target["ownerId"] in (None, session), "That slot is already taken.", 409)
        require(room["phase"] == "lobby" or (action["controller"] == "bot"
                and target["controller"] == "bot"), "Watch now, or play on the next board.")
        require(room["roleLocks"].get(session, target["id"]) == target["id"],
                "Your role is locked until the next board.", 403)
        if yours and yours is not target:
            yours.update(ownerId=None, name=None, controller="bot", ready=True)
        target.update(ownerId=session, name=action["name"].strip() or "Guest",
                      controller=action["controller"], ready=action["controller"] == "bot")
        if room["phase"] != "lobby":
            room["roleLocks"][session] = target["id"]
    elif kind == "leave":
        require(room["phase"] == "lobby" and yours, "Slots are locked until the next board.")
        yours.update(ownerId=None, name=None, controller="bot", ready=True)
    elif kind == "ready":
        require(room["phase"] == "lobby" and yours and yours["controller"] == "human",
                "Choose a human slot first.")
        yours["ready"] = not yours["ready"]
    elif kind == "start":
        require(room["phase"] == "lobby", "The game has already started.")
        require(all(s["ready"] for s in room["seats"]), "Wait for everyone to be ready.")
        room["phase"] = "clue"
        room["paused"] = all_bots
        room["roleLocks"].update({s["ownerId"]: s["id"] for s in room["seats"] if s["ownerId"]})
        event(room, "system", "Red starts. Find all your agents.")
    elif kind == "clue":
        require(room["phase"] == "clue", "A clue has already been given.")
        require(action["count"] <= remaining(room, room["turn"]), "That count is too large.")
        cards = [Card(c["word"], c["kind"], c["revealed"]) for c in room["board"]]
        require(CluePolicy(cards).allows(action["word"].lower()),
                "A clue cannot reuse an unrevealed board word or its word form.")
        accept_clue(room, {
            "word": action["word"].lower(), "count": action["count"], "team": room["turn"],
            "scores": {}, "analysis": {"source": mode, "summary": "Clue supplied by a player.",
                "targets": [], "weakestTarget": None, "closestDanger": None, "gap": None,
                "alternatives": [], "fallback": False},
        })
    elif kind == "guess":
        require(room["clue"] and room["clue"]["scores"], "Wait for the clue scores.")
        reveal(room, action["cardId"])
    elif kind == "end-turn":
        require(room["phase"] == "guess" and room["guesses"] > 0,
                "Make at least one guess before ending the turn.")
        event(room, "end", "Turn ended.")
        next_turn(room)
    elif kind == "pause":
        require(all_bots and active_slot(room), "Pause is available during all-bot games.")
        room["paused"] = not room["paused"]
        room["stepRequested"] = False
    elif kind == "step":
        require(all_bots and room["paused"] and active_slot(room), "Pause before stepping.")
        require(not room["pending"] and not room["botError"], "Wait or retry the failed turn.")
        room["stepRequested"] = True
    elif kind == "replace":
        require(room["phase"] != "finished", "This game has finished.")
        target = next(s for s in room["seats"] if s["id"] == action["slotId"])
        require(target["controller"] == "human", "That slot already has a bot.")
        target.update(controller="bot", ready=True)
        event(room, "system", f"{target['team']} {target['role']} is now controlled by a bot.")
    elif kind == "retry":
        require(room["botError"] and not room["pending"], "There is no failed inference to retry.")
        room["botError"] = None
    elif kind == "rematch":
        require(room["phase"] == "finished", "Finish this board first.")
        fresh = make_room(room["code"], room["hostId"], words, room["board_size"])
        fresh.update(createdAt=room["createdAt"], version=room["version"],
                     gameNumber=room["gameNumber"] + 1, seats=room["seats"],
                     processedActions=room["processedActions"], geometry=room["geometry"], communication=room["communication"])
        for seat in fresh["seats"]:
            seat["ready"] = seat["controller"] == "bot"
        room.clear()
        room.update(fresh)
    room["version"] += 1
    room["nextBotAt"] = time.time() + 1.5
    room["processedActions"] = [*room["processedActions"][-199:], receipt]
    return True


def project(room, session, mode, online=()):
    yours = next((s for s in room["seats"] if s["ownerId"] == session), None)
    key = room["phase"] == "finished" or (
        room["phase"] != "lobby" and ((yours is not None and yours["role"] == "spymaster")
        or room["roleLocks"].get(session) == "spectator"))
    diagnostics = yours is None
    clue = room["clue"]
    fields = ("code", "version", "gameNumber", "phase", "turn", "turnNumber", "guesses",
              "winner", "winReason", "events", "paused", "pending", "botError", "stage", "geometry", "communication", "board_size")
    view = {name: copy.deepcopy(room[name]) for name in fields}
    view.update({
        "spectator": room["roleLocks"].get(session) == "spectator",
        "botMode": mode, "yourSeat": yours["id"] if yours else None,
        "liveSearch": copy.deepcopy(room.get("liveSearch")) if diagnostics and room["roleLocks"].get(session) == "spectator" else None,
        "isHost": room["hostId"] == session, "canSeeKey": key, "canSeeAnalysis": diagnostics,
        "board": [{**c, "kind": c["kind"] if key or c["revealed"] else None,
                   "score": clue["scores"].get(c["id"]) if clue and diagnostics else None}
                  for c in room["board"]],
        "seats": [{**{k: v for k, v in s.items() if k != "ownerId"},
                   "occupied": s["ownerId"] is not None, "isYou": s["ownerId"] == session,
                   "online": s["ownerId"] in online} for s in room["seats"]],
        "clue": {k: copy.deepcopy(clue.get(k)) for k in ("word", "count", "team", "message")} if clue else None,
        "analysis": copy.deepcopy(clue["analysis"]) if key and diagnostics and clue else None,
        "plot": copy.deepcopy(clue.get("plot")) if clue and diagnostics else None,
        "history": [copy.deepcopy(d) if key and diagnostics else {
            "turn": d["turn"], "clue": {k: copy.deepcopy(d["clue"].get(k))
                for k in (("word", "count", "team", "scores", "plot", "message") if diagnostics
                          else ("word", "count", "team", "message"))}}
            for d in room["decisions"]],
        "remaining": {team: remaining(room, team) for team in ("red", "blue")},
        "guessesLeft": max(0, clue["count"] + 1 - room["guesses"]) if clue else 0,
        "activeSlot": active_slot(room),
        "allBots": all(s["controller"] == "bot" for s in room["seats"]),
        "canStart": room["phase"] == "lobby" and all(s["ready"] for s in room["seats"]),
    })
    if not diagnostics:
        view['stage'] = 'Bot is thinking…' if room['pending'] else None
        view['botError'] = 'Bot could not complete its turn. Ask the host to retry.' if room['botError'] else None
        for entry in view['events']:
            if entry['kind'] == 'guess':
                entry['text'] = entry['text'].split(' — ', 1)[0]
        for entry in [view['clue'], *(d['clue'] for d in view['history'])]:
            if entry and entry.get('message'):
                entry['message'].pop('model', None)
    return view
