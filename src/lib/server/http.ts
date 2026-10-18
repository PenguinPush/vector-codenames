import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { GameError } from "../game/engine";
import { SLOT_IDS, type ActionRequest, type GameAction, type SlotId } from "../game/types";

export const SESSION_COOKIE = "codenames-session";
export function session(request: NextRequest): string {
  const value = request.cookies.get(SESSION_COOKIE)?.value;
  return value && /^[a-f0-9-]{36}$/.test(value) ? value : randomUUID();
}

export function json(value: unknown, request: NextRequest, sessionId: string): NextResponse {
  const response = NextResponse.json(value, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(SESSION_COOKIE, sessionId, {
    httpOnly: true, sameSite: "lax", secure: request.nextUrl.protocol === "https:",
    path: "/", maxAge: 60 * 60 * 24 * 30,
  });
  return response;
}

export function errorResponse(error: unknown): NextResponse {
  if (error instanceof GameError) return NextResponse.json({ error: error.message }, { status: error.status });
  console.error("Room request failed", error);
  return NextResponse.json({ error: "The server could not complete that action. Try again." }, { status: 500 });
}

export function checkOrigin(request: NextRequest): void {
  const origin = request.headers.get("origin");
  if (!origin) return;
  // Next can normalize nextUrl to localhost even when a client uses a LAN IP.
  // Compare the browser's origin with the actual incoming HTTP Host instead.
  let source: URL;
  try { source = new URL(origin); } catch { throw new GameError("Invalid request origin.", 403); }
  if (!["http:", "https:"].includes(source.protocol) || source.host !== request.headers.get("host")) {
    throw new GameError("Use the room page to submit an action.", 403);
  }
}

export async function readAction(request: NextRequest): Promise<ActionRequest> {
  checkOrigin(request);
  const raw = await request.text();
  if (raw.length > 4096) throw new GameError("Action is too large.", 413);
  let body: Record<string, unknown>;
  try { body = JSON.parse(raw); } catch { throw new GameError("Invalid action."); }
  if (!body || typeof body !== "object" || typeof body.actionId !== "string" ||
    !/^[a-zA-Z0-9-]{8,80}$/.test(body.actionId) || !Number.isInteger(body.version) ||
    !body.action || typeof body.action !== "object") throw new GameError("Invalid action.");
  const value = body.action as Record<string, unknown>;
  const slot = () => {
    if (!SLOT_IDS.includes(value.slotId as SlotId)) throw new GameError("Invalid slot.");
    return value.slotId as SlotId;
  };
  let action: GameAction;
  switch (value.type) {
    case "claim":
      if (!["human", "bot"].includes(value.controller as string) || typeof value.name !== "string" || value.name.length > 24) throw new GameError("Use a name up to 24 characters.");
      action = { type: "claim", slotId: slot(), controller: value.controller as "human" | "bot", name: value.name };
      break;
    case "replace": action = { type: "replace", slotId: slot() }; break;
    case "clue":
      if (typeof value.word !== "string" || typeof value.count !== "number") throw new GameError("Enter a word and count.");
      action = { type: "clue", word: value.word, count: value.count };
      break;
    case "guess":
      if (typeof value.cardId !== "string" || !/^w\d{1,2}$/.test(value.cardId)) throw new GameError("Select a word.");
      action = { type: "guess", cardId: value.cardId }; break;
    case "leave": case "ready": case "start": case "end-turn": case "pause": case "step": case "rematch":
      action = { type: value.type }; break;
    default: throw new GameError("Unknown action.");
  }
  return { actionId: body.actionId, version: body.version as number, action };
}
