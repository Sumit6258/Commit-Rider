"""Curve generation: Gaussian smoothing and periodic PCHIP interpolation.

PCHIP (monotone piecewise cubic Hermite) is C1-continuous and, unlike a natural cubic
spline, never overshoots: a spike between two zero days cannot dig a pit beside itself.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def gaussian_kernel(sigma: float) -> list[float]:
    radius = max(1, math.ceil(3.0 * sigma))
    weights = [math.exp(-0.5 * (k / sigma) ** 2) for k in range(-radius, radius + 1)]
    total = sum(weights)
    return [w / total for w in weights]


def smooth_circular(values: Sequence[float], sigma: float) -> list[float]:
    """Gaussian smoothing of a periodic sequence (``sigma`` in samples)."""
    n = len(values)
    if sigma < 0.05 or n < 2:
        return list(values)
    kernel = gaussian_kernel(sigma)
    radius = len(kernel) // 2
    out = []
    for i in range(n):
        acc = 0.0
        for k, weight in enumerate(kernel):
            acc += weight * values[(i + k - radius) % n]
        out.append(acc)
    return out


def pchip_slopes_periodic(y: Sequence[float]) -> list[float]:
    """Fritsch-Carlson slopes for uniformly spaced periodic data (spacing 1)."""
    n = len(y)
    deltas = [y[(i + 1) % n] - y[i] for i in range(n)]
    slopes = []
    for i in range(n):
        left, right = deltas[i - 1], deltas[i]
        if left * right > 0:
            slopes.append(2.0 * left * right / (left + right))
        else:
            slopes.append(0.0)
    return slopes


def sample_periodic_pchip(y: Sequence[float], sub: int) -> list[float]:
    """Evaluate the periodic PCHIP through ``y`` at ``sub`` samples per segment.

    The result has ``len(y) * sub`` samples; sample ``k`` lies at ``k / sub`` control
    intervals, so every ``sub``-th sample reproduces a control value exactly.
    """
    if sub < 1:
        raise ValueError("sub must be >= 1")
    n = len(y)
    if n < 2:
        raise ValueError("need at least two control points")
    slopes = pchip_slopes_periodic(y)
    out: list[float] = []
    for i in range(n):
        y0, y1 = y[i], y[(i + 1) % n]
        m0, m1 = slopes[i], slopes[(i + 1) % n]
        for s in range(sub):
            t = s / sub
            t2, t3 = t * t, t * t * t
            out.append(
                (2 * t3 - 3 * t2 + 1) * y0
                + (t3 - 2 * t2 + t) * m0
                + (-2 * t3 + 3 * t2) * y1
                + (t3 - t2) * m1
            )
    return out


def lipschitz_lower(h: Sequence[float], limit: float) -> list[float]:
    """Largest periodic sequence below ``h`` whose neighbouring samples differ by at most
    ``limit`` (a cone-shaped lower envelope), via two forward and two backward sweeps."""
    n = len(h)
    g = list(h)
    for k in range(2 * n):
        i = k % n
        bound = g[i - 1] + limit
        if g[i] > bound:
            g[i] = bound
    for k in range(2 * n):
        i = (n - 1 - k) % n
        bound = g[(i + 1) % n] + limit
        if g[i] > bound:
            g[i] = bound
    return g


def limit_rate(values: Sequence[float], max_step: float) -> list[float]:
    """Bound ``|values[i+1] - values[i]| <= max_step`` on a periodic sequence.

    The average of the lower and upper cone envelopes is exactly ``max_step``-Lipschitz
    and equals the input wherever the input already obeys the limit; a too-sharp step
    becomes a symmetric ramp centred on the step.
    """
    lower = lipschitz_lower(values, max_step)
    upper = [-v for v in lipschitz_lower([-v for v in values], max_step)]
    return [0.5 * (a + b) for a, b in zip(lower, upper, strict=True)]
