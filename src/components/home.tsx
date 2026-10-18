"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Brand, DemoNote } from "./brand";

export function Home() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState("");
  useEffect(() => { setRecent(localStorage.getItem("codenames-room") ?? ""); }, []);

  async function create() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/rooms", { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error);
      router.push(`/room/${body.code}`);
    } catch (error) { setError((error as Error).message || "Could not create a room."); setBusy(false); }
  }

  function join(event: FormEvent) {
    event.preventDefault();
    const value = code.trim().toUpperCase();
    if (!/^[A-F0-9]{6}$/.test(value)) { setError("Enter the six-character room code."); return; }
    router.push(`/room/${value}`);
  }

  return <main className="mx-auto flex min-h-svh max-w-5xl flex-col px-5 sm:px-10">
    <header className="flex items-center justify-between py-5 sm:py-7"><Brand /><DemoNote /></header>
    <div className="flex flex-1 flex-col justify-center py-12 sm:py-20">
      <div className="mb-10 sm:mb-14">
        <p className="eyebrow mb-5 text-muted">Two teams. Four seats.</p>
        <h1 className="max-w-xl text-[clamp(48px,9vw,86px)] leading-[0.96] font-medium tracking-[-0.065em]">A little word.<br /><span className="text-muted">A big connection.</span></h1>
        <p className="mt-6 text-sm text-muted">Find your words. Play a role, or let a bot take the seat.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <section className="flex flex-col bg-ink p-6 text-paper sm:p-8">
          <span className="eyebrow text-white/50">01 / Host</span>
          <h2 className="mt-6 text-2xl tracking-tight">Make room.</h2>
          <p className="mt-2 mb-8 text-sm text-white/60">Invite your team. Bots fill the empty seats.</p>
          <button onClick={create} disabled={busy} className="action mt-auto w-full bg-paper text-ink">{busy ? "Creating…" : "Create room"}<span aria-hidden="true" className="ml-auto">↗</span></button>
        </section>
        <section className="flex flex-col bg-surface p-6 sm:p-8">
          <span className="eyebrow text-muted">02 / Join</span>
          <h2 className="mt-6 text-2xl tracking-tight">Take a seat.</h2>
          <p className="mt-2 mb-8 text-sm text-muted">Have an invite? Enter your room code.</p>
          <form onSubmit={join} className="mt-auto flex gap-2">
            <input aria-label="Room code" autoCapitalize="characters" autoComplete="off" spellCheck={false} maxLength={6} value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} className="field bg-paper font-mono uppercase tracking-[.15em]" placeholder="ABC123" required />
            <button className="action action-primary shrink-0" disabled={busy}>Join <span aria-hidden="true">↗</span></button>
          </form>
        </section>
      </div>
      {error && <p role="alert" className="mt-4 text-sm text-red">{error}</p>}
      {recent && <Link href={`/room/${recent}`} className="mt-5 inline-flex min-h-11 items-center self-start text-sm text-muted">Return to {recent} <span aria-hidden="true" className="ml-2">↗</span></Link>}
    </div>
    <footer className="flex justify-between gap-4 py-6 text-xs text-muted"><span>25 words. One shared board.</span><span>Human intuition × machine association</span></footer>
  </main>;
}
