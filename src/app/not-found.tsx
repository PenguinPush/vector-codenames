import Link from "next/link";
export default function NotFound() {
  return <main className="mx-auto max-w-md px-6 py-24"><h1 className="text-3xl tracking-tight">That room is missing.</h1><p className="mt-3 text-muted">Check the invite link or start a new board.</p><Link className="action action-primary mt-8" href="/">Back to rooms</Link></main>;
}
