import random

seed = int(input())
n_min, n_max = map(int, input().split())
m_min, m_max = map(int, input().split())

r = random.Random(seed)
n, m = r.randint(n_min, n_max), r.randint(m_min, m_max)
k = r.binomialvariate(n - 1, 0.2) + (1 if r.random() > 0.1 else 0)

path = list(range(n))
r.shuffle(path)

print(f"{n} {m} {path[0] + 1}")
path_successor = dict(enumerate(path))

accepting = set(r.randint(1, n) for _ in range(k))
if accepting:
    print(f"{len(accepting)} {' '.join(map(str, accepting))}")
else:
    print("0")
for i in range(n):
    if i + 1 in accepting and r.random() > 0.1:
        print(" ".join([str(i + 1)] * m))
    else:
        print(
            " ".join(
                [str(path_successor[i] + 1)]
                + list(map(str, (r.randint(1, n) for j in range(m - 1))))
            )
        )
