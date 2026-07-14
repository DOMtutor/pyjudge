import random

seed = int(input())
n_min, n_max = map(int, input().split())
m_min, m_max = map(int, input().split())

random.seed(seed)
n, m = random.randint(n_min, n_max), random.randint(m_min, m_max)
k = random.binomialvariate(n - 1, 1 / n) + (1 if random.random() > 0.1 else 0)

print(f"{n} {m} {random.randint(1, n)}")
accepting = set(random.randint(1, n) for _ in range(k))
if accepting:
    print(f"{len(accepting)} {' '.join(map(str, accepting))}")
else:
    print("0")
for _ in range(n):
    print(" ".join(map(str, (random.randint(1, n) for _ in range(m)))))
