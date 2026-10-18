import { NextRequest } from "next/server";
import { newRoom } from "@/lib/server/store";
import { checkOrigin, errorResponse, json, session } from "@/lib/server/http";

export const runtime = "nodejs";
export async function POST(request: NextRequest) {
  try {
    checkOrigin(request);
    const id = session(request);
    return json(await newRoom(id), request, id);
  } catch (error) { return errorResponse(error); }
}
