"""Launch wiring only. Argument parsing and object construction; no process is started,
no audio, no window, no GitHub client. The live loop (C2) is separately scoped and is
not in this file on purpose: an accidental import must not be able to launch anything.

    --participant jarvis-local --peer claude-deploy-local --epoch <uuid> --plane local --root <dir>
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime
from pathlib import Path

from . import handshake, ledger as ledger_mod, outbox as outbox_mod, plane_local, publisher as pub_mod
from . import reader as reader_mod, state as state_mod, storage


class WallClock:
    def iso(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def sleep(self, seconds: float) -> None:
        import time
        time.sleep(seconds)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jarvis-comm", description="JARVIS-COMM-01 wiring (no live loop in C1)")
    p.add_argument("--participant", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--session", default=None, help="session id; default: a fresh UUID")
    p.add_argument("--epoch", default=None, help="session epoch; default: a fresh UUID minted at launch")
    p.add_argument("--plane", choices=("local", "github"), default="local")
    p.add_argument("--root", required=True, help="directory for spool, outbox and ledger")
    p.add_argument("--owner", default="Krish")
    p.add_argument("--grant-id", default="5825532363")
    p.add_argument("--grant-revision", type=int, default=1)
    ns = p.parse_args(argv)
    ns.session = ns.session or str(uuid.uuid4())
    ns.epoch = ns.epoch or str(uuid.uuid4())
    return ns


def build(ns: argparse.Namespace, *, speaker, display, store=None, clock=None, github_client=None) -> state_mod.Comm:
    root = Path(ns.root)
    clock = clock or WallClock()
    if ns.plane == "local":
        plane = plane_local.LocalSpoolPlane(root / "spool.md")
    else:
        if github_client is None:
            raise RuntimeError("github plane needs an injected client; none is constructed here (C1: no live transport)")
        from . import plane_github
        plane = plane_github.GitHubPlane(github_client, path="coordination/cloud-claude-coordination.md")
    ob = outbox_mod.Outbox(root / "outbox")
    lg = ledger_mod.Ledger(root / "ledger.json")
    pub = pub_mod.Publisher(plane, ob, lg, sleep=clock.sleep, clock=clock)
    rd = reader_mod.Reader(plane, lg, self_id=ns.participant, clock=clock)
    rel = handshake.Relationship(self_id=ns.participant, self_session=ns.session, self_epoch=ns.epoch, peer_id=ns.peer)
    return state_mod.Comm(relationship=rel, publisher=pub, reader=rd, store=store if store is not None else storage.NoopStore(),
                          speaker=speaker, display=display, clock=clock, owner=ns.owner, grant_id=ns.grant_id,
                          grant_revision=ns.grant_revision)
