import type { BotProvider, ClueProposal } from "./provider";
import type { Card } from "../game/types";
import { WORD_GROUPS } from "../game/words";

function hash(value: string): number {
  let result = 0;
  for (const char of value) result = (result * 31 + char.charCodeAt(0)) >>> 0;
  return result;
}

/** Synthetic fixtures for exercising the UI. No embeddings or cosine are computed. */
export const demoBot: BotProvider = {
  source: "demo",
  scoreClue(word, board) {
    const term = word.toLowerCase();
    const related = WORD_GROUPS[term] ?? Object.values(WORD_GROUPS).find(
      (group) => group.includes(word.toUpperCase()),
    ) ?? [];
    return Object.fromEntries(board.map((card) => [
      card.id,
      Number(((related.includes(card.word) ? 0.73 : 0.28) +
        (hash(`${term}:${card.word}`) % 170) / 1000).toFixed(3)),
    ]));
  },
  proposeClue(board, team) {
    const unrevealed = board.filter((card) => !card.revealed);
    const candidates = Object.keys(WORD_GROUPS).map((word) => {
      const scores = this.scoreClue(word, board);
      const ranked = [...unrevealed].sort((a, b) => scores[b.id] - scores[a.id]);
      const firstDanger = ranked.findIndex((card) => card.kind !== team);
      const targets = ranked.slice(0, firstDanger < 0 ? ranked.length : firstDanger);
      const danger = ranked.find((card) => card.kind !== team);
      const weakest = targets.at(-1);
      return { word, scores, targets, danger, weakest,
        gap: weakest && danger ? scores[weakest.id] - scores[danger.id] : -1 };
    }).sort((a, b) => b.targets.length - a.targets.length || b.gap - a.gap);
    const best = candidates[0];
    const targets = best.targets.length ? best.targets : unrevealed.filter((card) => card.kind === team).slice(0, 1);
    const weakest = targets.at(-1) as Card;
    return {
      word: best.word,
      count: Math.max(1, targets.length),
      scores: best.scores,
      analysis: {
        source: "demo",
        summary: best.targets.length
          ? `The demo ranking places ${targets.length} friendly ${targets.length === 1 ? "word" : "words"} before its first unsafe word. Gemma scoring will replace these fixture values.`
          : "No clean group in the demo ranking. Trying one word; this fixture clue may fail.",
        targets: targets.map((card) => card.word),
        weakestTarget: { word: weakest.word, score: best.scores[weakest.id] },
        closestDanger: best.danger ? { word: best.danger.word, score: best.scores[best.danger.id] } : null,
        gap: best.danger ? Number((best.scores[weakest.id] - best.scores[best.danger.id]).toFixed(3)) : null,
        alternatives: candidates.slice(1, 4).map((c) => ({ word: c.word, count: c.targets.length })),
      },
    } satisfies ClueProposal;
  },
  chooseGuess({ cards, clue, guesses }) {
    if (guesses >= clue.count) return { cardId: null, reason: "Reached the clue count. Ending the turn." };
    const ranked = cards.filter((card) => !card.revealed)
      .sort((a, b) => (clue.scores[b.id] ?? -1) - (clue.scores[a.id] ?? -1));
    const best = ranked[0];
    return { cardId: best?.id ?? null, reason: best
      ? `${best.word} has the highest remaining demo score (${clue.scores[best.id].toFixed(3)}).`
      : "No words remain." };
  },
};
