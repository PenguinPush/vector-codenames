import { NextRequest } from "next/server";
import { roomView } from "@/lib/server/store";
import { errorResponse, SESSION_COOKIE } from "@/lib/server/http";
import { GameError } from "@/lib/game/engine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ code: string }> }) {
  try {
    const { code } = await context.params;
    const id = request.cookies.get(SESSION_COOKIE)?.value;
    if (!id) throw new GameError("Open the room before connecting.", 401);
    await roomView(code, id);
    const encoder = new TextEncoder();
    let stop: () => void = () => undefined;
    const stream = new ReadableStream({
      start(controller) {
        let closed = false;
        let busy = false;
        let lastVersion = -1;
        const send = async () => {
          if (closed || busy) return;
          busy = true;
          try {
            const view = await roomView(code, id, true);
            if (closed) return;
            if (view.version !== lastVersion) {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(view)}\n\n`));
              lastVersion = view.version;
            } else controller.enqueue(encoder.encode(": keepalive\n\n"));
          } catch { stop(); }
          finally { busy = false; }
        };
        const timer = setInterval(() => void send(), 1000);
        stop = () => {
          if (closed) return;
          closed = true;
          clearInterval(timer);
          request.signal.removeEventListener("abort", stop);
          // A cancelled stream may already be closed by the runtime.
          try { controller.close(); } catch { /* no work remains */ }
        };
        request.signal.addEventListener("abort", stop);
        if (request.signal.aborted) stop(); else void send();
      },
      cancel() { stop(); },
    });
    return new Response(stream, { headers: {
      "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive", "X-Accel-Buffering": "no",
    } });
  } catch (error) { return errorResponse(error); }
}
