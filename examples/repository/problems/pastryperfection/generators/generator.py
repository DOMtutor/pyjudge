import random

seed = int(input())
n_min, n_max = map(int, input().split())
m_min, m_max = map(int, input().split())

random.seed(seed)
n, m = random.randint(n_min, n_max), random.randint(m_min, m_max)

print(f"{m} {n}")
for _ in range(n):
    clause = [random.choice([k, -k]) for k in range(1, m + 1) if random.random() < 0.5]
    print(*(clause + [0]))
