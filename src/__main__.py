"""Allow ``python -m src`` to launch the studio CLI."""
from __future__ import annotations

from main import main

if __name__ == "__main__":
    raise SystemExit(main())
