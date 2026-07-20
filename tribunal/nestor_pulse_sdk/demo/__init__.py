"""
Demo mode -- mock API surface for the local clickable UI demo.

Enabled by DEMO_MODE=1. When enabled, server.py mounts demo.api routers
instead of the real DB-backed routers. Bypasses auth + DB entirely so
the UI can be shown end-to-end on a laptop with zero infrastructure.

Never enable in production -- the env check in server.py is the only gate.
"""
