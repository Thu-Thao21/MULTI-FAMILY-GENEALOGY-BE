import sys
import subprocess
import os

def main():
    print("=" * 60)
    print(" 🚀 RUNNING MULTI-FAMILY GENEALOGY E2E TESTS (SELENIUM)")
    print("=" * 60)

    target = "tests_e2e/"
    if "--sprint3" in sys.argv:
        target = "tests_e2e/test_sprint3_cases.py"
        print("🎯 Target: Sprint 3 Automated Cases (SEL3-001 -> SEL3-016)")
    else:
        print("🎯 Target: All E2E Suites (Sprint 1, 2, 3)")

    args = ["pytest", target, "-v", "--html=tests_e2e/report.html", "--self-contained-html"]
    
    # Check if user requested visible browser window
    if "--headed" in sys.argv:
        args.append("--headed")
        print("📌 Mode: HEADED (Visible Chrome browser window)")
    else:
        print("📌 Mode: HEADLESS (Background execution, fast)")
        print("💡 Hint: Add `--headed` to watch Chrome open!")

    print(f"Executing: {' '.join(args)}\n")
    result = subprocess.run(args)

    report_path = os.path.abspath("tests_e2e/report.html")
    print("\n" + "=" * 60)
    if result.returncode == 0:
        print("✅ ALL TESTS PASSED SUCCESSFULLY!")
    else:
        print("❌ SOME TESTS FAILED. Check console output or report.")
    print(f"📊 Detailed HTML Report: file:///{report_path.replace(os.sep, '/')}")
    print("=" * 60)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
