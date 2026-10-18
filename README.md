# Codenames

A mobile web game built with Next.js App Router, React, TypeScript, and Tailwind CSS. Four seats share one authoritative room: red and blue spymasters and guessers. Each seat can be played by a person or controlled by a bot while its owner watches.

**This milestone implements the web game. Gemma is not connected.** Bot clues and displayed similarities come from deterministic demo fixtures, not embeddings. The interface labels these values explicitly.

## Run locally

Requires Node.js 22 or newer.

```sh
npm ci
npm run dev
```

Open http://localhost:3000. Create a room and share its URL or six-character code. Phones on the same network can use `http://<your-computer-LAN-IP>:3000`; the development server binds to all interfaces. Remote internet play requires deploying the persistent server, which this milestone does not do.

For LAN development, add your computer's IP to `.env.local` as `CODENAMES_DEV_ORIGINS=192.168.1.100` (using your actual address) and restart the dev server. This permits Next.js development assets on that hostname. Local production mode does not require this development setting.

Each browser profile has one anonymous session, saved in an HTTP-only cookie. Use different devices, browser profiles, or private windows to test independent players. Tabs in the same browser profile share their identity.

1. Enter a name and choose **Play** or **Watch** for a seat.
2. Human players press **Ready**. Bots are always ready.
3. The room creator presses **Start game**. Unclaimed seats run as bots.
4. Spymasters enter a clue and count. Guessers select a word and confirm **Guess**, or end the turn after at least one guess.
5. In an all-bot match, the host can pause and advance one decision with **Next**.
6. After the game, download the complete replay or start another board.

## What was built, step by step

### 1. Framework and visual foundation

`src/app/layout.tsx`, `src/app/globals.css`, and `src/components/brand.tsx` establish the app shell. Tailwind v4 is integrated through PostCSS. The palette uses warm off-white, charcoal, muted red, and muted blue. Tiles and controls have square corners, no decorative outlines, no animation, and no external fonts or image assets. Keyboard focus uses a background change.

### 2. Rules and role boundaries

`src/lib/game/types.ts` defines internal state separately from the browser's `RoomView`. `src/lib/game/engine.ts` implements:

- 25 unique words: nine red, eight blue, seven bystanders, and one assassin. Red starts.
- Exclusive seat claims, ready state, host actions, and roles locked during a game.
- Single-word numbered clues, one required guess, the optional extra guess, and end-turn behavior.
- Immediate assassin loss and victory when all of a team's agents are revealed.
- A full hidden key for spymasters, and public information only for guessers.
- No key shown in the lobby, preventing players from shopping for a role after seeing the board.
- Postgame key reveal and a fresh board for rematches.

Clue validation blocks exact board words, simple plural variants, and obvious word parts. It is not a complete linguistic judge. The current UI uses positive numbered clues; optional zero/unlimited clue variants are not included.

### 3. Shared rooms and live updates

`src/lib/server/store.ts` serializes mutations and persists rooms through atomic JSON file replacement in `.data/rooms.json`. The data directory is ignored by Git. `CODENAMES_DATA_DIR` can override it.

Completed games are also archived in `.data/replays/` before their room starts another board, preserving the records for later evaluation.

Next.js route handlers accept commands and send role-filtered snapshots. Server-sent events deliver live updates and reconnect automatically. POST requests handle player actions. This serves the present one-way update stream without a separate WebSocket service.

The server checks roles and turns, not just disabled buttons. Commands have unique IDs to prevent double application and state versions to reject stale decisions. Hidden colors, target lists, and session identifiers are never included in guesser snapshots.

### 4. The mobile interface

`src/components/home.tsx` creates or joins rooms. `room-client.tsx` coordinates the live connection and actions. `seats.tsx` renders the four slots. `board.tsx` renders the five-column square board and scores. `analysis.tsx` renders the decision explanation, separation values, rankings, and alternatives.

On mobile, the board, controls, analysis, and seats stack vertically. On desktop, analysis and seats sit beside the board. Guessing requires selection followed by confirmation. Refreshing preserves your seat. A disconnected human's turn waits; the host can use **Let bot take over**. Spectating a spymaster reveals the key, so switching to a guesser is disallowed until the next board.

### 5. Demo bot and Gemma boundary

`src/lib/bot/provider.ts` defines the three operations the web game needs:

| Operation | Input | Output |
| --- | --- | --- |
| `proposeClue` | Board with key, team | Clue, count, scores, private diagnostic summary |
| `scoreClue` | Clue and public words | Word-to-score mapping |
| `chooseGuess` | Public words, clue scores, guess count | Word ID or stop, with an explanation |

`src/lib/bot/demo.ts` supplies synthetic scores based on a small category vocabulary and deterministic numeric variation. This is only enough to exercise the UI and complete games. Its output must not be used to judge Gemma's quality or calibrate safety margins.

The real model, candidate vocabulary, cosine optimization, threshold calibration, and fine-tuning remain unimplemented. The next integration is documented in [docs/GEMMA-INTEGRATION.md](docs/GEMMA-INTEGRATION.md).

### 6. Verification

```sh
npm run typecheck
npm test
npm run build
npx playwright install chromium --only-shell
npm run test:e2e
```

Unit tests cover all human/bot combinations, slot conflicts, private projections, role locking, guesser input isolation, rule outcomes, idempotency, and rematches. Browser tests exercise independent mobile sessions, shared board updates, reconnecting, narrow layouts, and bot stepping. Browser screenshots are saved to the ignored `test-results/` directory.

The production script uses Next.js's supported Webpack build path because Turbopack's CSS worker requires local port permissions unavailable in this sandbox. Browser tests can optionally use an existing Chromium via `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/absolute/path/to/chromium`.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/rooms` | Create a room and session |
| `GET /api/rooms/:code` | Fetch your role-filtered snapshot and establish a session |
| `POST /api/rooms/:code` | Apply a validated action |
| `GET /api/rooms/:code/events` | Stream role-filtered updates |
| `GET /api/rooms/:code/replay` | Download full postgame diagnostics; blocked during play |

## Deployment boundary

This implementation targets **one persistent Node.js process**, not horizontally scaled or ephemeral serverless instances. Memory and a serialized JSON store coordinate rooms. Bot turns advance while at least one room event stream is open; if everyone leaves, the game waits until someone reconnects. There is no model inference on a phone.

For a local production run:

```sh
npm run build
npm start
```

Before wider hosting, replace the file store with a transactional database, add room expiry and request limits, and define session recovery and host transfer. A multi-process deployment also needs a shared event channel and a single scheduler per room. Saved rooms include private game keys and must remain server-side. This prototype has no accounts, matchmaking, or live fine-tuning.
