"""So `python -m app` works as well as `python -m app.cli`."""

import sys

from app.cli import main

sys.exit(main())
