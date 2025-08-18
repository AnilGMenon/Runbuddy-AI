"""Basic stdout logger configuration for RunBuddy."""

import logging
import sys


def setup_logger(level: str = "INFO") -> logging.Logger:
    """Configure and return a logger for RunBuddy.

    :param level: Logging level as a string (e.g., "DEBUG", "INFO", "WARNING").
    :return: A configured Logger instance named "runbuddy".
    """
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return logging.getLogger("runbuddy")
