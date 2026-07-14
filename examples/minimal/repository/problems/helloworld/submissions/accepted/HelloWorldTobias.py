#!/usr/bin/env python3

case_count = int(input())
for case_number in range(1, case_count + 1):
    name = input().strip()
    print(f"Case #{case_number}: Hello {name}!")
