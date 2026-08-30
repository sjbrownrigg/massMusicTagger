"""One global cap on CPU-heavy external work.

Workers and CPU concurrency are different concerns, and sizing them together
oversubscribes a modest host badly.

Workers exist to overlap *waiting*. Tagging is dominated by the share: on the
development machine an album read from the NAS took 33.0s against 19.1s of
ReplayGain scanning, and the container sat at 1.5% CPU throughout. Raising
``batch.workers`` is how that wait gets overlapped, so it wants to be high.

The CPU is a separate and much smaller resource, shared by every external
decoder the tagger runs -- ``r128gain``, ``shntool`` and ``flac`` for CUE
splitting, ``ffmpeg`` for transcoding, ``fpcalc`` for fingerprinting. Before
this module each worker started its own, and ``r128gain`` was given no
``-c`` so it defaulted to ``os.cpu_count()``: concurrent decodes were
``workers x cpu_count``. At ``workers: 4`` on a four-core mini-PC that is 32
decode threads on four cores, which is thrash rather than throughput.

Measured on 12 FLAC / 345 MB, on local disk so the share could not mask it,
``r128gain`` saturates at two threads -- 35.1s, 19.1s, 20.1s, 20.6s at
``-c 1/2/4/8``. Everything above two was already pure contention.

So this is the second dial. ``batch.cpu_jobs`` bounds how many CPU-heavy
subprocesses run at once, regardless of how many workers are waiting on the
network. The effective ceiling on decode threads is ``cpu_jobs`` times
``replaygain.thread_count`` rather than ``workers`` times ``cpu_count``.

Hold a slot only around the subprocess call itself, never around a caller
that will acquire one again -- the semaphore is not reentrant, and nesting
two acquisitions in one thread with ``cpu_jobs: 1`` deadlocks.
"""

import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DEFAULT_JOBS = 1

_lock = threading.Lock()
_semaphore = threading.BoundedSemaphore(DEFAULT_JOBS)
_jobs = DEFAULT_JOBS


def configure(jobs):
    """Size the pool. Call once, before any worker starts.

    Reconfiguring while slots are held would corrupt the count, so this
    replaces the semaphore wholesale and is only safe at startup.
    """
    global _semaphore, _jobs

    try:
        jobs = int(jobs)
    except (TypeError, ValueError):
        logger.warning('cpu_jobs: %r is not a number -- using %d',
                       jobs, DEFAULT_JOBS)
        jobs = DEFAULT_JOBS

    if jobs < 1:
        logger.warning('cpu_jobs: %d is below 1 -- using 1', jobs)
        jobs = 1

    with _lock:
        _semaphore = threading.BoundedSemaphore(jobs)
        _jobs = jobs

    logger.debug('CPU-heavy work limited to %d concurrent job(s)', jobs)


def jobs():
    """The configured limit."""
    return _jobs


@contextmanager
def slot(what='CPU work'):
    """Hold one of the CPU slots for the duration of the block."""
    # Read once: configure() rebinds the name, and a waiter must release the
    # same object it acquired.
    with _lock:
        sem = _semaphore

    acquired = sem.acquire(blocking=False)
    if not acquired:
        logger.debug('Waiting for a CPU slot before %s', what)
        sem.acquire()
    try:
        yield
    finally:
        sem.release()
