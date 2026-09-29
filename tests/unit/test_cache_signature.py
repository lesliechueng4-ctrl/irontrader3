"""
Unit tests for CacheManager HMAC-SHA256 signature verification & RCE protection
"""

import hashlib
import hmac
import os
import pickle
import tempfile
import time
from pathlib import Path

from cache_manager import CacheManager


def test_cache_set_and_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CacheManager(cache_dir=tmpdir, cleanup_legacy=False)
        test_data = {"key": "value", "list": [1, 2, 3]}
        cm.set("test_key", test_data)

        # File should exist and have ITCS magic header
        cache_file = Path(tmpdir) / "test_key.pkl"
        assert cache_file.exists()
        raw = cache_file.read_bytes()
        assert raw.startswith(b"ITCS\x01")
        assert len(raw) >= 37

        # Reading back should match
        result = cm.get("test_key")
        assert result == test_data


def test_cache_tampered_file_rejected_without_deserialization():
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CacheManager(cache_dir=tmpdir, cleanup_legacy=False)
        cm.set("tamper_key", {"safe": "data"})

        cache_file = Path(tmpdir) / "tamper_key.pkl"
        raw = bytearray(cache_file.read_bytes())

        # Tamper with the payload (after header of 37 bytes)
        raw[-1] ^= 0xFF
        cache_file.write_bytes(bytes(raw))

        # Clear memory cache so it reads from disk
        cm.memory_cache.clear()

        # Reading tampered file should fail signature check, return None, and unlink file
        result = cm.get("tamper_key")
        assert result is None
        assert not cache_file.exists()


def test_unsigned_legacy_or_malicious_file_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CacheManager(cache_dir=tmpdir, cleanup_legacy=False)

        # Drop a raw pickle file without ITCS magic header
        malicious_file = Path(tmpdir) / "malicious_key.pkl"
        with open(malicious_file, "wb") as f:
            pickle.dump({"data": "untrusted", "timestamp": time.time()}, f)

        # CacheManager must refuse to deserialize and remove the file
        result = cm.get("malicious_key")
        assert result is None
        assert not malicious_file.exists()


def test_cache_expiration_and_stale():
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CacheManager(cache_dir=tmpdir, cleanup_legacy=False)
        cm.cache_policy["expiring"] = 1  # 1 second TTL

        cm.set("expiring_key", {"status": "ok"})
        assert cm.get("expiring_key") == {"status": "ok"}

        time.sleep(1.1)

        # get() should return None because it's expired
        assert cm.get("expiring_key") is None

        # get_stale() should still return stale data for degradation
        stale = cm.get_stale("expiring_key")
        assert stale is not None
        data, age = stale
        assert data == {"status": "ok"}
        assert age >= 1.0


def test_cache_background_cleaner():
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CacheManager(cache_dir=tmpdir, cleanup_legacy=False)
        cm.start_background_cleaner(interval=1)
        thread = cm._cleaner_thread
        assert thread is not None
        assert thread.is_alive()

        cm.stop_background_cleaner()
        assert not thread.is_alive()
        assert cm._cleaner_thread is None
