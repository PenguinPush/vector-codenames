import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomBytes } from "node:crypto";
import { demoBot } from "../bot/demo";
import { advanceBot, applyAction, createRoom, GameError, projectRoom } from "../game/engine";
import type { ActionRequest, Room, RoomView } from "../game/types";

type Store = { rooms: Map<string, Room>; loaded: boolean; queue: Promise<unknown> };
const globalStore = globalThis as typeof globalThis & { codenamesStore?: Store };
const store = globalStore.codenamesStore ??= { rooms: new Map(), loaded: false, queue: Promise.resolve() };
const directory = path.resolve(process.env.CODENAMES_DATA_DIR ?? ".data");
const filename = path.join(directory, "rooms.json");

async function load(): Promise<void> {
  if (store.loaded) return;
  try {
    const rooms = JSON.parse(await readFile(filename, "utf8")) as Room[];
    for (const room of rooms) store.rooms.set(room.code, room);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  store.loaded = true;
}

async function persist(): Promise<void> {
  await mkdir(directory, { recursive: true });
  await writeFile(`${filename}.tmp`, JSON.stringify([...store.rooms.values()]), { mode: 0o600 });
  await rename(`${filename}.tmp`, filename);
}

function replayData(room: Room) {
  return {
    code: room.code, gameNumber: room.gameNumber, source: "demo", winner: room.winner,
    board: room.board, events: room.events, decisions: room.decisions,
  };
}

async function archiveFinished(room: Room): Promise<void> {
  if (room.phase !== "finished") return;
  const replays = path.join(directory, "replays");
  await mkdir(replays, { recursive: true });
  await writeFile(path.join(replays, `${room.code}-${room.gameNumber}.json`), JSON.stringify(replayData(room), null, 2), { mode: 0o600 });
}

function serial<T>(work: () => Promise<T>): Promise<T> {
  const result = store.queue.then(async () => { await load(); return work(); });
  store.queue = result.catch(() => undefined);
  return result;
}

function find(code: string): Room {
  const room = store.rooms.get(code.toUpperCase());
  if (!room) throw new GameError("Room not found. Check the code and try again.", 404);
  return room;
}

export function newRoom(sessionId: string): Promise<RoomView> {
  return serial(async () => {
    let code: string;
    do { code = randomBytes(4).toString("hex").slice(0, 6).toUpperCase(); } while (store.rooms.has(code));
    const room = createRoom(code, sessionId);
    store.rooms.set(code, room);
    await persist();
    return projectRoom(room, sessionId);
  });
}

export function roomView(code: string, sessionId: string, tick = false): Promise<RoomView> {
  return serial(async () => {
    const room = find(code);
    if (tick && advanceBot(room, demoBot)) { await persist(); await archiveFinished(room); }
    return projectRoom(room, sessionId);
  });
}

export function act(code: string, sessionId: string, request: ActionRequest): Promise<RoomView> {
  return serial(async () => {
    const current = find(code);
    // A rejected action cannot leave a partially changed room behind.
    const room = structuredClone(current);
    applyAction(room, sessionId, request, demoBot);
    store.rooms.set(room.code, room);
    await persist();
    await archiveFinished(room);
    return projectRoom(room, sessionId);
  });
}

export function replay(code: string): Promise<unknown> {
  return serial(async () => {
    const room = find(code);
    if (room.phase !== "finished") throw new GameError("The full replay is available after the game.", 403);
    return replayData(room);
  });
}
