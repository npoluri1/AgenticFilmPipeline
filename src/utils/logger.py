import logging
import sys

_handlers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    if name in _handlers:
        return _handlers[name]
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
    _handlers[name] = logger
    return logger
