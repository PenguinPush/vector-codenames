import type { RoomView } from "@/lib/game/types";

export function DecisionAnalysis({ room }: { room: RoomView }) {
  const analysis = room.analysis;
  const ranked = room.board.filter((card) => !card.revealed && card.score !== null).sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  return <section aria-label="Bot decision" className="bg-surface p-5 sm:p-6">
    <div className="flex items-center justify-between gap-3"><h2 className="text-sm font-semibold">The decision</h2><span className="eyebrow text-muted">Demo scores</span></div>
    {!room.clue ? <p className="mt-4 text-sm leading-relaxed text-muted">{room.phase === "finished" ? "The board is complete. Download the replay to inspect every turn." : "Scores and the decision summary appear with the next clue."}</p> : <>
      <p className="mt-4 text-sm leading-relaxed text-muted">{analysis?.summary ?? "The guesser ranks unrevealed words by their demo scores and stops at the clue count. Intended targets stay private until the game ends."}</p>
      {analysis?.targets.length ? <div className="mt-5"><span className="eyebrow text-muted">Targets</span><p className="mt-2 text-sm font-medium">{analysis.targets.join(" · ")}</p></div> : null}
      {analysis?.weakestTarget && <dl className="mt-5 space-y-3 text-xs">
        <div className="flex justify-between gap-3"><dt className="text-muted">Weakest · {analysis.weakestTarget.word}</dt><dd className="font-mono">{analysis.weakestTarget.score.toFixed(3)}</dd></div>
        {analysis.closestDanger && <div className="flex justify-between gap-3"><dt className="text-muted">Danger · {analysis.closestDanger.word}</dt><dd className="font-mono">{analysis.closestDanger.score.toFixed(3)}</dd></div>}
        {analysis.gap !== null && <div className="flex justify-between bg-paper px-3 py-3"><dt>Separation</dt><dd className="font-mono">{analysis.gap >= 0 ? "+" : ""}{analysis.gap.toFixed(3)}</dd></div>}
      </dl>}
      {ranked.length > 0 && <details className="mt-5"><summary className="cursor-pointer py-2 text-xs font-semibold">Word rankings</summary><ol className="mt-2 space-y-2">{ranked.map((card, index) => <li className="flex justify-between text-xs" key={card.id}><span><span className="mr-3 font-mono text-muted">{String(index + 1).padStart(2, "0")}</span>{card.word}</span><span className="font-mono text-muted">{card.score?.toFixed(3)}</span></li>)}</ol></details>}
      {analysis && analysis.alternatives.length > 0 && <details className="mt-2"><summary className="cursor-pointer py-2 text-xs font-semibold">Other clues</summary><ul className="mt-2 space-y-2">{analysis.alternatives.map((item) => <li className="flex justify-between text-xs" key={item.word}><span className="uppercase">{item.word}</span><span className="font-mono text-muted">{item.count} words</span></li>)}</ul></details>}
    </>}
    <p className="mt-5 text-[11px] leading-relaxed text-muted">Illustrative values, not Gemma cosine similarities.</p>
  </section>;
}
