export type Team = "red" | "blue";
export type Role = "spymaster" | "guesser";
export type SlotId = `${Team}-${Role}`;
export type Controller = "human" | "bot";
export type CardKind = Team | "neutral" | "assassin";
export type Phase = "lobby" | "clue" | "guess" | "finished";

export interface Card {
  id: string;
  word: string;
  kind: CardKind;
  revealed: boolean;
}

export interface Seat {
  id: SlotId;
  team: Team;
  role: Role;
  controller: Controller;
  ownerId: string | null;
  name: string | null;
  ready: boolean;
}

export interface Analysis {
  source: "demo" | "gemma";
  summary: string;
  targets: string[];
  weakestTarget: { word: string; score: number } | null;
  closestDanger: { word: string; score: number } | null;
  gap: number | null;
  alternatives: { word: string; count: number }[];
}

export interface Clue {
  word: string;
  count: number;
  team: Team;
  scores: Record<string, number>;
  analysis: Analysis;
}

export interface GameEvent {
  id: number;
  turn: number;
  team: Team;
  kind: "clue" | "guess" | "end" | "system";
  text: string;
}

export interface Room {
  code: string;
  hostId: string;
  createdAt: string;
  version: number;
  gameNumber: number;
  board: Card[];
  seats: Seat[];
  phase: Phase;
  turn: Team;
  turnNumber: number;
  clue: Clue | null;
  guesses: number;
  winner: Team | null;
  winReason: string | null;
  events: GameEvent[];
  decisions: { turn: number; clue: Clue }[];
  paused: boolean;
  nextBotAt: number;
  processedActions: string[];
  roleLocks: Record<string, SlotId>;
}

export interface PublicSeat extends Omit<Seat, "ownerId"> {
  occupied: boolean;
  isYou: boolean;
}

export interface RoomView {
  code: string;
  version: number;
  gameNumber: number;
  phase: Phase;
  turn: Team;
  turnNumber: number;
  board: (Omit<Card, "kind"> & { kind: CardKind | null; score: number | null })[];
  seats: PublicSeat[];
  yourSeat: SlotId | null;
  isHost: boolean;
  canSeeKey: boolean;
  clue: { word: string; count: number; team: Team; source: "demo" | "gemma" } | null;
  analysis: Analysis | null;
  remaining: Record<Team, number>;
  guesses: number;
  guessesLeft: number;
  winner: Team | null;
  winReason: string | null;
  events: GameEvent[];
  paused: boolean;
  activeSlot: SlotId | null;
  allBots: boolean;
  canStart: boolean;
}

export type GameAction =
  | { type: "claim"; slotId: SlotId; controller: Controller; name: string }
  | { type: "leave" }
  | { type: "ready" }
  | { type: "start" }
  | { type: "clue"; word: string; count: number }
  | { type: "guess"; cardId: string }
  | { type: "end-turn" }
  | { type: "pause" }
  | { type: "step" }
  | { type: "replace"; slotId: SlotId }
  | { type: "rematch" };

export interface ActionRequest {
  actionId: string;
  version: number;
  action: GameAction;
}

export const SLOT_IDS: SlotId[] = [
  "red-spymaster", "blue-spymaster", "red-guesser", "blue-guesser",
];

export const otherTeam = (team: Team): Team => team === "red" ? "blue" : "red";
