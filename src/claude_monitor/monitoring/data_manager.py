"""Unified data management for monitoring - combines caching and fetching."""

import logging
import time
from datetime import datetime, timedelta
from datetime import timezone as tz
from typing import Any, Dict, List, Optional, Set

from claude_monitor.core.models import CostMode
from claude_monitor.core.pricing import PricingCalculator
from claude_monitor.data.analysis import analyze_usage
from claude_monitor.data.reader import FileTracker, _find_jsonl_files
from claude_monitor.error_handling import report_error
from claude_monitor.utils.time_utils import TimezoneHandler

logger = logging.getLogger(__name__)


def _parse_raw_timestamp(raw: Dict[str, Any]) -> "datetime":
    """Parse timestamp from raw dict for window filtering; returns epoch on failure."""
    from datetime import timezone as _tz
    from claude_monitor.utils.time_utils import TimezoneHandler
    ts = raw.get("timestamp")
    if ts:
        try:
            result = TimezoneHandler().parse_timestamp(ts)
            if result:
                return result
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=_tz.utc)


class DataManager:
    """Manages data fetching and caching for monitoring."""

    def __init__(
        self,
        cache_ttl: int = 30,
        hours_back: int = 192,
        data_path: Optional[str] = None,
        data_paths: Optional[List[str]] = None,
    ) -> None:
        """Initialize data manager with cache and fetch settings.

        Args:
            cache_ttl: Cache time-to-live in seconds
            hours_back: Hours of historical data to fetch
            data_path: Path to data directory
            data_paths: List of paths to scan (overrides data_path)
        """
        self.cache_ttl: int = cache_ttl
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: Optional[float] = None

        self.hours_back: int = hours_back
        self.data_path: Optional[str] = data_path
        self.data_paths: Optional[List[str]] = data_paths
        self._last_error: Optional[str] = None
        self._last_successful_fetch: Optional[float] = None

        # Incremental parsing state
        self._file_tracker = FileTracker()
        self._all_entries: List[Any] = []
        self._all_raw_entries: List[Dict[str, Any]] = []
        self._processed_hashes: Set[str] = set()
        self._tz_handler = TimezoneHandler()
        self._pricing = PricingCalculator()

    def _fetch_incremental(self) -> Optional[Dict[str, Any]]:
        """Fetch only new JSONL entries, merge with in-memory cache, run analysis."""
        from pathlib import Path

        if self.data_paths:
            scan_dirs = [Path(p).expanduser() for p in self.data_paths]
        else:
            scan_dirs = [Path(self.data_path if self.data_path else "~/.claude/projects").expanduser()]

        seen: set = set()
        jsonl_files = []
        for scan_dir in scan_dirs:
            for f in _find_jsonl_files(scan_dir):
                resolved = f.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    jsonl_files.append(resolved)

        added = 0
        for file_path in jsonl_files:
            new_entries, new_raw = self._file_tracker.read_new_entries(
                file_path,
                CostMode.AUTO,
                self._tz_handler,
                self._pricing,
                self._processed_hashes,
            )
            if new_entries:
                self._all_entries.extend(new_entries)
                added += len(new_entries)
            if new_raw:
                self._all_raw_entries.extend(new_raw)

        if added:
            self._all_entries.sort(key=lambda e: e.timestamp)
            logger.debug("Incremental: +%d entries (total %d)", added, len(self._all_entries))

        if self.hours_back and self._all_entries:
            cutoff = datetime.now(tz.utc) - timedelta(hours=self.hours_back)
            entries_window = [e for e in self._all_entries if e.timestamp >= cutoff]
            raw_window = [r for r in self._all_raw_entries if _parse_raw_timestamp(r) >= cutoff]
        else:
            entries_window = self._all_entries
            raw_window = self._all_raw_entries

        self._file_tracker.save_index()

        return analyze_usage(
            hours_back=self.hours_back,
            quick_start=False,
            use_cache=False,
            data_path=self.data_path,
            data_paths=self.data_paths,
            preloaded_entries=entries_window,
            preloaded_raw_entries=raw_window,
        )

    def get_data(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Get monitoring data with caching and error handling.

        Args:
            force_refresh: Force refresh ignoring cache

        Returns:
            Usage data dictionary or None if fetch fails
        """
        if not force_refresh and self._is_cache_valid():
            cache_age: float = time.time() - self._cache_timestamp  # type: ignore
            logger.debug(f"Using cached data (age: {cache_age:.1f}s)")
            return self._cache

        max_retries: int = 3
        for attempt in range(max_retries):
            try:
                logger.debug(
                    f"Fetching fresh usage data (attempt {attempt + 1}/{max_retries})"
                )
                data: Optional[Dict[str, Any]] = self._fetch_incremental()

                if data is not None:
                    self._set_cache(data)
                    self._last_successful_fetch = time.time()
                    self._last_error = None
                    return data

                logger.warning("No data returned from analyze_usage")
                break

            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.exception(f"Data access error (attempt {attempt + 1}): {e}")
                self._last_error = str(e)
                report_error(
                    exception=e, component="data_manager", context_name="access_error"
                )
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (2**attempt))
                    continue

            except (ValueError, TypeError, KeyError) as e:
                logger.exception(f"Data format error: {e}")
                self._last_error = str(e)
                report_error(
                    exception=e, component="data_manager", context_name="format_error"
                )
                break

            except Exception as e:
                logger.exception(f"Unexpected error (attempt {attempt + 1}): {e}")
                self._last_error = str(e)
                report_error(
                    exception=e,
                    component="data_manager",
                    context_name="unexpected_error",
                )
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (2**attempt))
                    continue
                break

        if self._is_cache_valid():
            logger.info("Using cached data due to fetch error")
            return self._cache

        logger.error("Failed to get usage data - no cache fallback available")
        return None

    def invalidate_cache(self) -> None:
        """Invalidate the cache."""
        self._cache = None
        self._cache_timestamp = None
        logger.debug("Cache invalidated")

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if self._cache is None or self._cache_timestamp is None:
            return False

        cache_age = time.time() - self._cache_timestamp
        return cache_age <= self.cache_ttl

    def _set_cache(self, data: Dict[str, Any]) -> None:
        """Set cache with current timestamp."""
        self._cache = data
        self._cache_timestamp = time.time()

    @property
    def cache_age(self) -> float:
        """Get age of cached data in seconds."""
        if self._cache_timestamp is None:
            return float("inf")
        return time.time() - self._cache_timestamp

    @property
    def last_error(self) -> Optional[str]:
        """Get last error message."""
        return self._last_error

    @property
    def last_successful_fetch_time(self) -> Optional[float]:
        """Get timestamp of last successful fetch."""
        return self._last_successful_fetch
