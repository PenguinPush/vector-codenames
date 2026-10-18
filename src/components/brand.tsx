import Link from "next/link";

export function Brand() {
  return <Link href="/" className="inline-flex min-h-11 items-center gap-3" aria-label="Codenames home">
    <span aria-hidden="true" className="grid grid-cols-2 gap-0.5">
      <span className="size-2.5 bg-red" /><span className="size-2.5 bg-ink" />
      <span className="size-2.5 bg-ink" /><span className="size-2.5 bg-blue" />
    </span>
    <span className="text-sm font-semibold tracking-[-0.03em]">codenames</span>
  </Link>;
}

export function DemoNote() {
  return <span className="eyebrow text-muted">Demo bots · Gemma next</span>;
}
