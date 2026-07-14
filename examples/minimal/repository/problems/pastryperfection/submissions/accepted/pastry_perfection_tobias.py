#!/usr/bin/env python3


def recurse(index: int, value: bool, remaining_clauses):
    remaining = []
    variable = index if value else -index
    for clause in remaining_clauses:
        if -variable in clause:
            if len(clause) == 1:
                return False  # Conflict
            clause_copy = set(clause)
            clause_copy.remove(-variable)
            remaining.append(clause_copy)
        elif variable not in clause:
            remaining.append(clause)
    if not remaining:
        return True  # All resolved
    return solve(index + 1, remaining)


def solve(variable, remaining_clauses):
    return recurse(variable, False, remaining_clauses) or recurse(
        variable, True, remaining_clauses
    )


m, n = map(int, input().split())
clauses = [set(map(int, input().split()[:-1])) for _ in range(n)]
print("yes" if all(clauses) and solve(0, clauses) else "no")
