"""Entry point for Wingman: python -m wingman."""

from __future__ import annotations

import signal
import sys

from wingman.config import load_config
from wingman.scheduler import WingmanScheduler
from wingman.utils.logging_config import setup_logging


def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    scheduler = WingmanScheduler(config)

    def shutdown(signum: int, frame: object) -> None:
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    scheduler.start()


if __name__ == "__main__":
    main()
