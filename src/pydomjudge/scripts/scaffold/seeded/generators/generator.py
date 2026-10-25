"""Reads a seed file on stdin (here: the random seed and how large the numbers
may be) and writes one test input. Must be deterministic."""

import random

seed, limit = map(int, open(0).read().split())
rng = random.Random(seed)
print(rng.randint(-limit, limit), rng.randint(-limit, limit))
