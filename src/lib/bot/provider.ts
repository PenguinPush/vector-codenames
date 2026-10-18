import type { Analysis, Card, Clue, Team } from "../game/types";

export interface ClueProposal {
  word: string;
  count: number;
  scores: Record<string, number>;
  analysis: Analysis;
}

export interface PublicBotBoard {
  // A guesser must never receive hidden card kinds or intended targets.
  cards: Pick<Card, "id" | "word" | "revealed">[];
  clue: Pick<Clue, "word" | "count" | "scores">;
  guesses: number;
}

export interface BotProvider {
  readonly source: "demo" | "gemma";
  proposeClue(board: Card[], team: Team): ClueProposal;
  scoreClue(word: string, board: Pick<Card, "id" | "word">[]): Record<string, number>;
  chooseGuess(input: PublicBotBoard): { cardId: string | null; reason: string };
}

// Future integration: an async service adapter will call the Python Gemma worker.
// Keep embeddings, model loading, optimizer calibration, and training out of this app.
