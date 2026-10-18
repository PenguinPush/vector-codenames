# Gemma / Codenames

An inspectable embedding experiment with a small multiplayer game around it. One Python server owns the model, vector communication search, rules, rooms, and WebSockets. The frontend is plain HTML, CSS, and JavaScript: no Node build or frontend framework.

## Run

Python 3.13 is recommended. From this directory:

```sh
uv venv --python 3.13
uv pip install -e '.[gemma,dev]'
.venv/bin/codenames
```

Open **http://localhost:8000**. Create a room, copy its invite, and choose a seat or **Analysis spectator**. Empty seats use bots. Human players mark themselves ready; the host starts. All-bot games begin paused: use **Next decision** or **Play automatically**.

The first real clue downloads `google/embeddinggemma-2` and encodes the vocabulary. This is substantially slower than subsequent turns. Model work runs off the networking event loop, through one shared serialized worker. The UI shows its current processing stage. Model errors remain errors; there is no silent synthetic fallback.

For a quick, explicitly synthetic UI test without downloading weights:

```sh
uv pip install -e '.[dev]'
.venv/bin/codenames --demo
```

The page visibly labels this mode. Synthetic vectors verify the application, not Gemma's semantic quality.

Apple Silicon can use `GEMMA_DEVICE=mps .venv/bin/codenames`. CPU is the default. CUDA can be selected with `GEMMA_DEVICE=cuda` on a compatible installation.

## Precompute on a Colab GPU

See [colab/README.md](colab/README.md). Upload the supplied notebook and ZIP, run on a GPU, and download one `gemma_embeddings.npz`. Set `GEMMA_EMBEDDINGS_FILE=.cache/gemma_embeddings.npz` in `.env` to use the file without loading Gemma locally. Words absent from the file are computed on demand with the same pinned Gemma revision and saved in `.cache/live_embeddings/words.sqlite3`. Cached words do not load the model. The first genuinely missing word may download/load model weights; model dependencies and access are required. No synthetic fallback is used. The original NPZ is not rewritten.

## Embedding progress and resumable caching

During encoding, the room/laboratory status shows batch count, words ready, percentage, reused words, newly saved words, elapsed time and an estimated remaining time. The terminal also reports progress, throttled to about once every two seconds. ETA begins after the first completed batch and covers inference rather than model download/loading.

Each batch is committed to `.cache/embeddings/words.sqlite3` before progress is reported. Restarting after interruption reuses completed batches; only an unfinished batch needs repeating. Adding, removing or reordering vocabulary entries reuses existing per-word vectors. Board and clue words share this cache. `GEMMA_BATCH_SIZE` controls batch size (default 32).

Cache entries are separated by model revision, prompt, dimensions and encoding metadata. Changing those settings may require recomputation. The model still loads to resolve its identity before cache lookup. Existing whole-list NPZ caches are imported when the exact original list is requested; the old files remain untouched. Local models without a stable revision deliberately use a fresh cache namespace each process.

## Join remotely

The server binds to **0.0.0.0:8000** by default. On the same network, open `http://YOUR_SERVER_LAN_IP:8000`, then copy the room invite **from that address**, rather than from localhost. A room has four player/bot seats and supports additional spectators. Each browser keeps its seat using an HTTP-only session cookie. Reconnecting restores the current authoritative snapshot.

For Internet access, run the same app on a reachable Python host behind an HTTPS reverse proxy that supports WebSocket upgrades. The frontend derives HTTP/WebSocket addresses from the current page, so no frontend URL edits are needed. Serve it at the domain root. This repository includes a Dockerfile:

```sh
docker build -t gemma-codenames .
docker run --rm -p 8000:8000 -v gemma-cache:/app/.cache gemma-codenames
```

The image installs the Python packages; model weights download on first use and persist in the volume. Set `PORT` when your host requires a different listening port. Use **one server process/worker**: rooms live in memory and disappear on restart. This is a small-group demo, not an account-based public game service. Invite codes are unlisted, not passwords. Anyone with a link can choose full analysis spectating; use trusted participants for competitive play.

No public hosting account or tunnel is provisioned by this repository. The local server becomes remotely joinable only when its host/network is reachable. TLS is supplied by the deployment proxy, not by the Python CLI.

## Bot vector communication

Gemma is the shared embedding space. Each word is encoded separately with the same `STS` prompt and L2-normalized. The bots never embed the concatenated clue as a sentence. Python performs all optimization, encoding, decoding and game decisions.

For friendly vectors F and dangerous vectors U, the spymaster first solves:

```text
maximize gamma
subject to ||q||₂ <= 1
           qᵀ(f - u) >= gamma  for every f in F, u in U
```

CVXPY/Clarabel solves this convex unit-ball problem in the span of the board embeddings. A positive solution supplies an ideal separating direction. The numerical bound is not a formal certificate; a zero optimum supplies no useful normalized direction. Even a positive ideal gap does not guarantee a legal word combination exists.

The encoder searches messages of up to K distinct legal words:

```text
p = sum(alpha_i * normalize(Gemma(word_i)))
q_hat = p / ||p||₂
score(card) = q_hatᵀ normalize(Gemma(card))
all_target_gap = min friendly score - max dangerous score
```

Without coefficients, every alpha is 1. With coefficients enabled, they are nonnegative, sum to 1, and are rounded to the configured decimal precision BEFORE the message is scored. Zero coefficients are removed. Near-zero sums are rejected. There are no negative weights or repetition counts.

All legal single words are evaluated exactly. A bounded beam search then extends combinations using a shortlist drawn from good single words, ideal-vector neighbors, and individual target neighbors. A linear program proposes coefficients by maximizing the **unnormalized** all-target margin. Both equal and optimized coefficients are evaluated after rounding and normalization; the LP is a proposal heuristic, not an exact optimizer of cosine separation.

Candidates maximize safe target coverage, then separation gap, then prefer fewer words, then mean target similarity. Safe targets must exceed every dangerous card by the required gap (default 0.001). The best shorter message is retained while searching deeper. A one-shot means every remaining friendly card passes this test. If no safe target is found, a labeled one-guess fallback can fail.

The wire packet contains only words, coefficients, precision, guess count and model identity. The receiver independently reconstructs the direction and scores the public board. It never receives the ideal vector or hidden colors. Both bots currently run inside one server; this is an explicit data boundary, not a distributed-model deployment.

### Configuration

The homepage and host's lobby offer:

- Maximum distinct words: 1–12 (default 3).
- Optional coefficients and 0–4 decimal precision (default 2).
- Required positive separation gap and stop-at-one-shot toggle.
- Beam width, shortlist size, combination evaluation limit and search time budget.

Settings lock when play starts and persist on rematch. The time/evaluation budgets apply to combination extension, excluding model loading, embedding, ideal solving and the exhaustive single-word baseline. Budget exhaustion returns the best evaluated message. Multiword search is approximate: increasing the word limit or vocabulary does not guarantee a one-shot. A broader search can also require larger budgets. Human spymasters still submit ordinary single-word clues.

### Board size and common clues

Room creation, host lobby settings, and the laboratory accept an integer board side N from 2 to 10 (default 5), producing N×N cards. Blue gets floor(N²/3) agents, red gets one more, there is one assassin, and the remaining cards are neutral. The standard 5×5 board remains 9/8/7/1. Changing the board size redraws the lobby board and resets human readiness. Settings lock at game start and survive rematches.

“Common clue words only” limits bot message components to the intersection of the active clue vocabulary and `clue_words_common.csv`. It defaults off, does not change the board pool, and does not restrict human clues. Common-only inference encodes only that candidate subset, sharing the existing encoder/cache. A custom `GEMMA_VOCABULARY` must overlap the common list; an empty intersection produces a visible inference error.

API: `board_size` is the total card count N² (4, 9, 16, …, 100), validated as a square; `communication.common_words_only` is a boolean. Both room creation and laboratory requests accept these settings, as does the host's `configure` WebSocket action.

The common CSV contains 978 distinct entries. All are now present in the full CSV after adding 101 missing entries. Of these, 977 are legal clue candidates: `good-bye` is excluded by the existing single-word letters-only policy. A regression test checks raw CSV membership, including unsupported entries. The local embedding file has been extended with 94 missing vectors (seven of the 101 additions already had board vectors). All 978 common entries have embeddings, including the currently ineligible `good-bye`. The active file has 40,109 vectors; the previous file is backed up at `.cache/gemma_embeddings.before_common.npz`. Restart an already-running server to load the updated file.

### Bot presets

The shared controls offer Human, Hard, Verbose, Insane and God, mapped to the supplied screenshots in attachment order. Presets never change board size. Selecting one fills the existing settings; the lobby still requires **Apply settings**. Manual edits select Custom.

| Preset | Common only | Words | Gap | Seconds | Combinations | Beam | Shortlist |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Human | No | 1 | 0.005 | 5 | 500 | 8 | 32 |
| Hard | No | 1 | 0.005 | 10 | 1,000 | 16 | 64 |
| Verbose | No | 1 | 0.0001 | 15 | 1,000 | 16 | 64 |
| Insane | Yes | 1 | 0.005 | 10 | 1,000 | 16 | 64 |
| God | No | 2 | 0.0001 | 15 | 4,000 | 32 | 128 |

All five disable coefficients, retain two decimal places, and stop at a one-shot. The first screenshot did not show the common-words checkbox; Human defaults it to off. These are configuration presets, not measured difficulty guarantees. Combination budgets only apply when searching multiple words.

### CSV vocabulary

The board pool is `gemma_codenames/data/board_words.csv`; the independent clue pool is `gemma_codenames/data/clue_words.csv`. Both require a `word` column; additional metadata columns are ignored. Board entries may be phrases; clue components contain 1–30 ASCII letters, including single-letter words. Unsupported clue entries (including hyphenated words, apostrophes, periods, phrases and digits) are skipped with a logged count; malformed CSV still raises an error. Duplicates are normalized and removed.

Override paths with `GEMMA_BOARD_WORDS` and `GEMMA_VOCABULARY`. TXT remains supported for custom paths, but editing the old bundled `words.txt` no longer changes the default pools. Restart after changing a pool. Clue filtering excludes board words, their components and inflections conservatively.

## Vector laboratory

Open **http://localhost:8000/lab** (also linked from the homepage). Choose a seed, target team, Gemma or explicitly synthetic embeddings, and search settings. Run once and inspect three stages:

1. The ideal direction and numerical separation bound.
2. The selected word components, rounded coefficients, search trace, baseline comparison and exact wire packet.
3. The independently decoded vector, full cosine ranking and simulated guesses stopping at the clue count or first mistake.

The graph shows board points, component embeddings, cumulative weighted additions, raw sum, normalized decoded vector and ideal direction. Its board-fitted PCA axes preserve linear addition around the origin, but 2D angles/distances are approximate; every decision uses the full embedding dimension. Full vectors and a downloadable JSON report are available. Reconstruction error measures protocol consistency; distance to ideal measures lossy encoding. These are different quantities.

The lab runs outside multiplayer and displays the full theoretical key. Reports are private to the creating browser session and held in memory. Only one lab experiment runs at a time. Model failures are shown explicitly without synthetic fallback.

For the same pipeline without a browser:

```sh
.venv/bin/python -m gemma_codenames.experiment --seed 42 --max-words 5 --coefficients --json reports/gemma-42.json
.venv/bin/python -m gemma_codenames.experiment --synthetic --seed 42 --max-words 5 --coefficients --json reports/synthetic-42.json
```

CLI commands use exported environment variables; `./run.sh` loads `.env` for the web server. Seeded boards are reproducible for the same board CSV; time-limited search results can vary with machine load. Use generous time budgets and fixed evaluation limits for comparisons.

## Multiplayer inspection and privacy

While a bot searches, opted-in analysis spectators see a live panel with the provisional best clue, sampled candidate, depth, evaluations, coverage, gap and a bounded progress history. Updates arrive about twice per second plus depth boundaries; the panel clears when the turn finishes. Players and public spectators do not receive these provisional search reports.

The game combines the interactive embedding map and cosine rankings in one tab, with search traces in a separate Search tab. The map supports drag/pinch/scroll navigation, zoom/reset controls, word finding, hover details and linked ranking selection. Clue words display without plus separators. Math, cosine-matrix, model-diagnostic and raw-vector panels are omitted from the interface. Public spectators receive public scores and projections; opted-in analysis spectators receive full analysis after start. Seated players (both spymasters and guessers) receive no embedding scores, plots, search reports or model metadata, including in history and after game end. Spymasters still receive the board key. Player progress and guess logs omit embedding diagnostics. Role locking prevents switching from an analysis view to guessing on the same board.

The legacy `gemma-board` CLI and separate `gemma_codenames.api:app` `/clues` endpoint retain the original single-word threshold experiment. Use `/lab` or `gemma_codenames.experiment` for the new communication system.

## Files

| File | Responsibility |
| --- | --- |
| `embeddings.py` | Lazy Gemma loading, consistent prompts, model-specific disk cache |
| `communication.py` | Ideal solve, bounded word encoding, rounded coefficients and wire decoder |
| `optimizer.py` | Clue legality and legacy single-word search |
| `transmission_plot.py` | Linear PCA projection and vector addition visualization |
| `experiment.py` | Standalone seeded communication experiment |
| `service.py`, `bots.py` | Model-to-game bridge; public-only guesser |
| `game.py` | Authoritative rules, seats, versions, role projections |
| `web.py` | Single-process server, shared model worker, WebSockets |
| `static/` | Rendering, user input, accessible score tables and SVG graph |

## Configuration and checks

Environment variables: `GEMMA_MODEL_ID`, `GEMMA_REVISION`, `GEMMA_DEVICE`, `GEMMA_BATCH_SIZE`, `GEMMA_CACHE_DIR`, `GEMMA_VOCABULARY`, `GEMMA_BOARD_WORDS`, `GEMMA_OFFLINE=1`, `CODENAMES_MODE=demo`, `PORT`. For an unusual reverse proxy with a differing backend Host header, explicitly list trusted browser origins in comma-separated `CODENAMES_ORIGINS`; normal same-origin hosting needs none.

```sh
.venv/bin/python -m pytest -q
node --check gemma_codenames/static/app.js  # Optional syntax check; Node is not needed to run.
```

Tests cover the optimizer against exhaustive subset search, privacy, duplicate/stale commands, game outcomes, WebSocket execution and reconnects, model errors, PCA geometry, and continuous bounds. Real-model quality should be evaluated separately on repeatable boards and human games; synthetic tests cannot establish it.

Model setup follows [Google's EmbeddingGemma inference guide](https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers); networking uses [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/).

## Verification in this checkout

78 tests pass, including interrupted-batch recovery, per-word cache reuse, legacy cache import, progress forwarding, weighted/unweighted encoding, quantization, a small exhaustive combination comparison, budget fallback, wire reconstruction, model identity checks, CSV loading, role privacy, configuration locking, owner-private lab reports and multiplayer WebSocket flows. Python unused-name checks and JavaScript syntax checks pass. The new laboratory was run in Safari and its ideal-vector and decoded-result views were inspected: seed 42 with synthetic embeddings and coefficients found a three-word one-shot with nine correct guesses and zero reconstruction error. This demonstrates the mechanics, not Gemma semantic quality or guaranteed one-shots.

Actual Gemma inference could not be verified: an offline load found no complete model weights in the local cache. Previous downloads encountered network errors. Complete the model download before selecting real Gemma in the laboratory. Mobile styles are included; a physical-phone test remains outstanding. The Docker recipe has not been built in this environment.

## Local environment and Hugging Face login

`./run.sh` loads the git-ignored `.env` and starts the app. Direct `codenames` invocation uses only exported environment variables. Authenticate once using the installed CLI:

```sh
.venv/bin/hf auth login
.venv/bin/hf auth whoami
./run.sh
```

The CLI supports browser sign-in or securely pasting an existing access token. For manual tokens, a read-only token is sufficient for model downloads. The Hugging Face library automatically uses the saved credential; there is no need to place a token in this repository or in shell history. Restart a running model process after authentication. Authentication does not itself provide cloud inference or resolve network/DNS problems.
