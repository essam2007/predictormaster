"""Exponential-histogram bucket structure for ADWIN (Bifet & Gavaldà 2007).

The window is represented as a sequence of *rows*; each row holds at most M
buckets of capacity 2^row. A new sample is inserted as a capacity-1 bucket at
row 0; whenever a row overflows, its two oldest buckets are merged into a
single bucket promoted to the next row. This keeps the total bucket count
O(log n) and amortised update cost O(log n).

We expose just the operations ADWIN needs:

* ``add(x)``         — append a sample.
* ``drop_left(k)``   — drop the k oldest samples (used after a cut).
* ``cuts()``         — iterate (n0, n1, mean0, mean1) pairs to test.
* ``total / variance / size`` — running summary statistics.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    capacity: int  # number of underlying samples
    total: float   # sum of those samples
    sq: float      # sum of squares (for variance)


@dataclass
class BucketRows:
    max_buckets_per_row: int = 5
    rows: list[deque[_Bucket]] = field(default_factory=list)
    size: int = 0
    total: float = 0.0
    sq: float = 0.0

    def _ensure_row(self, i: int) -> None:
        while len(self.rows) <= i:
            self.rows.append(deque())

    def _compress(self, i: int) -> None:
        # Merge oldest two buckets of row i into one bucket of row i+1.
        self._ensure_row(i + 1)
        while len(self.rows[i]) > self.max_buckets_per_row:
            b0 = self.rows[i].popleft()
            b1 = self.rows[i].popleft()
            merged = _Bucket(capacity=b0.capacity + b1.capacity, total=b0.total + b1.total, sq=b0.sq + b1.sq)
            self.rows[i + 1].append(merged)
            if len(self.rows[i + 1]) > self.max_buckets_per_row:
                self._compress(i + 1)

    def add(self, x: float) -> None:
        self._ensure_row(0)
        self.rows[0].append(_Bucket(capacity=1, total=x, sq=x * x))
        self.size += 1
        self.total += x
        self.sq += x * x
        if len(self.rows[0]) > self.max_buckets_per_row:
            self._compress(0)

    def drop_left(self, k: int) -> None:
        """Drop the k oldest underlying samples by removing whole buckets
        from the left until at least k samples have been removed.
        """
        remaining = k
        while remaining > 0 and self.rows:
            row = self._oldest_nonempty_row()
            if row is None:
                break
            b = row.popleft()
            self.size -= b.capacity
            self.total -= b.total
            self.sq -= b.sq
            remaining -= b.capacity

    def _oldest_nonempty_row(self) -> deque[_Bucket] | None:
        # Buckets at higher rows hold older samples — they were promoted from
        # lower rows during compression. Drop from the highest non-empty row.
        for row in reversed(self.rows):
            if row:
                return row
        return None

    def variance(self) -> float:
        if self.size <= 1:
            return 0.0
        mean = self.total / self.size
        return max(self.sq / self.size - mean * mean, 0.0)

    def cuts(self):
        """Yield (n0, n1, mean0, mean1) at each whole-bucket split position.

        Splits respect bucket boundaries (no fractional bucket cuts), which
        is what the ADWIN epsilon-cut formula expects.
        """
        # Walk buckets in oldest -> newest order: highest row first, oldest
        # bucket within each row first.
        ordered: list[_Bucket] = []
        for row in reversed(self.rows):
            ordered.extend(row)
        cum_n = 0
        cum_t = 0.0
        for k in range(len(ordered) - 1):
            cum_n += ordered[k].capacity
            cum_t += ordered[k].total
            n0 = cum_n
            n1 = self.size - cum_n
            if n0 == 0 or n1 == 0:
                continue
            mean0 = cum_t / n0
            mean1 = (self.total - cum_t) / n1
            yield n0, n1, mean0, mean1
