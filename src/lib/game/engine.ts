import type { BotProvider } from "../bot/provider";
import { shuffle, WORDS } from "./words";
import { SLOT_IDS, otherTeam } from "./types";
import type { ActionRequest, Card, CardKind, Room, RoomView, SlotId, Team } from "./types";

export class GameError extends Error {
  constructor(message: string, public status = 400) { super(message); }
}

function requireThat(condition: unknown, message: string, status = 400): asserts condition {
  if (!condition) throw new GameError(message, status);
}

export function remaining(room: Room, team: Team): number {
  return room.board.filter((card) => card.kind === team && !card.revealed).length;
}

export function makeBoard(random = Math.random): Card[] {
  const kinds = shuffle<CardKind>([
    ...Array<CardKind>(9).fill("red"), ...Array<CardKind>(8).fill("blue"),
    ...Array<CardKind>(7).fill("neutral"), "assassin",
  ], random);
  return shuffle(WORDS, random).slice(0, 25).map((word, index) => ({
    id: `w${index}`, word, kind: kinds[index], revealed: false,
  }));
}

export function createRoom(code: string, hostId: string, random = Math.random): Room {
  return {
    code, hostId, createdAt: new Date().toISOString(), version: 0, gameNumber: 1,
    board: makeBoard(random),
    seats: SLOT_IDS.map((id) => ({
      id, team: id.startsWith("red") ? "red" : "blue",
      role: id.endsWith("spymaster") ? "spymaster" : "guesser",
      controller: "bot", ownerId: null, name: null, ready: true,
    })),
    phase: "lobby", turn: "red", turnNumber: 1, clue: null, guesses: 0,
    winner: null, winReason: null, events: [], decisions: [], paused: false,
    nextBotAt: 0, processedActions: [], roleLocks: {},
  };
}

export function activeSlot(room: Room): SlotId | null {
  if (room.phase !== "clue" && room.phase !== "guess") return null;
  return `${room.turn}-${room.phase === "clue" ? "spymaster" : "guesser"}`;
}

function event(room: Room, kind: Room["events"][number]["kind"], text: string): void {
  room.events.push({ id: room.events.length + 1, turn: room.turnNumber, team: room.turn, kind, text });
}

function nextTurn(room: Room): void {
  room.turn = otherTeam(room.turn);
  room.turnNumber++;
  room.phase = "clue";
  room.clue = null;
  room.guesses = 0;
}

function finish(room: Room, winner: Team, reason: string): void {
  room.phase = "finished";
  room.winner = winner;
  room.winReason = reason;
  event(room, "system", `${winner === "red" ? "Red" : "Blue"} wins. ${reason}`);
}

export function revealCard(room: Room, cardId: string, reason?: string): void {
  requireThat(room.phase === "guess" && room.clue, "Wait for a clue.");
  const card = room.board.find((item) => item.id === cardId);
  requireThat(card && !card.revealed, "That word is not available.");
  card.revealed = true;
  room.guesses++;
  const kindLabel = card.kind === "neutral" ? "bystander" : card.kind;
  event(room, "guess", `${card.word} · ${kindLabel}${reason ? ` — ${reason}` : ""}`);
  if (card.kind === "assassin") finish(room, otherTeam(room.turn), "The assassin was revealed.");
  else if (remaining(room, "red") === 0) finish(room, "red", "All red agents were found.");
  else if (remaining(room, "blue") === 0) finish(room, "blue", "All blue agents were found.");
  else if (card.kind !== room.turn || room.guesses >= room.clue.count + 1) nextTurn(room);
}

function submitClue(room: Room, word: string, count: number, provider: BotProvider): void {
  const normalized = word.trim().toLowerCase();
  requireThat(/^[a-z]{2,24}$/.test(normalized), "Use one word, 2–24 letters.");
  requireThat(Number.isInteger(count) && count >= 1 && count <= remaining(room, room.turn), "Choose a count between 1 and your remaining agents.");
  const stem = (value: string) => value.toLowerCase().replace(/(?:es|s)$/, "");
  requireThat(!room.board.some((card) => !card.revealed && (
    stem(card.word) === stem(normalized) ||
    (normalized.length >= 3 && card.word.toLowerCase().includes(normalized)) ||
    normalized.includes(card.word.toLowerCase())
  )), "A clue cannot use an unrevealed board word or its word form.");
  room.clue = {
    word: normalized, count, team: room.turn, scores: provider.scoreClue(normalized, room.board),
    analysis: { source: provider.source, summary: "Human clue. The displayed scores are demo fixtures; Gemma is not connected.", targets: [], weakestTarget: null, closestDanger: null, gap: null, alternatives: [] },
  };
  room.decisions.push({ turn: room.turnNumber, clue: structuredClone(room.clue) });
  room.phase = "guess";
  room.guesses = 0;
  event(room, "clue", `${normalized.toUpperCase()} · ${count}`);
}

export function advanceBot(room: Room, provider: BotProvider, now = Date.now(), force = false): boolean {
  const slot = room.seats.find((seat) => seat.id === activeSlot(room));
  if (!slot || slot.controller !== "bot" || (!force && (room.paused || now < room.nextBotAt))) return false;
  if (room.phase === "clue") {
    const proposal = provider.proposeClue(room.board, room.turn);
    room.clue = { ...proposal, team: room.turn };
    room.decisions.push({ turn: room.turnNumber, clue: structuredClone(room.clue) });
    room.phase = "guess";
    room.guesses = 0;
    event(room, "clue", `${proposal.word.toUpperCase()} · ${proposal.count}`);
  } else if (room.phase === "guess" && room.clue) {
    const proposal = provider.chooseGuess({
      cards: room.board.map(({ id, word, revealed }) => ({ id, word, revealed })),
      clue: { word: room.clue.word, count: room.clue.count, scores: room.clue.scores },
      guesses: room.guesses,
    });
    if (proposal.cardId) revealCard(room, proposal.cardId, proposal.reason);
    else { event(room, "end", proposal.reason); nextTurn(room); }
  }
  room.version++;
  room.nextBotAt = now + 2400;
  return true;
}

export function applyAction(room: Room, sessionId: string, request: ActionRequest, provider: BotProvider): void {
  // Retried requests are idempotent even if the board has since advanced.
  const receipt = `${sessionId}:${request.actionId}`;
  if (room.processedActions.includes(receipt)) return;
  const action = request.action;
  // Independent lobby changes can be validated against the latest state. They
  // must not reject one player's Ready because another player just joined.
  if (!["claim", "ready", "leave"].includes(action.type)) {
    requireThat(request.version === room.version, "The room changed. Review the board and try again.", 409);
  }
  const yours = room.seats.find((seat) => seat.ownerId === sessionId);
  const isHost = room.hostId === sessionId;
  const allBots = room.seats.every((seat) => seat.controller === "bot");
  if (["start", "pause", "step", "replace", "rematch"].includes(action.type)) requireThat(isHost, "Only the host can do that.", 403);
  if (["clue", "guess", "end-turn"].includes(action.type)) {
    requireThat(yours && yours.controller === "human" && yours.id === activeSlot(room), "It is not your turn.", 403);
  }
  switch (action.type) {
    case "claim": {
      const target = room.seats.find((seat) => seat.id === action.slotId);
      requireThat(target && (!target.ownerId || target.ownerId === sessionId), "That slot is already taken.", 409);
      requireThat(room.phase === "lobby" || (action.controller === "bot" && target.controller === "bot"), "Join as a watcher now, or play on the next board.");
      requireThat(!room.roleLocks[sessionId] || room.roleLocks[sessionId] === action.slotId, "Your role is locked until the next board.", 403);
      if (yours && yours !== target) Object.assign(yours, { ownerId: null, name: null, controller: "bot", ready: true });
      Object.assign(target, { ownerId: sessionId, name: action.name.trim() || "Guest", controller: action.controller, ready: action.controller === "bot" });
      if (room.phase !== "lobby") room.roleLocks[sessionId] = target.id;
      break;
    }
    case "leave":
      requireThat(room.phase === "lobby", "Slots are locked until the next board.");
      requireThat(yours, "Choose a slot first.");
      Object.assign(yours, { ownerId: null, name: null, controller: "bot", ready: true });
      break;
    case "ready":
      requireThat(room.phase === "lobby" && yours?.controller === "human", "Choose a human slot first.");
      yours.ready = !yours.ready;
      break;
    case "start":
      requireThat(room.phase === "lobby", "The game has already started.");
      requireThat(room.seats.every((seat) => seat.controller === "bot" || seat.ready), "Wait for every player to be ready.");
      room.phase = "clue";
      for (const seat of room.seats) if (seat.ownerId) room.roleLocks[seat.ownerId] = seat.id;
      event(room, "system", "Red starts. Find all your agents.");
      break;
    case "clue":
      requireThat(room.phase === "clue", "A clue has already been given.");
      submitClue(room, action.word, action.count, provider);
      break;
    case "guess":
      revealCard(room, action.cardId);
      break;
    case "end-turn":
      requireThat(room.phase === "guess" && room.guesses > 0, "Make at least one guess before ending the turn.");
      event(room, "end", "Turn ended.");
      nextTurn(room);
      break;
    case "pause":
      requireThat(allBots && (room.phase === "clue" || room.phase === "guess"), "Pause is available during all-bot games.");
      room.paused = !room.paused;
      break;
    case "step":
      requireThat(allBots && room.paused && activeSlot(room), "Pause an all-bot game before stepping.");
      advanceBot(room, provider, Date.now(), true);
      break;
    case "replace": {
      const target = room.seats.find((seat) => seat.id === action.slotId);
      requireThat(target?.controller === "human", "That slot already has a bot.");
      target.controller = "bot";
      target.ready = true;
      event(room, "system", `${target.team} ${target.role} is now controlled by a bot.`);
      break;
    }
    case "rematch": {
      requireThat(room.phase === "finished", "Finish this board before starting another.");
      const next = createRoom(room.code, room.hostId);
      Object.assign(room, next, {
        createdAt: room.createdAt, version: room.version, gameNumber: room.gameNumber + 1,
        seats: room.seats.map((seat) => ({ ...seat, ready: seat.controller === "bot" })),
        processedActions: room.processedActions,
      });
      break;
    }
  }
  room.version++;
  room.nextBotAt = Date.now() + 2400;
  room.processedActions = [...room.processedActions.slice(-199), receipt];
}

export function projectRoom(room: Room, sessionId: string): RoomView {
  const yours = room.seats.find((seat) => seat.ownerId === sessionId);
  const canSeeKey = room.phase === "finished" || (room.phase !== "lobby" && yours?.role === "spymaster");
  return {
    code: room.code, version: room.version, gameNumber: room.gameNumber,
    phase: room.phase, turn: room.turn, turnNumber: room.turnNumber,
    board: room.board.map(({ kind, ...card }) => ({ ...card, kind: canSeeKey || card.revealed ? kind : null, score: room.clue?.scores[card.id] ?? null })),
    seats: room.seats.map(({ ownerId, ...seat }) => ({ ...seat, occupied: ownerId !== null, isYou: ownerId === sessionId })),
    yourSeat: yours?.id ?? null, isHost: room.hostId === sessionId, canSeeKey,
    clue: room.clue ? { word: room.clue.word, count: room.clue.count, team: room.clue.team, source: room.clue.analysis.source } : null,
    analysis: canSeeKey && room.clue ? structuredClone(room.clue.analysis) : null,
    remaining: { red: remaining(room, "red"), blue: remaining(room, "blue") },
    guesses: room.guesses, guessesLeft: room.clue ? Math.max(0, room.clue.count + 1 - room.guesses) : 0,
    winner: room.winner, winReason: room.winReason,
    events: structuredClone(room.events), paused: room.paused, activeSlot: activeSlot(room),
    allBots: room.seats.every((seat) => seat.controller === "bot"),
    canStart: room.phase === "lobby" && room.seats.every((seat) => seat.controller === "bot" || seat.ready),
  };
}
