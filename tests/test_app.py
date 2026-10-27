

import unittest
from unittest.mock import patch
from app import app


class TestDashboard(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    @patch("app.client")
    def test_health_api(self, mock_client):
        mock_client.ping.return_value = True

        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertIn("docker_status", data)
        self.assertIn("monitoring", data)
        self.assertEqual(data["service"],
                         "self-healing-container-management")


if __name__ == "__main__":
    unittest.main()

