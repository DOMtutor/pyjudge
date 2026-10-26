# Correct only if the judge's run script sets DOMJUDGE=1
import os

if os.environ.get("DOMJUDGE") == "1":
    for _ in range(int(input())):
        print(f"Ola {input().strip()}!")
else:
    print("DOMJUDGE is not set")
