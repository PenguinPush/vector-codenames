import { NextRequest } from "next/server";
import { act, roomView } from "@/lib/server/store";
import { errorResponse, json, readAction, session } from "@/lib/server/http";

export const runtime = "nodejs";
type Context = { params: Promise<{ code: string }> };

export async function GET(request: NextRequest, context: Context) {
  try {
    const { code } = await context.params;
    const id = session(request);
    return json(await roomView(code, id), request, id);
  } catch (error) { return errorResponse(error); }
}

export async function POST(request: NextRequest, context: Context) {
  try {
    const { code } = await context.params;
    const id = session(request);
    return json(await act(code, id, await readAction(request)), request, id);
  } catch (error) { return errorResponse(error); }
}
