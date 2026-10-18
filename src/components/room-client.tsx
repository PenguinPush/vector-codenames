"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import type { GameAction, RoomView } from "@/lib/game/types";
import { Brand, DemoNote } from "./brand";
import { Seats } from "./seats";
import { Board } from "./board";
import { DecisionAnalysis } from "./analysis";

export function RoomClient({ code }: { code: string }) {
  const [room, setRoom] = useState<RoomView | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [connection, setConnection] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const [selected, setSelected] = useState<string | null>(null);
  const [clueWord, setClueWord] = useState("");
  const [clueCount, setClueCount] = useState(1);
  const [copied, setCopied] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const requestPending = useRef(false);
  const accept = useCallback((view: RoomView) => {
    setRoom((current) => !current || current.code !== view.code || current.version <= view.version ? view : current);
  }, []);

  useEffect(() => {
    let closed = false;
    let source: EventSource | null = null;
    const controller = new AbortController();
    setName(localStorage.getItem("codenames-name") ?? "");
    async function connect() {
      try {
        const response = await fetch(`/api/rooms/${code}`, { signal: controller.signal, cache: "no-store" });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error);
        if (closed) return;
        accept(body);
        localStorage.setItem("codenames-room", code);
        source = new EventSource(`/api/rooms/${code}/events`);
        source.onopen = () => setConnection("live");
        source.onmessage = (message) => {
          try { accept(JSON.parse(message.data)); } catch { setError("An update could not be read. Refresh to reconnect."); }
        };
        source.onerror = () => setConnection("reconnecting");
      } catch (error) { if (!closed) setError((error as Error).message || "Could not open the room."); }
    }
    void connect();
    return () => { closed = true; controller.abort(); source?.close(); };
  }, [code, accept]);

  useEffect(() => { setSelected(null); }, [room?.turnNumber, room?.phase, room?.gameNumber]);
  useEffect(() => {
    if (selected && room?.board.find((card) => card.id === selected)?.revealed) setSelected(null);
  }, [room, selected]);

  async function send(action: GameAction): Promise<boolean> {
    if (!room || requestPending.current) return false;
    requestPending.current = true;
    setBusy(true); setError("");
    try {
      const actionId = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const response = await fetch(`/api/rooms/${code}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: room.version, actionId, action }),
      });
      const body = await response.json();
      if (!response.ok) {
        if (response.status === 409) {
          const latest = await fetch(`/api/rooms/${code}`, { cache: "no-store" });
          if (latest.ok) accept(await latest.json());
        }
        throw new Error(body.error);
      }
      accept(body);
      if (action.type === "claim") localStorage.setItem("codenames-name", name);
      return true;
    } catch (error) { setError((error as Error).message || "Could not send the action."); return false; }
    finally { requestPending.current = false; setBusy(false); }
  }

  async function copyInvite() {
    try { await navigator.clipboard.writeText(window.location.href); setCopied(true); }
    catch { setShowInvite(true); }
  }

  async function submitClue(event: FormEvent) {
    event.preventDefault();
    if (await send({ type: "clue", word: clueWord, count: clueCount })) setClueWord("");
  }

  const yours = room?.seats.find((seat) => seat.isYou);
  const yourTurn = yours?.controller === "human" && yours.id === room?.activeSlot;
  const canGuess = Boolean(yourTurn && room?.phase === "guess" && !busy && connection === "live");
  const chosenWord = room?.board.find((card) => card.id === selected)?.word;
  const activeSeat = room?.seats.find((seat) => seat.id === room.activeSlot);
  const liveGame = room?.phase === "clue" || room?.phase === "guess";

  return <main className="mx-auto min-h-svh max-w-[1180px] px-4 pb-8 sm:px-8">
    <header className="flex items-center justify-between gap-4 py-4 sm:py-6">
      <Brand />
      <div className="flex items-center gap-3 sm:gap-5">
        <span className="hidden text-xs text-muted sm:inline">Room <span className="font-mono">{code}</span></span>
        <button onClick={copyInvite} className="action action-secondary px-3 text-xs">{copied ? "Copied" : "Invite"}<span aria-hidden="true">↗</span></button>
      </div>
    </header>
    {showInvite && <input aria-label="Invite link" readOnly className="field mb-4" value={typeof window === "undefined" ? "" : window.location.href} onFocus={(event) => event.target.select()} />}
    {error && <div role="alert" className="mb-4 flex items-start justify-between gap-3 bg-red-soft px-4 py-3 text-sm text-red"><span>{error}</span><button className="shrink-0 px-2" aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
    {!room ? <section className="py-20"><h1 className="text-3xl tracking-tight">{error ? "Couldn’t open this room." : "Opening the room…"}</h1><Link className="action action-secondary mt-6" href="/">Back to rooms</Link></section> : <>
      {connection !== "live" && <p role="status" className="mb-4 bg-surface px-4 py-3 text-xs text-muted">{connection === "reconnecting" ? "Reconnecting. Your seat is saved." : "Connecting to the room…"}</p>}
      {room.phase === "lobby" ? <div className="mx-auto max-w-3xl py-5 sm:py-12">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
          <div><p className="eyebrow mb-4 text-muted">Room {room.code} / Board {String(room.gameNumber).padStart(2, "0")}</p><h1 className="text-4xl font-medium tracking-[-0.05em] sm:text-5xl">Take your seat.</h1><p className="mt-3 text-sm text-muted">Play a role. Or watch a bot make the connections.</p></div>
          <div className="w-full sm:w-48"><label htmlFor="player-name" className="eyebrow mb-2 block text-muted">Your name</label><input id="player-name" className="field" autoComplete="nickname" maxLength={24} value={name} placeholder="Guest" onChange={(event) => setName(event.target.value)} /></div>
        </div>
        <Seats room={room} name={name} busy={busy} send={send} />
        <div className="mt-6 flex flex-wrap items-center gap-3">
          {yours?.controller === "human" && <button disabled={busy} onClick={() => void send({ type: "ready" })} className={`action ${yours.ready ? "action-secondary" : "action-primary"}`}>{yours.ready ? "Not ready" : "Ready"}</button>}
          {room.isHost && <button disabled={busy || !room.canStart} onClick={() => void send({ type: "start" })} className="action action-primary">Start game <span aria-hidden="true">↗</span></button>}
          {yours && <button disabled={busy} onClick={() => void send({ type: "leave" })} className="action text-muted">Leave seat</button>}
          <span className="ml-auto text-xs text-muted">{room.seats.filter((seat) => seat.occupied).length}/4 seats joined</span>
        </div>
        <p className="mt-4 text-xs leading-relaxed text-muted">{!room.canStart ? "Waiting for players to be ready." : !room.isHost ? "The host will start the game." : "Empty seats play as bots. Roles lock when the game starts."}</p>
        <div className="mt-10"><DemoNote /></div>
      </div> : <>
        <div className="mt-3 mb-7 flex flex-wrap items-end justify-between gap-4 sm:mt-6">
          <div>
            <p className="eyebrow mb-3 text-muted">Board {String(room.gameNumber).padStart(2, "0")} / Turn {String(room.turnNumber).padStart(2, "0")}{room.paused ? " / Paused" : ""}</p>
            <h1 className="text-3xl font-medium tracking-[-0.04em] sm:text-4xl">{room.phase === "finished" ? `${room.winner === "red" ? "Red" : "Blue"} takes the board.` : yourTurn ? room.phase === "clue" ? "Make the connection." : "Find your words." : room.phase === "clue" ? "A clue is coming." : "Follow the connection."}</h1>
          </div>
          <div className="flex gap-2" aria-label="Remaining agents">
            <div className="flex min-w-20 items-baseline justify-between gap-3 bg-red-soft px-3 py-2 text-red"><span className="eyebrow">Red</span><span className="font-mono text-2xl">{room.remaining.red}</span></div>
            <div className="flex min-w-20 items-baseline justify-between gap-3 bg-blue-soft px-3 py-2 text-blue"><span className="eyebrow">Blue</span><span className="font-mono text-2xl">{room.remaining.blue}</span></div>
          </div>
        </div>
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-8">
          <div className="min-w-0">
            <div className="mb-3 flex min-h-16 items-center justify-between gap-3 bg-surface px-4 py-3 sm:px-5">
              <div>{room.clue ? <><span className="eyebrow text-muted">{room.clue.team} clue</span><p className="mt-1 text-2xl font-medium tracking-tight sm:text-3xl">{room.clue.word}<span className="mx-2 text-muted">·</span>{room.clue.count}</p></> : <><span className="eyebrow text-muted">{room.turn} spymaster</span><p className="mt-1 text-sm">{room.phase === "finished" ? "Board complete" : activeSeat?.controller === "bot" ? "Considering the board…" : "Choosing a clue…"}</p></>}</div>
              <span className="text-right text-xs leading-relaxed text-muted">{yours ? <>{yours.team}<br />{yours.role}{yours.controller === "bot" ? " / watching" : ""}</> : "Watching"}</span>
            </div>
            <Board room={room} selected={selected} canGuess={canGuess} onSelect={(id) => setSelected(selected === id ? null : id)} />
            <div className="mt-3 flex justify-between gap-3 text-[10px] text-muted sm:text-xs"><span>{room.canSeeKey ? "Full key visible" : "Key hidden"}</span><span>{room.clue ? "Illustrative similarity scores" : "25 words · one assassin"}</span></div>
            {yourTurn && room.phase === "clue" && <form onSubmit={submitClue} className="mt-6 grid grid-cols-[minmax(0,1fr)_64px_auto] gap-2">
              <input className="field" aria-label="Clue word" placeholder="One word" value={clueWord} onChange={(event) => setClueWord(event.target.value)} autoComplete="off" spellCheck={false} maxLength={24} required disabled={busy} />
              <input className="field px-2 text-center" aria-label="Clue count" type="number" min={1} max={room.remaining[room.turn]} value={clueCount} onChange={(event) => setClueCount(Number(event.target.value))} required disabled={busy} />
              <button className="action action-primary" disabled={busy || connection !== "live"}>Send</button>
            </form>}
            {yourTurn && room.phase === "guess" && <div className="mt-5 flex flex-wrap items-center gap-2">
              <button className="action action-primary min-w-36 flex-1" disabled={!selected || busy || connection !== "live"} onClick={async () => { if (selected && await send({ type: "guess", cardId: selected })) setSelected(null); }}>{chosenWord ? `Guess ${chosenWord}` : "Select a word"}</button>
              <button className="action action-secondary" disabled={busy || room.guesses === 0} onClick={() => void send({ type: "end-turn" })}>End turn</button>
              <span className="w-full pt-1 text-xs text-muted">Up to {room.guessesLeft} {room.guessesLeft === 1 ? "guess" : "guesses"} left, including the optional extra.</span>
            </div>}
            {liveGame && !yourTurn && <p role="status" className="mt-5 text-sm text-muted">{room.paused ? "Paused. Advance one decision at a time." : `${activeSeat?.controller === "bot" ? "Bot" : activeSeat?.name ?? "Player"} ${room.phase === "clue" ? "is choosing a clue" : "is guessing"} for ${room.turn}.`}</p>}
            {room.allBots && room.isHost && liveGame && <div className="mt-4 flex gap-2"><button disabled={busy} className="action action-secondary" onClick={() => void send({ type: "pause" })}>{room.paused ? "Resume" : "Pause"}</button><button disabled={busy || !room.paused} className="action action-primary" onClick={() => void send({ type: "step" })}>Next <span aria-hidden="true">→</span></button></div>}
            {room.phase === "finished" && <div className="mt-5 bg-surface p-5"><p className="text-sm text-muted">{room.winReason}</p><div className="mt-4 flex flex-wrap gap-2">{room.isHost && <button className="action action-primary" disabled={busy} onClick={() => void send({ type: "rematch" })}>Another board <span aria-hidden="true">↗</span></button>}<a className="action action-secondary" href={`/api/rooms/${code}/replay`}>Download replay</a></div></div>}
            <section className="mt-8" aria-label="Turn history"><h2 className="eyebrow mb-4 text-muted">At the table</h2>{room.events.length === 0 ? <p className="text-xs text-muted">The first turn starts here.</p> : <ol className="space-y-3">{room.events.slice(-12).reverse().map((item) => <li key={item.id} className="flex gap-3 text-xs leading-relaxed"><span className={`shrink-0 font-mono ${item.team === "red" ? "text-red" : "text-blue"}`}>{String(item.turn).padStart(2, "0")}</span><span className={item.kind === "clue" ? "font-semibold" : "text-muted"}>{item.text}</span></li>)}</ol>}</section>
          </div>
          <aside className="space-y-6"><DecisionAnalysis room={room} /><div><h2 className="eyebrow mb-3 text-muted">The seats</h2><Seats room={room} name={name} busy={busy} send={send} compact /></div><DemoNote /></aside>
        </div>
      </>}
    </>}
  </main>;
}
