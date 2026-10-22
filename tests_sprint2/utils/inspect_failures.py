import json
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SPRINT2_DIR = os.path.dirname(CURRENT_DIR)

def get_results_path():
    candidates = [
        os.path.join(SPRINT2_DIR, 'reports', 'sprint2_test_results.json'),
        os.path.join(CURRENT_DIR, 'sprint2_test_results.json'),
        'sprint2_test_results.json'
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(SPRINT2_DIR, 'reports', 'sprint2_test_results.json')

with open(get_results_path(), encoding='utf-8') as f:
    results = json.load(f)

failed = [r for r in results if r['status'] == 'FAILED']
print(f"Total Failed TCs: {len(failed)}")
for f_tc in failed:
    print(f"[{f_tc['code']}] - {f_tc['category']} ({f_tc['classification']})")
    print(f"   Chức Năng: {f_tc.get('feature', '')}")
    print(f"   Kịch Bản : {f_tc['scenario']}")
    print(f"   Kỳ Vọng  : {f_tc['expected']}")
    print(f"   Thực Tế  : {f_tc['actual']}")
    print("-" * 70)
