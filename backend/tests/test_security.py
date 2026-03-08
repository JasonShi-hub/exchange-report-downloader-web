import time
import unittest

from app.security import TokenError, issue_token, verify_token


class SecurityTests(unittest.TestCase):
    def test_issue_and_verify_token(self):
        token, expires_at = issue_token("secret", "shared-access", 60)
        payload = verify_token("secret", token)
        self.assertEqual(payload["sub"], "shared-access")
        self.assertGreaterEqual(payload["exp"], expires_at - 1)

    def test_expired_token_raises(self):
        token, _ = issue_token("secret", "shared-access", -1)
        time.sleep(1)
        with self.assertRaises(TokenError):
            verify_token("secret", token)


if __name__ == "__main__":
    unittest.main()

