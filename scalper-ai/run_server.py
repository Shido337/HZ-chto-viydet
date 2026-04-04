"""Entry point — keeps uvicorn alive with proper signal handling."""
import atexit
import signal
import sys
import traceback

import uvicorn
from loguru import logger


def _on_exit():
    logger.warning("Server process exiting")
    traceback.print_stack()


def _on_signal(signum, frame):
    logger.warning(f"Received signal {signum}")
    traceback.print_stack(frame)
    sys.exit(0)


if __name__ == "__main__":
    atexit.register(_on_exit)
    # Register common termination signals
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (OSError, ValueError):
            pass  # Some signals unavailable on Windows
    try:
        logger.info("Starting uvicorn server")
        uvicorn.run(
            "server.api:app",
            host="0.0.0.0",
            port=8000,
            log_level="info",
        )
        logger.warning("uvicorn.run() returned normally")
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as exc:
        logger.critical(f"Server crashed: {exc}")
        traceback.print_exc()
        sys.exit(1)
