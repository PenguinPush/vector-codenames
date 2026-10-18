# Gemma Codenames backend

An independent Python embedding service and clue optimizer. The existing Next.js
app does not import or call this backend. There is no training or personalization.

## Run a random-board experiment

From the repository root:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[gemma,api,dev]'
python test_random_board.py --seed 42
```

If you use `uv`, replace the environment and installation steps with:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e '.[gemma,api,dev]'
.venv/bin/python test_random_board.py --seed 42
```

The runner uses **real Gemma embeddings**. The first invocation downloads model
weights and embeds the vocabulary. Subsequent runs reuse the downloaded weights
and cached vectors. A missing model or dependency is an error; the runner never
substitutes mock scores.

If Hugging Face requires access approval for the selected model, accept its terms
on the model page and authenticate using `hf auth login` or `HF_TOKEN` in your
environment. Do not put credentials in source files.

Useful variations:

```sh
# Five boards, with seeds 42 through 46; save every score and decision.
python test_random_board.py --seed 42 --boards 5 --json reports/boards.json

# Blue's perspective, with blue receiving the nine starting agents.
python test_random_board.py --seed 42 --team blue --starting-team blue

# Apple GPU or CUDA, when supported by your PyTorch installation.
python test_random_board.py --seed 42 --device mps
python test_random_board.py --seed 42 --device cuda

# Experiment with more demanding separation margins.
python test_random_board.py --seed 42 --min-similarity 0.60 \
  --neutral-margin 0.03 --opponent-margin 0.05 --assassin-margin 0.10

# Broaden the search using your own vocabulary; each line contains one word.
python test_random_board.py --seed 42 --vocabulary clues.txt --board-words board.txt

# Reproduce an encoder revision; replace COMMIT with the revision printed by a run.
python test_random_board.py --seed 42 --revision COMMIT --offline
```

Omit `--seed` for a fresh board. The actual seed is printed and saved. The board has
25 distinct words: 9 starting agents, 8 opposing agents, 7 neutral cards, and one
assassin. `--team` selects the team to generate a clue for independently of who
starts. This is a standalone spymaster experiment, so the entire key is visible.

Output includes:

- Chosen one-word clue and target count, explicitly marked qualified or fallback.
- Target list, all 25 cosine scores, and their ranking.
- Weakest target, closest raw danger, and the danger that limits the margin.
- Raw separation and remaining slack after the required danger margin.
- A feasibility witness for every possible target count, including rejected counts.
- Alternative clues, model revision, thresholds, board seed, and elapsed time.

The bundled 872-word list is an original starter vocabulary for fast experiments.
It is not an official Codenames word list or the planned 20,000–50,000-word corpus.
Both the default board and clue pools use it. Larger supplied vocabularies improve
search coverage; the optimizer finds the exact best qualifying clue **within the
supplied vocabulary**, not among all possible English words. Input files accept
one word per line and `#` comments; blank lines and duplicates are removed.

## Model and caching

The default is `google/embeddinggemma-2`, as specified by Google's current
[inference guide](https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers).
The encoder uses Sentence Transformers, the `STS` prompt on both sides, full
768-dimensional normalized embeddings, text-only configuration, and float32.
CPU is the default. The model is loaded only on the first request and reused.
`--model`, `--revision`, `--device`, and `--batch-size` are configurable.
The `gemma` extra includes the processor's Pillow/torchvision dependencies even
though the model's vision and audio encoders are disabled.

The supplied [fine-tuning guide](https://ai.google.dev/gemma/docs/embeddinggemma/fine-tuning-embeddinggemma-with-sentence-transformers)
was also reviewed; this implementation only performs inference.

Caches live in `backend/.cache/`, which is ignored by Git. Set `--cache-dir` to
change this. Vector cache identities include the resolved model commit, actual
prompt, dimension, dtype, device, library versions, and ordered word list. Mutable
local models without a resolved commit get a fresh cache identity per process.
Writes use atomic replacement, and corrupt entries are recomputed. Deleting the
cache only causes downloads/encoding to repeat. `--offline` prevents model network
lookups once all required weights are cached. Pin a printed commit with
`--revision` when comparing experiments across time.

## Mathematical objective

For normalized embeddings, cosine similarity is a dot product:

```text
s(c, w) = e(c) · e(w)
```

For each legal clue `c`, sort all unrevealed friendly cards by decreasing score.
The first `k` cards form its strongest possible group of that size:

```text
W(c, k) = similarity of the kth-ranked friendly word
D(c)    = max over dangerous cards u of [s(c, u) + margin(u)]
qualifies(c, k) iff W(c, k) >= max(min_similarity, D(c))
```

Dangerous cards include every unrevealed opposing agent, neutral, and assassin.
The default experimental margins are 0.035, 0.02, and 0.07 respectively; minimum
target similarity is 0.50. These are adjustable starting values, not calibrated
probabilities of human success. Margins must be positive so score ties with a
dangerous card never qualify. Revealed cards are excluded from target and danger
sets. With no dangers left, only the minimum similarity matters and reported
danger/gap fields are null.

Select the lexicographic maximum:

```text
(k, W(c, k) - D(c), mean target similarity)
```

Alphabetical clue order resolves an exact remaining tie. The sorted prefix has
the best minimum and mean score among all subsets of size `k`; therefore scanning
prefixes finds the same result as enumerating every target subset. We scan every
legal candidate rather than using approximate nearest-neighbor search.

If no candidate qualifies even for `k = 1`, select one target by greatest
danger-margin slack, then target similarity. The result sets `fallback=true`,
`qualified=false`, and `maximum_safe_count=0`, and identifies failed constraints.
Thresholds are never silently relaxed. A large similarity average cannot hide a
weak target below a dangerous card.

Clue filtering rejects non-single English words, exact matches to unrevealed
cards, matching English Snowball stems, and obvious substring/compound reuse
with parts at least four letters long. This conservative spelling policy can
reject some otherwise legal words and cannot judge every semantic Codenames rule.

## Optional local HTTP service

```sh
cd backend
source .venv/bin/activate
uvicorn gemma_codenames.api:app --host 127.0.0.1 --port 8001
```

`GET /health` checks the process without loading the model. `POST /clues` performs
the same search as the script. Interactive request documentation is at
`http://127.0.0.1:8001/docs`. A small request for experimentation:

```json
{
  "team": "red",
  "board": [
    {"word": "planet", "kind": "red"},
    {"word": "moon", "kind": "red"},
    {"word": "rocket", "kind": "assassin"},
    {"word": "glass", "kind": "neutral"}
  ],
  "config": {"assassin_margin": 0.07},
  "top_n": 5
}
```

The endpoint accepts 1–25 unique cards to support small experiments as well as
complete boards. Each card optionally has `revealed: true`. Requests are validated
before encoding. Model calls are serialized within each process. Use one Uvicorn
worker to share one model and cache. Invalid input returns 422; unavailable model
inference returns 503. This is a local spymaster laboratory endpoint: its response
contains hidden identities and targets and is not a player-facing game API.

Environment options for the HTTP process: `GEMMA_MODEL_ID`, `GEMMA_REVISION`,
`GEMMA_DEVICE`, `GEMMA_BATCH_SIZE`, `GEMMA_CACHE_DIR`, `GEMMA_VOCABULARY`, and
`GEMMA_OFFLINE=1`. The CLI uses its explicit flags.

## Verification

```sh
cd backend
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Tests use controlled vectors and need no weights or Hugging Face access. To run
just these tests on a fresh environment, install `-e '.[api,dev]'`. They cover
lexicographic priorities, assassin margins, threshold boundaries, low-similarity
fallbacks, revealed cards, illegal clues, caching, input validation, API failures,
and comparison against exhaustive enumeration of every target subset across 100
random score matrices. These establish algorithm correctness; the real-model
script evaluates actual associations. Human clue quality still requires playing
and tuning on real boards.
