"use client";

import type { GameAction, RoomView } from "@/lib/game/types";

export function Seats({ room, name, busy, send, compact = false }: {
  room: RoomView; name: string; busy: boolean; send: (action: GameAction) => Promise<boolean>; compact?: boolean;
}) {
  return <div className="grid grid-cols-2 gap-2 sm:gap-3" aria-label="Four role slots">
    {room.seats.map((seat) => {
      const available = !seat.occupied || seat.isYou;
      const lobby = room.phase === "lobby";
      const canClaim = available && (lobby || (!room.yourSeat && seat.controller === "bot"));
      return <section key={seat.id} data-testid={seat.id} className={`${seat.team === "red" ? "bg-red-soft" : "bg-blue-soft"} ${compact ? "p-3" : "p-5 sm:p-7"}`}>
        <div className={`eyebrow flex items-center justify-between gap-1 ${seat.team === "red" ? "text-red" : "text-blue"}`}>
          <span>{seat.team}</span><span>{seat.isYou ? "You" : seat.occupied ? "Joined" : "Open"}</span>
        </div>
        <h3 className={`${compact ? "mt-3 text-base" : "mt-5 text-xl sm:text-2xl"} font-medium tracking-tight capitalize`}>{seat.role}</h3>
        <p className="mt-1 min-h-5 truncate text-xs text-muted">{seat.controller === "human" ? (seat.name ?? "Player") : seat.occupied ? `${seat.name} watching` : "Bot"}{seat.isYou && seat.controller === "human" && lobby ? seat.ready ? " · ready" : " · not ready" : ""}</p>
        {canClaim && <div className={`mt-5 grid gap-1 ${lobby ? "grid-cols-2" : "grid-cols-1"}`}>
          {lobby && <button aria-label={`Play ${seat.team} ${seat.role}`} aria-pressed={seat.isYou && seat.controller === "human"} disabled={busy} onClick={() => void send({ type: "claim", slotId: seat.id, controller: "human", name })} className={`min-h-11 px-2 text-xs font-semibold ${seat.isYou && seat.controller === "human" ? "bg-ink text-paper" : "bg-paper/75"}`}>Play</button>}
          <button aria-label={`Watch ${seat.team} ${seat.role}`} aria-pressed={seat.isYou && seat.controller === "bot"} disabled={busy || (!lobby && seat.isYou)} onClick={() => void send({ type: "claim", slotId: seat.id, controller: "bot", name })} className={`min-h-11 px-2 text-xs font-semibold ${seat.isYou && seat.controller === "bot" ? "bg-ink text-paper" : "bg-paper/75"}`}>Watch</button>
        </div>}
        {!lobby && room.isHost && seat.controller === "human" && <button disabled={busy} onClick={() => void send({ type: "replace", slotId: seat.id })} className="mt-3 min-h-11 text-xs text-muted" aria-label={`Replace ${seat.team} ${seat.role} with bot`}>Let bot take over</button>}
      </section>;
    })}
  </div>;
}
