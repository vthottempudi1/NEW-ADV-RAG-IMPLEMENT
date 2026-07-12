"""Deprecated CLI bridge; use ``python -m evals.runners.run``."""
from evals.runners.run import *  # noqa: F403
from evals.runners.run import main

if __name__ == "__main__":
    main()
