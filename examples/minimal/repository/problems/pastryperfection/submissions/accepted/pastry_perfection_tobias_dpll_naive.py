#!/usr/bin/env python3


def remove_unit_clause(clauses):
    for c in clauses:
        if len(c) == 1:
            v = next(iter(c))
            return True, [cl - {-v} for cl in clauses if v not in cl]
    return False, clauses


def pure_literal_assign(clauses):
    literals = set()
    positive_literals = set()
    negative_literals = set()
    for c in clauses:
        for v in c:
            if abs(v) in literals:
                if v < 0:
                    if -v in positive_literals:
                        positive_literals.remove(-v)
                else:
                    if -v in negative_literals:
                        negative_literals.remove(-v)
            else:
                literals.add(abs(v))
                if v > 0:
                    positive_literals.add(v)
                else:
                    negative_literals.add(v)
    if not positive_literals and not negative_literals:
        return False, clauses
    removed = positive_literals | negative_literals
    return True, [cl - removed for cl in clauses if not cl.intersection(removed)]


def dpll(clauses):
    while True:
        change, clauses = remove_unit_clause(clauses)
        if not change:
            break
    while True:
        change, clauses = pure_literal_assign(clauses)
        if not change:
            break
    if not clauses:
        return True
    if any(not cl for cl in clauses):
        return False
    literal = next(iter(clauses[0]))
    return dpll(clauses + [{literal}]) or dpll(clauses + [{-literal}])


m, n = map(int, input().split())
cs = [set(map(int, input().split()[:-1])) for _ in range(n)]
print("yes" if dpll(cs) else "no")
