"use client";

import type { CardKind, RoomView } from "@/lib/game/types";

const hiddenColors: Record<CardKind, string> = { red: "bg-red-soft text-red", blue: "bg-blue-soft text-blue", neutral: "bg-[#e9e6da] text-[#706c5c]", assassin: "bg-ink text-paper" };
const revealedColors: Record<CardKind, string> = { red: "bg-red text-paper", blue: "bg-blue text-paper", neutral: "bg-[#d5d1c3] text-[#5c594f]", assassin: "bg-ink text-paper" };

export function Board({ room, selected, canGuess, onSelect }: { room: RoomView; selected: string | null; canGuess: boolean; onSelect: (id: string) => void }) {
  return <div className="grid grid-cols-5 gap-1.5 sm:gap-2" role="group" aria-label="Codenames board">
    {room.board.map((card) => <button
      key={card.id}
      className={`word-tile ${card.kind ? (card.revealed ? revealedColors : hiddenColors)[card.kind] : "bg-surface text-ink"}`}
      disabled={!canGuess || card.revealed}
      data-testid={`card-${card.id}`}
      data-selected={selected === card.id}
      aria-pressed={selected === card.id}
      aria-label={`${card.word}${card.kind ? `, ${card.kind}` : ""}${card.revealed ? ", revealed" : ""}${card.score !== null ? `, demo score ${card.score.toFixed(3)}` : ""}`}
      onClick={() => onSelect(card.id)}>
      <span className={`tile-word ${card.revealed ? "opacity-70" : ""}`}>{card.word}</span>
      <span className="font-mono text-[9px] leading-none opacity-65 sm:text-[11px]">{card.revealed ? card.kind === "neutral" ? "FOUND / —" : `FOUND / ${card.kind === "assassin" ? "×" : card.kind?.toUpperCase()}` : card.score !== null ? card.score.toFixed(3) : room.canSeeKey && card.kind ? card.kind === "neutral" ? "—" : card.kind.toUpperCase() : "·"}</span>
    </button>)}
  </div>;
}
