import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { activeSlot, advanceBot, applyAction, createRoom, GameError, projectRoom, revealCard } from "../src/lib/game/engine";
import { demoBot } from "../src/lib/bot/demo";
import type { BotProvider } from "../src/lib/bot/provider";
import { SLOT_IDS, type GameAction, type Room } from "../src/lib/game/types";

function act(room: Room, session: string, action: GameAction) {
  applyAction(room, session, { action, version: room.version, actionId: randomUUID() }, demoBot);
}
function started() {
  const room = createRoom("ABC123", "host");
  act(room, "host", { type: "start" });
  advanceBot(room, demoBot, Date.now(), true);
  return room;
}

test("board has 25 unique words and standard role counts", () => {
  const room = createRoom("ABC123", "host");
  assert.equal(new Set(room.board.map((card) => card.word)).size, 25);
  for (const [kind, count] of [["red", 9], ["blue", 8], ["neutral", 7], ["assassin", 1]] as const) {
    assert.equal(room.board.filter((card) => card.kind === kind).length, count);
  }
});

test("all 16 human/bot combinations can claim, ready and start", () => {
  for (let mask = 0; mask < 16; mask++) {
    const room = createRoom("ABC123", "host");
    SLOT_IDS.forEach((slotId, i) => {
      const controller = mask & (1 << i) ? "human" : "bot";
      act(room, `player${i}`, { type: "claim", slotId, controller, name: `P${i}` });
      if (controller === "human") act(room, `player${i}`, { type: "ready" });
    });
    act(room, "host", { type: "start" });
    assert.equal(room.phase, "clue");
    assert.equal(activeSlot(room), "red-spymaster");
  }
});

test("slot claims are exclusive and an unready human prevents start", () => {
  const room = createRoom("ABC123", "host");
  act(room, "one", { type: "claim", slotId: "red-guesser", controller: "human", name: "One" });
  assert.throws(() => act(room, "two", { type: "claim", slotId: "red-guesser", controller: "human", name: "Two" }), /taken/);
  assert.throws(() => act(room, "host", { type: "start" }), /ready/);
  assert.throws(() => act(room, "one", { type: "start" }), /host/);
});

test("hidden keys and private analysis never appear in guesser or guest projections", () => {
  const room = createRoom("ABC123", "host");
  act(room, "spy", { type: "claim", slotId: "red-spymaster", controller: "bot", name: "Spy" });
  act(room, "guess", { type: "claim", slotId: "red-guesser", controller: "bot", name: "Guess" });
  assert.ok(projectRoom(room, "spy").board.every((card) => card.kind === null), "lobby keys stay hidden");
  act(room, "host", { type: "start" });
  advanceBot(room, demoBot, Date.now(), true);
  for (const session of ["guess", "guest"]) {
    const view = projectRoom(room, session);
    assert.ok(view.board.every((card) => card.kind === null));
    assert.equal(view.analysis, null);
    assert.ok(!JSON.stringify(view).includes("ownerId"));
    assert.ok(!JSON.stringify(view).includes("hostId"));
    assert.ok(!JSON.stringify(view).includes("targets"));
  }
  assert.ok(projectRoom(room, "spy").board.every((card) => card.kind !== null));
  assert.ok(projectRoom(room, "spy").analysis);
});

test("independent lobby changes do not invalidate another player's Ready", () => {
  const room = createRoom("ABC123", "host");
  act(room, "one", { type: "claim", slotId: "red-spymaster", controller: "human", name: "One" });
  const oldVersion = room.version;
  act(room, "two", { type: "claim", slotId: "red-guesser", controller: "human", name: "Two" });
  applyAction(room, "one", { version: oldVersion, actionId: randomUUID(), action: { type: "ready" } }, demoBot);
  assert.equal(room.seats.find((seat) => seat.ownerId === "one")?.ready, true);
});

test("a spymaster cannot switch to guessing after seeing the key", () => {
  const room = createRoom("ABC123", "host");
  act(room, "spy", { type: "claim", slotId: "red-spymaster", controller: "bot", name: "Spy" });
  act(room, "host", { type: "start" });
  assert.throws(() => act(room, "spy", { type: "claim", slotId: "blue-guesser", controller: "bot", name: "Spy" }), /locked/);
  assert.throws(() => act(room, "spy", { type: "leave" }), /locked/);
});

test("bot guesser input contains no key or intended targets", () => {
  const room = started();
  let called = false;
  const provider: BotProvider = {
    ...demoBot,
    chooseGuess(input) {
      called = true;
      assert.ok(input.cards.every((card) => !("kind" in card)));
      assert.ok(!("analysis" in input.clue));
      return demoBot.chooseGuess(input);
    },
  };
  advanceBot(room, provider, Date.now(), true);
  assert.ok(called);
});

test("assassin ends the game immediately and reveals the full key", () => {
  const room = started();
  revealCard(room, room.board.find((card) => card.kind === "assassin")!.id);
  assert.equal(room.phase, "finished");
  assert.equal(room.winner, "blue");
  assert.ok(projectRoom(room, "guest").board.every((card) => card.kind));
});

test("wrong guesses end the turn and count toward the opposing team", () => {
  const room = started();
  const target = room.board.find((card) => card.kind === "blue")!;
  revealCard(room, target.id);
  assert.equal(room.phase, "clue");
  assert.equal(room.turn, "blue");
  assert.equal(projectRoom(room, "guest").remaining.blue, 7);
});

test("humans may take count plus one guesses, then the turn ends", () => {
  const room = started();
  room.clue!.count = 1;
  const friendly = room.board.filter((card) => card.kind === "red");
  revealCard(room, friendly[0].id);
  assert.equal(room.phase, "guess");
  revealCard(room, friendly[1].id);
  assert.equal(room.phase, "clue");
  assert.equal(room.turn, "blue");
});

test("human inputs obey turn, clue legality, and minimum-guess rules", () => {
  const room = createRoom("ABC123", "host");
  act(room, "spy", { type: "claim", slotId: "red-spymaster", controller: "human", name: "Spy" });
  act(room, "guess", { type: "claim", slotId: "red-guesser", controller: "human", name: "Guess" });
  act(room, "spy", { type: "ready" }); act(room, "guess", { type: "ready" }); act(room, "host", { type: "start" });
  assert.throws(() => act(room, "guess", { type: "clue", word: "orbit", count: 1 }), /turn/);
  assert.throws(() => act(room, "spy", { type: "clue", word: room.board[0].word, count: 1 }), /board word/);
  assert.throws(() => act(room, "spy", { type: "clue", word: "two words", count: 1 }), /one word/);
  act(room, "spy", { type: "clue", word: "orbit", count: 1 });
  assert.throws(() => act(room, "guess", { type: "end-turn" }), /at least one/);
});

test("retries are idempotent and stale new actions are rejected", () => {
  const room = createRoom("ABC123", "host");
  const request = { version: 0, actionId: randomUUID(), action: { type: "start" } as const };
  applyAction(room, "host", request, demoBot);
  const version = room.version;
  applyAction(room, "host", request, demoBot);
  assert.equal(room.version, version);
  assert.throws(() => applyAction(room, "host", { ...request, actionId: randomUUID() }, demoBot), (error: unknown) => error instanceof GameError && error.status === 409);
});

test("all-bot match can pause, step, finish, and reset role locks for a rematch", () => {
  const room = createRoom("ABC123", "host");
  act(room, "host", { type: "claim", slotId: "red-spymaster", controller: "bot", name: "Host" });
  act(room, "host", { type: "start" });
  act(room, "host", { type: "pause" });
  assert.equal(advanceBot(room, demoBot, Date.now() + 10000), false);
  act(room, "host", { type: "step" });
  assert.equal(room.phase, "guess");
  let steps = 0;
  while (!room.winner && steps++ < 100) advanceBot(room, demoBot, Date.now(), true);
  assert.equal(room.phase, "finished");
  const version = room.version;
  act(room, "host", { type: "rematch" });
  assert.equal(room.phase, "lobby");
  assert.equal(room.gameNumber, 2);
  assert.ok(room.version > version);
  assert.deepEqual(room.roleLocks, {});
  assert.equal(room.events.length, 0);
});
