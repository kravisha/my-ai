"""JARVIS-COMM-01: Claude-Jarvis communication over the R2 message plane.

Owner: Claude Deploy (hub 5825532363). C1 scope: fakes only; nothing here opens a
network connection, starts a process, plays audio or shows a window. The GitHub
plane takes an injected client; the local spool plane is the same-machine adapter.
"""

__all__ = ["canon", "entry", "plane", "plane_local", "plane_github", "outbox", "ledger", "publisher",
           "reader", "handshake", "status", "storage", "state", "launch"]
