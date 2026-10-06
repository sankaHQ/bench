from pathlib import Path

from sanka_bench.go_driver import main

if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parent))
