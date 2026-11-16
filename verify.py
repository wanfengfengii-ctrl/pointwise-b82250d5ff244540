"""Chain the original regression with the DESIGN.md observation review.

Runs `python3 checks.py` first (business regression must stay green), then
`python3 review.py DESIGN.md` (replays observations cited in the design doc).
Any failure makes the whole verify fail.
"""
import subprocess
import sys

STEPS = (
    ["python3", "checks.py"],
    ["python3", "review.py", "DESIGN.md"],
)


def main():
    for argv in STEPS:
        print("+ " + " ".join(argv), flush=True)
        result = subprocess.run(argv)
        if result.returncode != 0:
            print("verify failed at: " + " ".join(argv), file=sys.stderr)
            return result.returncode
    print("verify ok: regression + document observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
