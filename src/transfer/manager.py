"""
Transfer manager — priority queue with retry logic.

Manages outbound file transfers: queuing, worker thread, exponential backoff.
"""

import heapq
import threading
import time
from pathlib import Path
from queue import PriorityQueue, Empty
from typing import Callable

from kivy.logger import Logger

from transfer.container import FileContainer
from transfer.protocol import TransferProtocol
from utils.config import Config


class TransferItem:
    """A single queued transfer."""

    def __init__(self, file_path: str | Path, target_ip: str, target_port: int, priority: int = 2):
        self.file_path = Path(file_path)
        self.target_ip = target_ip
        self.target_port = target_port
        self.priority = priority
        self.retry_count = 0
        self.next_retry_time: float = 0
        self.container: FileContainer | None = None

    def __lt__(self, other: "TransferItem"):
        """PriorityQueue comparison — lower number = higher priority."""
        return self.priority < other.priority


class TransferManager:
    """Coordinates the protocol server and the outbound send queue."""

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        self._protocol = TransferProtocol(self._config)
        self._queue: PriorityQueue[TransferItem] = PriorityQueue()
        self._running = False
        self._worker: threading.Thread | None = None

        # Retry heap: (next_retry_time, tiebreaker, item)
        self._retry_heap: list[tuple[float, int, TransferItem]] = []
        self._retry_counter: int = 0

        # Expose protocol callbacks
        self.on_file_received = None  # set by app
        self.on_file_sent: Callable[[str, str], None] | None = None  # set by app
        self.on_file_offer: Callable[[str, str, int], None] | None = None  # set by app

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the protocol server and the send worker."""
        if self._running:
            return

        # Wire callbacks
        if self.on_file_received:
            self._protocol.on_file_received = self.on_file_received
        if self.on_file_offer:
            self._protocol.on_file_offer = self.on_file_offer

        self._protocol.start_server()
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        Logger.info("Proximity: Transfer manager started")

    def stop(self):
        """Shut everything down."""
        self._running = False
        self._protocol.stop_server()
        if self._worker:
            self._worker.join(timeout=5)
        Logger.info("Proximity: Transfer manager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def queue_file(self, file_path: str | Path, target_ip: str, target_port: int | None = None) -> bool:
        """Add a file to the send queue.

        Priority is auto-assigned by file size:
            1 = small  (<100 KB)
            2 = medium (<10 MB)
            3 = large  (≥10 MB)
        """
        path = Path(file_path)
        if not path.exists():
            Logger.error(f"Proximity: File not found: {path}")
            return False

        size = path.stat().st_size
        if size < 100 * 1024:
            priority = 1
        elif size < 10 * 1024 * 1024:
            priority = 2
        else:
            priority = 3

        port = target_port or self._config.get_port()
        item = TransferItem(path, target_ip, port, priority)
        self._queue.put(item)
        Logger.info(f"Proximity: Queued '{path.name}' → {target_ip}:{port} (pri={priority})")
        return True

    def accept_offer(self, offer_id: str):
        """Accept a pending file offer (pass through to protocol)."""
        self._protocol.accept_offer(offer_id)

    def reject_offer(self, offer_id: str):
        """Reject a pending file offer (pass through to protocol)."""
        self._protocol.reject_offer(offer_id)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker_loop(self):
        base_delay = self._config.get_retry_base_delay()
        max_delay = self._config.get_max_retry_delay()
        max_retries = self._config.get_max_retries()

        while self._running:
            # Process due retries first
            now = time.time()
            while self._retry_heap and self._retry_heap[0][0] <= now:
                _, _, item = heapq.heappop(self._retry_heap)
                self._process_item(item, base_delay, max_delay, max_retries)

            # Check main queue
            try:
                item: TransferItem = self._queue.get(timeout=1.0)
            except Empty:
                continue

            self._process_item(item, base_delay, max_delay, max_retries)

    def _process_item(self, item: TransferItem, base_delay: int, max_delay: int, max_retries: int):
        success = self._attempt_send(item)

        if success:
            if self.on_file_sent:
                self.on_file_sent(item.file_path.name, item.target_ip)
            return

        item.retry_count += 1
        if item.retry_count <= max_retries:
            delay = min(base_delay * (2 ** (item.retry_count - 1)), max_delay)
            item.next_retry_time = time.time() + delay
            self._retry_counter += 1
            heapq.heappush(self._retry_heap, (item.next_retry_time, self._retry_counter, item))
            Logger.info(
                f"Proximity: Will retry '{item.file_path.name}' "
                f"(attempt {item.retry_count}/{max_retries}) in {delay}s"
            )
        else:
            Logger.error(f"Proximity: Gave up on '{item.file_path.name}' after {max_retries} retries")

    def _attempt_send(self, item: TransferItem) -> bool:
        try:
            if item.container is None:
                item.container = FileContainer.create_from_file(item.file_path)
            return self._protocol.send_file(item.container, item.target_ip, item.target_port)
        except Exception as e:
            Logger.error(f"Proximity: Transfer attempt failed: {e}")
            return False
