"""Bridge between a blocking generator and an async socket.

The Anthropic SDK's streaming interface is synchronous: iterating it blocks the
calling thread between fragments. Iterating it directly inside the WebSocket
handler would block the event loop for the whole duration of a reply - during
which the server could not read the socket, which is exactly the property
addendum 16 §9 needs preserved, since barge-in means noticing that the user
started talking *while* the assistant is still producing output.

So the generator runs in a worker thread and fragments cross back over an asyncio
queue. Two consequences worth stating, because both are load-bearing:

1. **The worker thread must not touch the database.** sqlite3 connections belong
   to the thread that opened them, and this one is not it. `gateway/conversation.py`
   is arranged so the streaming call takes a plain list and returns text -
   nothing it can persist with.
2. **Exceptions cross the queue as values,** not as a lost traceback in a thread
   nobody is joining. An API error mid-reply has to reach the socket as a
   reportable failure; a thread that died silently would leave the client waiting
   for a `done` that never comes.
3. **The calling context crosses with it.** A new thread starts with an empty
   `contextvars` context, so the request id that `app/model_calls.py` shares
   across every model call serving one user turn would be lost at this
   boundary - and every Gateway call would be logged under an id of its own,
   which is precisely the grouping the call log exists to provide. The worker
   runs inside `copy_context()` for that reason. It is a copy rather than the
   live context: the worker must not be able to mutate what the event loop
   sees.
"""

import asyncio
import contextvars
import threading
from typing import AsyncIterator, Callable, Iterator, TypeVar

T = TypeVar("T")

_END = object()


async def iterate_in_thread(factory: Callable[[], Iterator[T]]) -> AsyncIterator[T]:
    """Run `factory()`'s iterator in a worker thread, yielding its items here.

    Takes a factory rather than an iterator so that constructing it - which for a
    streaming HTTP client means opening the connection - also happens off the
    event loop."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def run() -> None:
        try:
            for item in factory():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's side
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _END)

    context = contextvars.copy_context()
    thread = threading.Thread(target=lambda: context.run(run),
                              name="gateway-model-stream", daemon=True)
    thread.start()

    while True:
        item = await queue.get()
        if item is _END:
            return
        if isinstance(item, BaseException):
            raise item
        yield item
