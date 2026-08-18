"""The blocking-generator-to-async-socket bridge.

Worth testing on its own rather than only through the WebSocket, because the
property that matters - that the event loop is free while the model is producing
tokens - is invisible in a passing end-to-end test and is the reason this module
exists at all.
"""

import asyncio
import threading
import time

import pytest

from gateway.streaming import iterate_in_thread


@pytest.mark.anyio
async def test_fragments_arrive_in_order():
    fragments = [item async for item in iterate_in_thread(lambda: iter(["a", "b", "c"]))]

    assert fragments == ["a", "b", "c"]


@pytest.mark.anyio
async def test_an_empty_stream_ends_cleanly():
    assert [item async for item in iterate_in_thread(lambda: iter([]))] == []


@pytest.mark.anyio
async def test_the_generator_runs_off_the_event_loop_thread():
    """The whole purpose. If this ran inline, a reply would block the socket for
    its entire duration - and barge-in (addendum 16 §9) means noticing that the
    user started talking *while* the assistant is still producing output."""
    caller_thread = threading.get_ident()

    def where_am_i():
        yield threading.get_ident()

    [producer_thread] = [item async for item in iterate_in_thread(where_am_i)]

    assert producer_thread != caller_thread


@pytest.mark.anyio
async def test_the_loop_keeps_running_while_the_generator_blocks():
    """Stated as a behaviour rather than an implementation detail: other tasks
    must make progress while a fragment is being waited for."""
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.005)

    def slow():
        time.sleep(0.15)
        yield "done"

    task = asyncio.ensure_future(ticker())
    try:
        assert [item async for item in iterate_in_thread(slow)] == ["done"]
    finally:
        task.cancel()

    assert ticks > 1, "the event loop was blocked while the generator slept"


@pytest.mark.anyio
async def test_an_exception_reaches_the_consumer():
    """A model error mid-reply has to become something the socket can report. A
    thread that died quietly would leave the client waiting for a `done` frame
    that never comes."""

    def explodes():
        yield "partial"
        raise RuntimeError("upstream refused")

    received = []
    with pytest.raises(RuntimeError, match="upstream refused"):
        async for item in iterate_in_thread(explodes):
            received.append(item)

    assert received == ["partial"], "fragments before the failure are still delivered"


@pytest.mark.anyio
async def test_a_failure_while_constructing_the_iterator_also_propagates():
    """Opening the stream is itself a network call, so it can fail before a
    single fragment exists - and that failure must not be silently empty."""

    def cannot_start():
        raise ConnectionError("no route to model")

    with pytest.raises(ConnectionError):
        async for _ in iterate_in_thread(cannot_start):
            pass
