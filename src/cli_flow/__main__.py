"""Package entry point.

Allows running as:
  python -m cli_flow
  cli-flow   (installed script via pyproject.toml)
"""

import sys
from cli_flow.cli import main

if __name__ == "__main__":
    sys.exit(main())
