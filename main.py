"""Entry point. Run `python main.py` (or the run.bat / run.command launchers).

The implementation lives in the `iracing_analytics` package; this just invokes
its CLI so the command stays simple.
"""
from iracing_analytics.cli import main

if __name__ == "__main__":
    main()
