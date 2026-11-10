import unittest

from fastapi import HTTPException
from backend.browser import BrowserSessions


class BrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.wall, self.mono = 1000, 100
        self.store = BrowserSessions(clock=lambda: self.wall, monotonic=lambda: self.mono,
                                     lifetime=30, idle=10, limit=2)

    def test_session_contains_a_hash_not_an_operator_key_or_cookie_token(self):
        token, csrf = self.store.issue('a' * 64)
        self.assertNotIn(token, self.store.sessions)
        self.assertEqual(self.store.lookup(token).key_hash, 'a' * 64)
        self.assertEqual(self.store.lookup(token).csrf, csrf)

    def test_wall_expiry_detects_a_suspended_host(self):
        token, _ = self.store.issue('a' * 64)
        self.wall += 31
        with self.assertRaises(HTTPException):
            self.store.lookup(token)

    def test_backward_clock_cannot_extend_monotonic_lifetime(self):
        token, _ = self.store.issue('a' * 64)
        self.wall -= 20; self.mono += 31
        with self.assertRaises(HTTPException):
            self.store.lookup(token)

    def test_idle_session_expires(self):
        token, _ = self.store.issue('a' * 64)
        self.wall += 11; self.mono += 11
        with self.assertRaises(HTTPException):
            self.store.lookup(token)

    def test_new_login_invalidates_the_old_cookie(self):
        old, _ = self.store.issue('a' * 64)
        current, _ = self.store.issue('a' * 64, old)
        with self.assertRaises(HTTPException):
            self.store.lookup(old)
        self.assertEqual(self.store.lookup(current).key_hash, 'a' * 64)

    def test_session_capacity_is_bounded(self):
        old, _ = self.store.issue('a' * 64)
        self.store.issue('b' * 64); self.store.issue('c' * 64)
        self.assertEqual(len(self.store.sessions), 2)
        with self.assertRaises(HTTPException):
            self.store.lookup(old)

    def test_signin_throttle_expires_and_is_memory_bounded(self):
        for _ in range(10):
            self.store.throttle('local')
        with self.assertRaises(HTTPException) as error:
            self.store.throttle('local')
        self.assertEqual(error.exception.status_code, 429)
        self.mono += 61
        self.store.throttle('local')
        for index in range(600):
            self.store.throttle(str(index))
        self.assertLessEqual(len(self.store.attempts), 512)
