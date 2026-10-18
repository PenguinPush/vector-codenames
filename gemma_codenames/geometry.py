"""Display-only PCA and an optional convex upper bound for the one-shot objective."""

import numpy as np


def normalized(vectors):
    values = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if not np.isfinite(values).all() or np.any(norms == 0):
        raise ValueError("Expected finite, nonzero embeddings.")
    return values / norms


def projection(words, vectors, extra=None):
    """Fit PCA only to the board: role colors never influence the geometry."""
    values = normalized(vectors)
    center = values.mean(axis=0)
    _, singular, basis = np.linalg.svd(values - center, full_matrices=False)
    axes = basis[:2].T
    if axes.shape[1] < 2:
        axes = np.pad(axes, ((0, 0), (0, 2 - axes.shape[1])))
    # Deterministic signs for repeatable plots (SVD signs are arbitrary).
    for column in range(2):
        if axes[np.argmax(np.abs(axes[:, column])), column] < 0:
            axes[:, column] *= -1
    xy = (values - center) @ axes
    points = [{"word": word.upper(), "x": float(p[0]), "y": float(p[1]), "type": "word"}
              for word, p in zip(words, xy)]
    for name, vector in extra or []:
        point = (normalized([vector])[0] - center) @ axes
        points.append({"word": name.upper(), "x": float(point[0]), "y": float(point[1]),
                       "type": "clue"})
    total = float(np.sum(singular ** 2))
    return {"method": "PCA", "dimensions": values.shape[1], "points": points,
            "variance": float(np.sum(singular[:2] ** 2) / total) if total else 0.0,
            "note": "2D projection only. Decisions use full-dimensional cosine similarities."}


def ideal_direction(vectors, board, team, config, vocabulary_vectors, vocabulary):
    """Solve over the unit BALL, a relaxation of the discrete word search.

    Constraints include the same association floor as the actual word search.
    Only an optimal solve is reported as a numerical bound, never as a certified
    impossibility proof. Nearest words are explanatory; they do not select the clue.
    """
    try:
        import cvxpy as cp
    except ImportError:
        return {"status": "unavailable", "note": "Install the geometry extra for the ideal-direction experiment."}
    vectors = normalized(vectors)
    friendly = [i for i, c in enumerate(board) if c.kind == team and not c.revealed]
    danger = [i for i, c in enumerate(board) if c.kind != team and not c.revealed]
    if not danger:
        return {"status": "unavailable", "note": "No dangerous cards remain."}
    # Restrict q to the span of the board. An orthogonal component changes no
    # board dot products and only increases its norm. This is exact dimensional reduction.
    _, singular, vt = np.linalg.svd(vectors, full_matrices=False)
    basis = vt[singular > 1e-10].T
    reduced = vectors @ basis
    q = cp.Variable(basis.shape[1])
    gamma = cp.Variable()
    constraints = [cp.norm(q, 2) <= 1, reduced[friendly] @ q >= config.min_similarity]
    for f in friendly:
        for u in danger:
            constraints.append((reduced[f] - reduced[u]) @ q >= config.margin(board[u].kind) + gamma)
    problem = cp.Problem(cp.Maximize(gamma), constraints)
    try:
        problem.solve(solver="CLARABEL")
    except cp.error.SolverError:
        return {"status": "solver_error", "note": "The optional geometric solve failed; exact word search is unaffected."}
    if problem.status == "infeasible":
        return {"status": "infeasible", "note": "The solver found no unit-ball vector meeting the minimum similarity floor for all friendly words. This is a numerical result, not a formal certificate."}
    if problem.status != "optimal" or q.value is None:
        return {"status": problem.status, "note": "No reliable bound returned by the solver."}
    direction = basis @ q.value
    norm = float(np.linalg.norm(direction))
    if norm < 1e-8:
        return {"status": "degenerate", "note": "The optimal direction has effectively zero length."}
    similarities = normalized(vocabulary_vectors) @ (direction / norm)
    nearest = np.argsort(-similarities)[:5]
    return {"status": "optimal", "upper_bound": float(gamma.value), "norm": norm,
            "nearest": [{"word": vocabulary[i], "similarity": float(similarities[i])}
                        for i in nearest],
            "note": "Numerical upper bound over ideal vectors with the same similarity floor. A positive bound does not guarantee a legal word exists.",
            "vector": direction.tolist()}
