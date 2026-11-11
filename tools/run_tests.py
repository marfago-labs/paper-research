#!/usr/bin/env python3
"""Run one unittest file and succeed only if tests really ran and all passed.

Mutation testing needs this: a mutant that makes a script exit while it is imported would end the
test process with status 0 before any test runs, and a plain exit code would count that as a pass.
Usage: python tools/run_tests.py skills/init/scripts/test_init.py
"""

import re
import subprocess
import sys


def main(argv):
    if len(argv) != 1:
        print("usage: run_tests.py <test file>", file=sys.stderr)
        return 2
    result = subprocess.run([sys.executable, "-B", argv[0]], capture_output=True, text=True)
    output = result.stderr + result.stdout
    ran = re.search(r"^Ran ([1-9]\d*) tests? in", output, re.M)
    if result.returncode == 0 and ran and re.search(r"^OK\b", output, re.M):
        return 0
    sys.stderr.write(output[-2000:])
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
