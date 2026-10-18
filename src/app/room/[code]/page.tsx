import { notFound } from "next/navigation";
import { RoomClient } from "@/components/room-client";

export default async function Page({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  if (!/^[a-f0-9]{6}$/i.test(code)) notFound();
  return <RoomClient code={code.toUpperCase()} />;
}
