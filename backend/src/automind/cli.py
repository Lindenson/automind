"""`python -m automind.cli <command>`: the stable command line (see automind/delivery/cli)."""

import sys

from automind.delivery.cli import main

if __name__ == "__main__":
    sys.exit(main())
