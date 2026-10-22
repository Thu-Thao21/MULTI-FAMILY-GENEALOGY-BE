import json
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SPRINT2_DIR = os.path.dirname(CURRENT_DIR)

def get_tc_path():
    candidates = [
        os.path.join(SPRINT2_DIR, 'test_cases', 'classified_test_cases.json'),
        os.path.join(CURRENT_DIR, 'classified_test_cases.json'),
        'classified_test_cases.json'
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(SPRINT2_DIR, 'test_cases', 'classified_test_cases.json')

with open(get_tc_path(), encoding='utf-8') as f:
    tcs = json.load(f)

for tc in tcs:
    print(f"{tc['code']} | {tc['category']} | {tc['feature']} | {tc['type_in_excel']} | {tc['scenario'][:50]} | {tc['expected'][:50]}")
