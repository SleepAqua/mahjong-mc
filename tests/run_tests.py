"""Run the test suite: python3 -m unittest discover -s tests -v (from project root)."""

import subprocess
import sys

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "unittest", "discover",
                              "-s", "tests", "-v"]))
