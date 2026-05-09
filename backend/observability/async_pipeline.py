"""
Async ingestion pipeline: queues, workers, batching, backpressure, retry queues.

Design goals:
- Async workers consume ingestion queues
- Batching with size/time triggers
- Backpressure: max queue length, drop or overflow handling
- Retry queue with exponential backoff
- Instrumentation hooks for telemetry_health
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class AsyncIngestionPipeline:
    def __init__(self, worker_fn: Callable[[List[Any]], asyncio.Future],
                 max_queue: int = 10000, batch_size: int = 100, batch_timeout: float = 1.0,
                 retry_backoff_base: float = 0.5, max_retries: int = 5):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        self.retry_queue: asyncio.Queue = asyncio.Queue()
        self.worker_fn = worker_fn
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.retry_backoff_base = retry_backoff_base
        self.max_retries = max_retries
        self._workers: List[asyncio.Task] = []
        self._retry_task: Optional[asyncio.Task] = None
        self.shutdown_event = asyncio.Event()
        self.stats = {
            "ingested": 0,
            "dropped": 0,
            "batches_processed": 0,
            "retry_attempts": 0,
            "retries_failed": 0,
        }

    async def start(self, worker_count: int = 4):
        logger.info("Starting ingestion pipeline with %d workers", worker_count)
        for _ in range(worker_count):
            t = asyncio.create_task(self._worker_loop())
            self._workers.append(t)
        self._retry_task = asyncio.create_task(self._retry_loop())

    async def stop(self):
        logger.info("Stopping ingestion pipeline")
        self.shutdown_event.set()
        for w in self._workers:
            w.cancel()
        if self._retry_task:
            self._retry_task.cancel()
        # Drain queues
        await asyncio.sleep(0)

    async def ingest(self, item: Any) -> bool:
        """Enqueue item for ingestion. Returns True if accepted, False if dropped."""
        try:
            self.queue.put_nowait((item, 0))  # (payload, retry_count)
            return True
        except asyncio.QueueFull:
            # Backpressure policy: drop oldest or newest. Drop newest here.
            self.stats["dropped"] += 1
            logger.warning("Ingestion queue full, dropping item")
            return False

    async def _worker_loop(self):
        try:
            while not self.shutdown_event.is_set():
                batch = []
                start = asyncio.get_event_loop().time()
                while len(batch) < self.batch_size and (asyncio.get_event_loop().time() - start) < self.batch_timeout:
                    try:
                        item, retry_count = await asyncio.wait_for(self.queue.get(), timeout=self.batch_timeout)
                        batch.append((item, retry_count))
                    except asyncio.TimeoutError:
                        break
                    except asyncio.CancelledError:
                        return
                if not batch:
                    continue
                # Extract payloads
                payloads = [it for it, _ in batch]
                try:
                    await self._dispatch(payloads)
                    self.stats["batches_processed"] += 1
                    self.stats["ingested"] += len(payloads)
                except Exception as e:
                    logger.exception("Batch worker failed, scheduling retries: %s", e)
                    # Push to retry queue with retry count increment
                    for _, rc in batch:
                        await self.retry_queue.put((_, rc + 1))
        except asyncio.CancelledError:
            return

    async def _dispatch(self, payloads: List[Any]):
        """Call user-provided worker_fn. Expected to be async function."""
        result = await self.worker_fn(payloads)
        return result

    async def _retry_loop(self):
        try:
            while not self.shutdown_event.is_set():
                try:
                    item, retry_count = await self.retry_queue.get()
                except asyncio.CancelledError:
                    return
                if retry_count > self.max_retries:
                    self.stats["retries_failed"] += 1
                    logger.error("Giving up on item after %d retries", retry_count)
                    continue
                backoff = self.retry_backoff_base * (2 ** (retry_count - 1))
                await asyncio.sleep(backoff)
                try:
                    await self.queue.put((item, retry_count))
                    self.stats["retry_attempts"] += 1
                except asyncio.QueueFull:
                    # If queue full, push back to retry
                    await self.retry_queue.put((item, retry_count + 1))
        except asyncio.CancelledError:
            return


# Convenience: simple runner
async def simple_worker_fn(payloads: List[Any]):
    # placeholder processing
    await asyncio.sleep(0)  # yield
    return True


if __name__ == "__main__":
    async def main():
        p = AsyncIngestionPipeline(simple_worker_fn, max_queue=1000, batch_size=50)
        await p.start(worker_count=2)
        for i in range(200):
            await p.ingest({"i": i})
        await asyncio.sleep(1)
        await p.stop()

    asyncio.run(main())
