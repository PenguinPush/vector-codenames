import { NextRequest, NextResponse } from "next/server";
import { replay } from "@/lib/server/store";
import { errorResponse } from "@/lib/server/http";

export const runtime = "nodejs";
export async function GET(_request: NextRequest, context: { params: Promise<{ code: string }> }) {
  try {
    const { code } = await context.params;
    return new NextResponse(JSON.stringify(await replay(code), null, 2), { headers: {
      "Content-Type": "application/json", "Content-Disposition": `attachment; filename="codenames-${code.replace(/[^a-z0-9]/gi, "")}.json"`, "Cache-Control": "no-store",
    } });
  } catch (error) { return errorResponse(error); }
}
