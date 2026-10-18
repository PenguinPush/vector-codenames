"""Linear, origin-preserving PCA coordinates for honest vector-addition diagrams."""
import numpy as np
from .geometry import normalized


def transmission_projection(words, board_vectors, message, component_vectors, decoded, ideal=None):
    board = normalized(board_vectors)
    # Fit axes on centered board data, but DO NOT subtract the mean when displaying
    # vectors: components must add in plot coordinates just as in the full space.
    _, singular, vt = np.linalg.svd(board-board.mean(axis=0), full_matrices=False)
    axes = vt[:2].T
    if axes.shape[1] < 2:
        axes = np.pad(axes, ((0, 0), (0, 2-axes.shape[1])))
    for j in range(2):
        if axes[np.argmax(np.abs(axes[:, j])), j] < 0:
            axes[:, j] *= -1
    def point(name, vector, kind, **extra):
        xy = vector @ axes
        return {"word": name.upper(), "x": float(xy[0]), "y": float(xy[1]), "type": kind, **extra}
    points = [point(w, v, "word") for w,v in zip(words, board)]
    components = normalized(component_vectors)
    coefficients = np.array([c["coefficient"] for c in message["components"]])
    if not message["weighted"]:
        coefficients /= coefficients.sum()
    running = np.zeros(board.shape[1])
    contributions = []
    for c,v,a in zip(message["components"], components, coefficients):
        points.append(point(c["word"], v, "component", coefficient=float(a)))
        before = running @ axes
        running += a*v
        after = running @ axes
        contributions.append({"word": c["word"], "coefficient": float(a),
                              "from": before.tolist(), "to": after.tolist()})
    points.append(point("weighted sum", running, "sum"))
    points.append(point("decoded", decoded, "decoded"))
    if ideal is not None:
        points.append(point("ideal", ideal, "ideal"))
    total = float(np.sum(singular**2))
    return {"method": "PCA axes, origin preserved", "dimensions": board.shape[1],
            "points": points, "contributions": contributions,
            "variance": float(np.sum(singular[:2]**2)/total) if total else 0.0,
            "note": "Linear 2D projection: arrows add exactly here, but angles and distances are approximate. Decisions use full-dimensional cosine."}
