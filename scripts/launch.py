"""Entry point for the packaged app (PyInstaller needs a script, not `-m roverlay`)."""
import sys

from roverlay.__main__ import main

sys.exit(main())
