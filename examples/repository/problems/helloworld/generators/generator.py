import random
import string

t = int(input())
seed = int(input())
length = int(input())

random.seed(seed)
print(t)
for _ in range(t):
    print("".join(random.choices(string.ascii_lowercase, k=length)))
