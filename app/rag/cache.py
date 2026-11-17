"""Small process-local cache shared by retrieval and catalog callers."""

from collections import OrderedDict
from threading import Lock
from time import monotonic


class TTLCache:
    """Thread-safe bounded LRU with fixed, monotonic time-to-live per entry.

    None is reserved for a cache miss. A nonpositive capacity or TTL disables
    storage. Callers own their values and should not mutate cached objects.
    """

    def __init__(self, max_entries: int, ttl_seconds: float):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries = OrderedDict()
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            deadline, value = entry
            if deadline <= monotonic():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key, value):
        if self.max_entries <= 0 or self.ttl_seconds <= 0 or value is None:
            return
        with self._lock:
            now = monotonic()
            expired = [key for key, (deadline, _) in self._entries.items()
                       if deadline <= now]
            for expired_key in expired:
                del self._entries[expired_key]
            self._entries[key] = (now + self.ttl_seconds, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self):
        with self._lock:
            self._entries.clear()
