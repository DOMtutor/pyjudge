#!/usr/bin/env python3

m, n = map(int, input().split())
clauses = [set(map(int, input().split()[:-1])) for _ in range(n)]
valid = False
for assignment in range(2**m):
    if all(
        any((assignment >> (abs(i) - 1)) & 1 == (i > 0) for i in clause)
        for clause in clauses
    ):
        valid = True
print("yes" if valid else "no")
