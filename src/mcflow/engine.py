"""The entire simulation: independent points in the unit square."""


def count_hits(rng, samples):
    hits = 0
    for _ in range(samples):
        x, y = rng.random(), rng.random()
        hits += x * x + y * y <= 1.0
    return hits
