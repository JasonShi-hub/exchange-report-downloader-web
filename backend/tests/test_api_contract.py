import os
import unittest


try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "fastapi 未安装，跳过 API 合约测试")
class ApiContractTests(unittest.TestCase):
    def setUp(self):
        os.environ["ACCESS_PASSWORD"] = "demo-password"
        os.environ["TOKEN_SECRET"] = "demo-secret"
        from app.main import app

        self.client = TestClient(app)

    def test_login_requires_correct_password(self):
        response = self.client.post("/api/auth/login", json={"password": "bad"})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()

