"""Bot-only sparse vector communication, with an explicit lossy wire protocol.

An exact single-word baseline followed by bounded beam search. Coefficient LPs
maximize an unnormalized all-target margin; only rounded, normalized, decoded
scores determine which message wins. Search reports never claim global optimality.
"""

import time
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import linprog

from .geometry import normalized
from .optimizer import CluePolicy


class CommunicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    common_words_only: bool = False
    max_words: int = Field(default=3, ge=1, le=12)
    coefficients: bool = False
    precision: int = Field(default=2, ge=0, le=4)
    target_gap: float = Field(default=0.001, ge=0.000001, le=1)
    beam_width: int = Field(default=8, ge=1, le=32)
    shortlist: int = Field(default=32, ge=4, le=128)
    max_evaluations: int = Field(default=2000, ge=1, le=20000)
    time_limit: float = Field(default=5.0, ge=0.1, le=60)
    stop_at_one_shot: bool = True


def identity(metadata):
    return {key: metadata.get(key) for key in
            ("model_id", "resolved_revision", "dimensions", "prompt", "prompt_name", "normalized")}


def quantize(weights, precision):
    """Largest-remainder rounding, keeping nonnegative coefficients summing to one."""
    weights = np.maximum(np.asarray(weights, dtype=float), 0)
    if not np.isfinite(weights).all() or weights.sum() <= 0:
        raise ValueError("Invalid coefficients")
    scaled = weights / weights.sum() * 10**precision
    units = np.floor(scaled).astype(int)
    count = 10**precision - int(units.sum())
    order = np.argsort(-(scaled - units), kind="stable")
    units[order[:count]] += 1
    return units / 10**precision


def decode_vectors(message, vectors):
    """Only the message and component embeddings are needed; no key or ideal vector."""
    if message.get("version") != 1 or type(message.get("weighted")) is not bool:
        raise ValueError("Unsupported vector message")
    components = message.get("components", [])
    if not 1 <= len(components) <= 12 or len(vectors) != len(components):
        raise ValueError("Invalid component count")
    words = [c["word"] for c in components]
    if len(set(words)) != len(words):
        raise ValueError("Clue components must be distinct")
    weights = np.array([c["coefficient"] for c in components], dtype=float)
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError("Coefficients must be finite and positive")
    if message["weighted"]:
        precision = message.get("precision")
        if type(precision) is not int or not 0 <= precision <= 4:
            raise ValueError("Invalid coefficient precision")
        if not np.isclose(weights.sum(), 1, atol=1e-10, rtol=0):
            raise ValueError("Coefficients must sum to one")
        if not np.allclose(weights * 10**precision, np.round(weights * 10**precision), atol=1e-8, rtol=0):
            raise ValueError("Coefficients exceed transmitted precision")
    elif not np.all(weights == 1):
        raise ValueError("Unweighted messages must use equal unit coefficients")
    total = weights @ normalized(vectors)
    norm = float(np.linalg.norm(total))
    if norm < 1e-8:
        raise ValueError("Component sum cancels to near zero")
    return total / norm


def evaluate(direction, board_vectors, friendly, danger, gap):
    scores = board_vectors @ direction
    threshold = float(scores[danger].max()) if len(danger) else -1.0
    order = friendly[np.argsort(-scores[friendly], kind="stable")]
    targets = order[scores[order] - threshold >= gap]
    full_gap = float(scores[order[-1]] - threshold)
    weakest = targets[-1] if len(targets) else order[0]
    return {"scores": scores, "targets": targets, "coverage": len(targets),
            "full_gap": full_gap, "gap": float(scores[weakest] - threshold),
            "threshold": threshold + gap, "weakest": int(weakest),
            "danger": int(danger[np.argmax(scores[danger])]) if len(danger) else None,
            "mean": float(scores[targets].mean()) if len(targets) else float(scores[order[0]])}


def solve_ideal(board_vectors, friendly, danger):
    """Convex unit-ball upper bound; positive optimum is a unit separating direction."""
    import cvxpy as cp
    if not len(danger):
        return {"status": "unavailable", "note": "No dangerous cards remain."}, None
    _, singular, vt = np.linalg.svd(board_vectors, full_matrices=False)
    basis = vt[singular > 1e-10].T
    reduced = board_vectors @ basis
    differences = (reduced[friendly, None] - reduced[danger][None, :]).reshape(-1, basis.shape[1])
    q = cp.Variable(basis.shape[1])
    gamma = cp.Variable()
    problem = cp.Problem(cp.Maximize(gamma), [cp.norm(q) <= 1, differences @ q >= gamma])
    try:
        problem.solve(solver="CLARABEL", max_iter=200)
    except cp.error.SolverError:
        return {"status": "solver_error", "note": "Ideal solve failed; discrete search still runs."}, None
    if problem.status != "optimal" or q.value is None:
        return {"status": problem.status, "note": "No reliable numerical upper bound."}, None
    vector = basis @ q.value
    norm = np.linalg.norm(vector)
    report = {"status": "optimal", "upper_bound": float(gamma.value),
              "note": "Numerical unit-ball upper bound for all targets; not a legal clue or formal certificate."}
    if gamma.value <= 1e-8 or norm < 1e-8:
        report["note"] += " No robust positive separating direction was found."
        return report, None
    return report, vector / norm


@dataclass
class Candidate:
    indices: tuple
    weights: np.ndarray
    direction: np.ndarray
    stats: dict
    alignment: float
    rounding_error: float = 0.0

    def key(self):
        return (self.stats["coverage"], self.stats["gap"], -len(self.indices), self.stats["mean"])


def search(vocabulary, vectors, board, board_vectors, team, config, progress=None):
    notify = progress or (lambda stage: None)
    start = time.perf_counter()
    vectors, board_vectors = normalized(vectors), normalized(board_vectors)
    friendly = np.array([i for i, c in enumerate(board) if not c.revealed and c.kind == team], dtype=int)
    danger = np.array([i for i, c in enumerate(board) if not c.revealed and c.kind != team], dtype=int)
    if not len(friendly):
        raise ValueError("No remaining targets")
    policy = CluePolicy(board)
    legal = np.array([i for i, w in enumerate(vocabulary) if policy.allows(w)], dtype=int)
    if not len(legal):
        raise ValueError("No legal communication words remain")
    notify("Finding the ideal separating vector · convex unit-ball optimization")
    ideal, ideal_vector = solve_ideal(board_vectors, friendly, danger)
    if ideal_vector is not None:
        ideal["actual_gap"] = evaluate(ideal_vector, board_vectors, friendly, danger, config.target_gap)["full_gap"]
    notify("Searching all legal single words · exact baseline")
    # Chunk the exact baseline so a large vocabulary never requires a huge dense matrix.
    candidates = []
    for offset in range(0, len(legal), 2048):
        ids = legal[offset:offset+2048]
        scores = vectors[ids] @ board_vectors.T
        thresholds = scores[:, danger].max(axis=1) if len(danger) else np.full(len(ids), -1.0)
        ordered = np.sort(scores[:, friendly], axis=1)[:, ::-1]
        counts = np.sum(ordered - thresholds[:, None] >= config.target_gap, axis=1)
        gaps = ordered[np.arange(len(ids)), np.maximum(counts-1, 0)] - thresholds
        # Keep enough for the shortlist/beam, plus directional and individual-target diversity below.
        means = np.array([row[:max(1, int(n))].mean() for row, n in zip(ordered, counts)])
        order = set(np.lexsort((-means, -gaps, -counts))[:max(config.shortlist, config.beam_width)*2].tolist())
        order.add(int(np.argmax(ordered[:, -1]-thresholds)))
        if ideal_vector is not None:
            order.update(np.argsort(-(vectors[ids] @ ideal_vector))[:config.beam_width].tolist())
        for j in sorted(order):
            idx = int(ids[j])
            stats = evaluate(vectors[idx], board_vectors, friendly, danger, config.target_gap)
            candidates.append(Candidate((idx,), np.ones(1), vectors[idx], stats,
                                        float(vectors[idx] @ ideal_vector) if ideal_vector is not None else 0))
    candidates.sort(key=lambda c: c.key(), reverse=True)
    best = candidates[0]
    baseline = best
    evaluations = len(legal)
    extension_evaluations = 0
    lp_failures = 0
    trace = []
    seen = set()

    def describe(candidate):
        return {"words": [vocabulary[i] for i in candidate.indices],
                "coefficients": candidate.weights.tolist() if config.coefficients else None,
                "word_count": len(candidate.indices), "coverage": candidate.stats["coverage"],
                "full_gap": candidate.stats["full_gap"], "gap": candidate.stats["gap"],
                "alignment": candidate.alignment, "rounding_error": candidate.rounding_error}

    live_trace = []
    last_live = 0.0

    def emit_live(depth, candidate=None, force=False):
        nonlocal last_live
        now = time.perf_counter()
        if not force and now - last_live < .5:
            return
        last_live = now
        live_trace.append({'depth': depth, 'evaluations': evaluations,
                           'coverage': best.stats['coverage'], 'gap': best.stats['full_gap']})
        del live_trace[:-24]
        notify({'stage': f'Searching up to {depth} words · {evaluations:,} evaluations',
                'search': {'depth': depth, 'evaluations': evaluations,
                           'extension_evaluations': extension_evaluations,
                           'elapsed': now-start, 'friendly_count': len(friendly),
                           'target_gap': config.target_gap, 'best': describe(best),
                           'candidate': describe(candidate) if candidate else None,
                           'trace': list(live_trace)}})

    def record(depth):
        trace.append({"depth": depth, "evaluations": evaluations,
                      "elapsed": time.perf_counter()-start, "best": describe(best),
                      "best_one_shot_gap": max(c.stats["full_gap"] for c in candidates)})

        emit_live(depth, force=True)

    # Shortlist is the union of actual-board winners, ideal neighbors and target neighbors.
    # It may exceed the requested size by at most 2*shortlist + 2*friendly_count.
    pool = {c.indices[0] for c in candidates[:config.shortlist]}
    if ideal_vector is not None:
        pool.update(int(i) for i in legal[np.argsort(-(vectors[legal] @ ideal_vector))[:config.shortlist]])
    target_scores = vectors[legal] @ board_vectors[friendly].T
    for column in range(len(friendly)):
        pool.update(int(i) for i in legal[np.argsort(-target_scores[:, column])[:2]])
    pool = sorted(pool)
    beam = candidates[:config.beam_width]
    if ideal_vector is not None:
        extra = sorted(candidates, key=lambda c: c.alignment, reverse=True)[:config.beam_width//2]
        beam = list({c.indices: c for c in [*beam, *extra]}.values())
    record(1)
    stop = "word_limit"
    if config.stop_at_one_shot and best.stats["coverage"] == len(friendly):
        stop = "one_shot"
    else:
        deadline = time.perf_counter() + config.time_limit
        for depth in range(2, config.max_words+1):
            notify(f"Encoding direction · searching up to {depth} words" + (" with rounded coefficients" if config.coefficients else " with equal weights"))
            extensions = []
            exhausted = False
            for parent in beam:
                for idx in pool:
                    support = tuple(sorted(set((*parent.indices, idx))))
                    if len(support) != depth or support in seen:
                        continue
                    seen.add(support)
                    if extension_evaluations >= config.max_evaluations or time.perf_counter() >= deadline:
                        stop = "evaluation_budget" if extension_evaluations >= config.max_evaluations else "time_budget"
                        exhausted = True
                        break
                    selected = vectors[list(support)]
                    weight_options = [np.full(depth, 1/depth)]
                    if config.coefficients and len(danger):
                        pair_scores = (board_vectors[friendly, None] - board_vectors[danger][None, :]).reshape(-1, vectors.shape[1]) @ selected.T
                        objective = np.r_[np.zeros(depth), -1.0]
                        result = linprog(objective, A_ub=np.c_[-pair_scores, np.ones(len(pair_scores))],
                                         b_ub=np.zeros(len(pair_scores)), A_eq=[np.r_[np.ones(depth), 0]],
                                         b_eq=[1], bounds=[(0, 1)]*depth+[(None, None)], method="highs",
                                         options={"time_limit": max(.001, deadline-time.perf_counter())})
                        if result.success:
                            weight_options.append(result.x[:depth])
                        else:
                            lp_failures += 1
                    for weights in weight_options:
                        raw_sum = weights @ selected
                        raw_norm = np.linalg.norm(raw_sum)
                        transmitted = quantize(weights, config.precision) if config.coefficients else np.ones(depth)
                        active = transmitted > 0
                        ids = tuple(np.array(support)[active].tolist())
                        weights_sent = transmitted[active]
                        total = weights_sent @ vectors[list(ids)]
                        norm = np.linalg.norm(total)
                        if norm < 1e-8:
                            continue
                        direction = total/norm
                        error = float(np.linalg.norm(direction-raw_sum/raw_norm)) if raw_norm >= 1e-8 else 0.0
                        candidate = Candidate(ids, weights_sent, direction,
                            evaluate(direction, board_vectors, friendly, danger, config.target_gap),
                            float(direction @ ideal_vector) if ideal_vector is not None else 0.0, error)
                        extensions.append(candidate)
                        if candidate.key() > best.key():
                            best = candidate
                    evaluations += 1
                    extension_evaluations += 1
                    emit_live(depth, extensions[-1] if extensions else None)
                if exhausted:
                    break
            candidates.extend(extensions)
            record(depth)
            if config.stop_at_one_shot and best.stats["coverage"] == len(friendly):
                stop = "one_shot"
                break
            if exhausted:
                break
            # Include one equal-weight expansion per support so zero LP coefficients
            # never erase the support needed for future deeper search.
            unique = {}
            for candidate in sorted(extensions, key=lambda c: c.key(), reverse=True):
                if len(candidate.indices) == depth:
                    unique.setdefault(candidate.indices, candidate)
            ordered = list(unique.values())
            beam = ordered[:config.beam_width]
            if ideal_vector is not None:
                extra = sorted(ordered, key=lambda c: c.alignment, reverse=True)[:config.beam_width//2]
                beam = list({c.indices: c for c in [*beam, *extra]}.values())
            if not beam:
                stop = "search_exhausted"
                break
    count = max(1, best.stats["coverage"])
    wire = {"version": 1, "weighted": config.coefficients,
            "precision": config.precision if config.coefficients else None,
            "components": [{"word": vocabulary[i], "coefficient": float(a)}
                           for i, a in zip(best.indices, best.weights)], "count": count}
    ranked = sorted(candidates, key=lambda c: c.key(), reverse=True)
    alternatives = []
    signatures = set()
    for candidate in ranked:
        signature = (candidate.indices, tuple(candidate.weights))
        if signature not in signatures:
            alternatives.append(describe(candidate))
            signatures.add(signature)
        if len(alternatives) >= 5:
            break
    return {"message": wire, "best": describe(best), "baseline": describe(baseline),
            "ideal": ideal, "trace": trace, "alternatives": alternatives,
            "legal_candidates": len(legal), "shortlist_size": len(pool),
            "evaluations": evaluations, "extension_evaluations": extension_evaluations,
            "lp_failures": lp_failures, "stop_reason": stop,
            "config": config.model_dump(), "search_seconds": time.perf_counter()-start,
            "optimality": "Exact single-word baseline; bounded multiword beam search, not a global optimum.",
            "_ideal_vector": ideal_vector, "_encoded_vector": best.direction}
