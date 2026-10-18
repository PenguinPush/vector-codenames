# Next milestone: EmbeddingGemma

The web game is the current milestone. This document records the integration plan; none of the model work below is implemented.

## 1. Confirm the model and encoding

Review the two supplied Google guides before implementation:

- [Inference with Sentence Transformers](https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers)
- [Fine-tuning with Sentence Transformers](https://ai.google.dev/gemma/docs/embeddinggemma/fine-tuning-embeddinggemma-with-sentence-transformers)

They currently describe `google/embeddinggemma-2`. Pin a model revision and compatible Python dependencies. Begin with full-size normalized embeddings and the same similarity task prefix for clue candidates and board words. Benchmark the available hardware before choosing precision or reducing dimensions.

The word given to a teammate is the **clue**. The encoding task prefix supplied to the model is a separate **model prompt**; it should remain fixed while evaluating clue quality.

## 2. Build a real candidate vocabulary

Choose a licensed, familiar English clue vocabulary. Filter unrevealed board words and disallowed forms before search. Batch-encode candidates once. Key caches by model revision, prompt, dimension, normalization settings, and vocabulary version.

EmbeddingGemma returns vectors, not generated clue text. The optimizer selects a real legal word from the vocabulary. An average target vector is not itself a playable clue.

## 3. Review and implement the optimization

For normalized embeddings, `s(c,w) = e(c) · e(w)` is cosine similarity.

For each candidate clue, sort friendly words by score. For a proposed count `k`, let `W(c,k)` be the score of the weakest of the first `k` friendly words. Let:

```text
D(c) = max(score(c, unsafe_word) + required_margin(unsafe_word))
```

The candidate/count qualifies when:

```text
W(c,k) >= max(minimum_target_similarity, D(c))
```

Rank qualifying proposals lexicographically by:

1. Target count, largest first.
2. Safety gap `W(c,k) - D(c)`, largest first.
3. Average target similarity, largest first.

Use a larger required margin for the assassin. Attempt the entire friendly set first; use smaller groups only when larger groups fail. Calibrate the margins and absolute floor on held-out boards. Define and visibly identify a fallback if no one-word clue qualifies. These choices need review before replacing the demo provider.

## 4. Add an asynchronous Python service

The proposed service owns model loading, cached embeddings, legal candidate search, and diagnostics. The Next.js server owns sessions, room permissions, game state, and the web UI.

Suggested service operations:

```text
POST /score-clue  { clue, public_words, model_version }
POST /propose-clue { board_with_key, team, scoring_config, model_version }
```

Responses should include the model/vocabulary revision, clue, count, per-word cosine scores, intended targets, weakest target, strongest dangerous alternative, required margins, raw and adjusted gaps, selected objective values, and a compact list of alternative candidates.

The current demo `BotProvider` is synchronous. Convert it to an asynchronous provider when adding the service. Do not wait for inference while holding the room's mutation lock:

1. Capture room version, active slot, and permitted input.
2. Mark a single bot job in flight for that version.
3. Run inference outside the room lock.
4. Reacquire the lock and validate the version and active controller.
5. Apply the result only if still current; otherwise discard it.
6. Publish role-filtered state and schedule the next action.

Handle timeouts and service failures as a visible paused bot state. Never silently present synthetic scores as model output. Keep model credentials on the server.

## 5. Preserve the information boundary

Only a spymaster request includes hidden colors. A guesser receives public words, clue, count, scores, and public history. It never receives intended targets or an assassin label. Full clue diagnostics go to spymaster viewers and the postgame replay. Guesser views expose rankings and actual guess decisions.

The browser already consumes structured analysis. Replace `source: "demo"` with `source: "gemma"` only for genuine inference results, and update the demo labels to describe the real model and cosine scores.

## 6. Evaluate before personalizing

Measure correctly guessed words per clue, turns to finish, assassin losses, human agreement, and latency. Keep held-out boards separate from tuning data. Same-model self-play is useful for consistency but can exaggerate how understandable clues are to people.

Then add player-specific feedback and an inexpensive learned scorer over frozen embeddings. Actual model fine-tuning follows after enough reviewed examples exist. Preserve multiple valid targets as positives; do not label a semantic association negative merely because a card happened to be the opponent's color. Upgrade model checkpoints between games and re-encode the vocabulary after encoder changes.

## Remaining delivery phases

| Phase | Status |
| --- | --- |
| Next.js/Tailwind UI and four role slots | Implemented |
| Server-owned game rules, private views, live updates | Implemented |
| Demo bot turns, scores, and explanation panels | Implemented as placeholders |
| Real EmbeddingGemma encoding and vocabulary | Pending review |
| Exact coverage/margin optimizer and calibration | Pending review |
| Python worker integration and failure recovery | Pending |
| Hosted service with transactional room storage | Pending |
| Player feedback and personalized scoring | Later |
| Encoder fine-tuning | Later |
