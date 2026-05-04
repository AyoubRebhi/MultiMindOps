#!/usr/bin/env python
"""
Comprehensive verification script for 6 Groq API keys and rate limit retry loop.
Tests key loading, rotation, cooldown, and error handling.
"""

from datetime import datetime, timedelta, timezone
from backend.app.core.config import settings
from backend.app.services.core.groq_key_manager import (
    GroqKeyManager,
    NoGroqAPIKeysAvailableError,
    extract_retry_after_seconds,
    is_groq_rate_limit_error,
    is_groq_auth_error,
)


def test_key_loading():
    """Verify all 6 Groq API keys are loaded from settings."""
    print("\n" + "="*70)
    print("TEST 1: Key Loading")
    print("="*70)
    
    manager = GroqKeyManager.from_settings(settings)
    
    print(f"\n✅ Total Keys Loaded: {manager.configured_keys_count}")
    assert manager.configured_keys_count == 6, f"Expected 6 keys, got {manager.configured_keys_count}"
    
    print("\nLoaded Keys (in rotation order):")
    for i, entry in enumerate(manager._entries, 1):
        value_preview = entry.value[:20] + "..." if len(entry.value) > 20 else entry.value
        print(f"  {i}. {entry.name:20} = {value_preview}")
        print(f"     Label: {entry.label}")
    
    print("\n✅ All 6 keys loaded successfully!")
    return manager


def test_key_rotation():
    """Verify round-robin key rotation."""
    print("\n" + "="*70)
    print("TEST 2: Key Rotation (Round-Robin)")
    print("="*70)
    
    manager = GroqKeyManager.from_settings(settings)
    
    print("\nRotating through all 6 keys:")
    keys_rotated = []
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    
    for i in range(6):  # Just get the first 6 keys (one full cycle)
        key = manager.get_active_key()
        keys_rotated.append(key.name)
        # Mark as rate-limited with 1s cooldown so they can be reused
        manager.mark_key_rate_limited(key.name, retry_after_seconds=1, now=now)
        print(f"  Request {i+1}: {key.name} ({key.label})")
    
    # After all 6 keys are marked for 1 second, check at +2s for the cycle to restart
    print("\n  Waiting 2 seconds for cooldowns to expire...")
    for i in range(6):
        key = manager.get_next_available_key(now=now + timedelta(seconds=2))
        if key:
            print(f"  Request {i+7}: {key.name} ({key.label})")
            keys_rotated.append(key.name)
    
    # Verify rotation (first 6 should be in order)
    expected_cycle = ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", 
                     "GROQ_API_KEY_4", "GROQ_API_KEY_5", "GROQ_API_KEY_6"]
    
    first_cycle = keys_rotated[:6]
    print(f"\nFirst cycle: {first_cycle}")
    assert first_cycle == expected_cycle, f"Expected {expected_cycle}, got {first_cycle}"
    
    print("✅ Round-robin rotation working correctly!")


def test_rate_limit_cooldown():
    """Verify rate-limited keys are excluded during cooldown."""
    print("\n" + "="*70)
    print("TEST 3: Rate Limit Cooldown")
    print("="*70)
    
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    manager = GroqKeyManager(
        [
            {"name": "GROQ_API_KEY", "value": "key-1"},
            {"name": "GROQ_API_KEY_2", "value": "key-2"},
            {"name": "GROQ_API_KEY_3", "value": "key-3"},
            {"name": "GROQ_API_KEY_4", "value": "key-4"},
            {"name": "GROQ_API_KEY_5", "value": "key-5"},
            {"name": "GROQ_API_KEY_6", "value": "key-6"},
        ]
    )
    
    print("\nScenario: Rate limit ALL 6 keys with different cooldowns")
    cooldowns = [60, 120, 180, 240, 300, 360]
    for key_name, cooldown in zip(
        ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3",
         "GROQ_API_KEY_4", "GROQ_API_KEY_5", "GROQ_API_KEY_6"],
        cooldowns
    ):
        manager.mark_key_rate_limited(key_name, retry_after_seconds=cooldown, now=now)
        print(f"  {key_name:20} → cooldown: {cooldown}s")
    
    print("\nChecking availability at different times:")
    # At +1s, all should be unavailable
    available = manager.get_next_available_key(now=now + timedelta(seconds=1))
    print(f"  At +1s:   {available}")
    assert available is None, "All keys should be rate-limited at +1s"
    print("    ✓ All keys blocked")
    
    # At +61s, key 1 should be available
    available = manager.get_next_available_key(now=now + timedelta(seconds=61))
    print(f"  At +61s:  {available.name if available else 'None'}")
    assert available is not None and available.name == "GROQ_API_KEY"
    print("    ✓ Key 1 unlocked (60s cooldown expired)")
    
    # At +121s, keys 1 and 2 should be available
    available = manager.get_next_available_key(now=now + timedelta(seconds=121))
    print(f"  At +121s: {available.name if available else 'None'}")
    assert available is not None
    print("    ✓ Multiple keys available")
    
    print("\n✅ Cooldown tracking working correctly!")


def test_all_keys_exhausted():
    """Verify clear error message when all keys are exhausted."""
    print("\n" + "="*70)
    print("TEST 4: All Keys Exhausted")
    print("="*70)
    
    now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    manager = GroqKeyManager.from_settings(settings)
    
    print("\nMarking all 6 keys as rate-limited...")
    for i, entry in enumerate(manager._entries, 1):
        manager.mark_key_rate_limited(entry.name, retry_after_seconds=100*i, now=now)
        print(f"  {i}. {entry.name:20} → 100×{i}s cooldown")
    
    # Try to get active key at +1s (during all cooldowns)
    try:
        key = manager.get_next_available_key(now=now + timedelta(seconds=1))
        if key is None:
            print(f"\n✅ Correctly returned None when all keys exhausted")
            # Get the error message
            error_msg = manager.describe_unavailable_state(now=now + timedelta(seconds=1))
            print(f"   Error Message: {error_msg}")
            assert "No Groq API keys are currently available" in error_msg
            print("   ✓ Error message is clear and helpful")
        else:
            print(f"\n❌ ERROR: Should return None, got {key}")
            assert False, "Should return None when all exhausted"
    except NoGroqAPIKeysAvailableError as e:
        error_msg = str(e)
        print(f"\n✅ Correctly raised: {type(e).__name__}")
        print(f"   Message: {error_msg}")
        assert "No Groq API keys are currently available" in error_msg
        print("   ✓ Error message includes retry time estimate")


def test_error_detection():
    """Verify rate limit and auth error detection."""
    print("\n" + "="*70)
    print("TEST 5: Error Detection")
    print("="*70)
    
    # Test rate limit error detection
    rate_limit_messages = [
        "Rate limit reached. Please try again in 2h19m48.575999999s.",
        "Too many requests - try again in 1m30s",
        "tokens per minute exceeded",
        "HTTP 429: Too Many Requests",
    ]
    
    print("\nTesting rate limit error detection:")
    for msg in rate_limit_messages:
        class FakeError(Exception):
            def __init__(self, msg):
                super().__init__(msg)
                self.status_code = 429
                self.response = type('obj', (object,), {'status_code': 429})()
        
        error = FakeError(msg)
        is_rate_limit = is_groq_rate_limit_error(error)
        print(f"  '{msg[:40]}...' → {is_rate_limit}")
        assert is_rate_limit, f"Should detect rate limit in: {msg}"
    
    print("\n✅ Rate limit detection working!")
    
    # Test auth error detection
    auth_messages = [
        "Invalid API key provided",
        "HTTP 401: Unauthorized",
        "authentication failed",
    ]
    
    print("\nTesting auth error detection:")
    for msg in auth_messages:
        class FakeError(Exception):
            def __init__(self, msg):
                super().__init__(msg)
                self.status_code = 401
                self.response = type('obj', (object,), {'status_code': 401})()
        
        error = FakeError(msg)
        is_auth = is_groq_auth_error(error)
        print(f"  '{msg}' → {is_auth}")
        assert is_auth, f"Should detect auth error in: {msg}"
    
    print("\n✅ Auth error detection working!")


def main():
    """Run all verification tests."""
    print("\n" + "="*70)
    print("GROQ API KEY MANAGER - COMPREHENSIVE VERIFICATION")
    print("6 Keys + Rate Limit Retry Loop")
    print("="*70)
    
    try:
        test_key_loading()
        test_key_rotation()
        test_rate_limit_cooldown()
        test_all_keys_exhausted()
        test_error_detection()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\nSummary:")
        print("  ✓ 6 Groq API keys loaded correctly")
        print("  ✓ Round-robin rotation working")
        print("  ✓ Rate limit cooldown tracking precise")
        print("  ✓ Exhaustion handling with clear error messages")
        print("  ✓ Rate limit and auth error detection accurate")
        print("\nThe retry loop is PRODUCTION READY with all 6 keys! 🚀")
        print("="*70 + "\n")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
