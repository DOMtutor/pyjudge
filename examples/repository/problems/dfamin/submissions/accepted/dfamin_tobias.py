from collections import defaultdict

state_count, alphabet_size, initial_state = map(int, input().split())
accepting = set(int(s) - 1 for s in input().split()[1:])

dfa = []

for _ in range(state_count):
    dfa.append(tuple(int(t) - 1 for t in input().split()))

queue = [initial_state - 1]
reachable = set(queue)
while queue:
    s = queue.pop()
    for t in dfa[s]:
        if t not in reachable:
            reachable.add(t)
            queue.append(t)

accepting.intersection_update(reachable)

if accepting:
    partition = {s: 0 if s in accepting else 1 for s in reachable}
    partitions = 2
    while True:
        signatures = defaultdict(set)
        for s in reachable:
            signature = (partition[s], tuple(partition[t] for t in dfa[s]))
            signatures[signature].add(s)
        if len(signatures) == partitions:
            break
        partitions = len(signatures)
        for i, group in enumerate(signatures.values()):
            for s in group:
                partition[s] = i

    print(partitions)
else:
    print("1")
