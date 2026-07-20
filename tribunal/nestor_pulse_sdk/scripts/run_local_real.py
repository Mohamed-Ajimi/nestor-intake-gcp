"""
Launch the REAL Nestor Pulse SDK server for local clean-room testing.

WHY a launcher (not plain `uvicorn ...`): on Windows the default asyncio loop
is the ProactorEventLoop, which asyncpg cannot use -- a DB query raises
NotImplementedError (from loop.add_reader). uvicorn creates its loop via
asyncio.run BEFORE importing the app, so setting the policy inside server.py is
too late. This launcher sets the WindowsSelectorEventLoopPolicy FIRST, then
hands off to uvicorn. On non-Windows it's a thin passthrough.

Usage (DATABASE_URL + LOCAL_DEV_AUTH come from the environment):
    $env:DATABASE_URL = "postgresql+asyncpg://postgres@localhost:5433/nestor"
    $env:LOCAL_DEV_AUTH = "1"
    .venv\Scripts\python.exe -m nestor_pulse_sdk.scripts.run_local_real --port 8083
"""
from __future__ import annotations

import argparse
import asyncio
import sys

if sys.platform == "win32":
    # MUST run before uvicorn creates its event loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402  -- imported after the policy is set


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real Nestor Pulse SDK server (local).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "nestor_pulse_sdk.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="asyncio",  # never uvloop; pairs with the Selector policy above
    )


if __name__ == "__main__":
    main()
