def remove_unit_clause(clauses):
    # If there is a unit clause, propagate it (remove clauses that contain the variable, remove its negation from the other variables) and True, modified_clauses
    # Otherwise, return False, clauses
    pass


def pure_literal_assign(clauses):
    # Search for pure literals (those that appear only positively or only negatively) and assign them accordingly
    # Return True, modified_clauses if there was some change, and False, clauses otherwise
    pass


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
