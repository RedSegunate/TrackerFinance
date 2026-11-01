import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import main


class MiniAppApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = main.DB_PATH
        self.original_allowed_users = main.ALLOWED_USERS
        main.DB_PATH = str(Path(self.temp_dir.name) / "test.db")
        main.ALLOWED_USERS = set()
        main.init_db()
        self.user_id = 918273645
        self.token = main.ensure_user(self.user_id)
        self.auth = {"Authorization": f"Bearer {self.token}"}
        self.client = TestClient(TestServer(main.create_web_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        main.DB_PATH = self.original_db_path
        main.ALLOWED_USERS = self.original_allowed_users
        self.temp_dir.cleanup()

    async def test_app_page_and_authentication(self):
        page = await self.client.get("/app")
        script = await self.client.get("/assets/app.js")
        unauthorized = await self.client.get("/api/app/me")

        self.assertEqual(page.status, 200)
        self.assertIn('data-s="analytics"', await page.text())
        self.assertEqual(script.status, 200)
        self.assertIn("loadAnalytics", await script.text())
        self.assertEqual(unauthorized.status, 401)

    async def test_transaction_edit_delete_and_restore(self):
        added = await self.client.post(
            "/api/app/add",
            headers=self.auth,
            json={"kind": "expense", "amount": "1250", "category": "Продукты", "note": "Покупки"},
        )
        self.assertEqual(added.status, 200)

        history = await self.client.get("/api/app/transactions?q=Покупки", headers=self.auth)
        history_data = await history.json()
        self.assertEqual(len(history_data["items"]), 1)
        tx_id = history_data["items"][0]["id"]

        edited = await self.client.patch(
            f"/api/app/transactions/{tx_id}",
            headers=self.auth,
            json={"category": "Кафе и рестораны", "amount": 1300, "note": "Обед"},
        )
        self.assertEqual(edited.status, 200)
        self.assertEqual(main.load_user_rules(self.user_id).get("обед"), "Кафе и рестораны")

        deleted = await self.client.delete(f"/api/app/transactions/{tx_id}", headers=self.auth)
        self.assertEqual(deleted.status, 200)
        deleted_data = await deleted.json()
        restored = await self.client.post(
            f"/api/app/transactions/{deleted_data['undo_id']}/restore",
            headers=self.auth,
        )
        self.assertEqual(restored.status, 200)

        stats = await self.client.get("/api/app/stats?period=year", headers=self.auth)
        stats_data = await stats.json()
        self.assertEqual(stats_data["expense"], 1300)
        self.assertTrue(stats_data["series"])

    async def test_uncertain_quick_add_requires_confirmation(self):
        parsed = [{"kind": "expense", "amount": 250, "category": "Другое", "note": "кофе"}]
        with patch.object(main, "parse_text", new=AsyncMock(return_value=parsed)):
            preview = await self.client.post(
                "/api/app/add",
                headers=self.auth,
                json={"text": "кофе 250"},
            )
        preview_data = await preview.json()
        self.assertFalse(preview_data["confirmed"])
        history = await self.client.get("/api/app/transactions", headers=self.auth)
        self.assertEqual((await history.json())["items"], [])

        confirmed = await self.client.post(
            "/api/app/add",
            headers=self.auth,
            json={"items": [{**parsed[0], "category": "Кафе и рестораны", "uncertain": True}]},
        )
        self.assertEqual(confirmed.status, 200)
        history = await self.client.get("/api/app/transactions", headers=self.auth)
        self.assertEqual(len((await history.json())["items"]), 1)
        self.assertEqual(main.load_user_rules(self.user_id).get("кофе"), "Кафе и рестораны")

    async def test_budgets_goals_settings_and_export(self):
        budget = await self.client.post(
            "/api/app/budgets",
            headers=self.auth,
            json={"category": "Продукты", "limit": 10000},
        )
        self.assertEqual(budget.status, 200)
        with patch.object(main.bot, "send_message", new_callable=AsyncMock) as send_message:
            for amount in (8500, 2000, 10):
                result = await self.client.post(
                    "/api/app/add",
                    headers=self.auth,
                    json={"kind": "expense", "amount": amount, "category": "Продукты"},
                )
                self.assertEqual(result.status, 200)
            self.assertEqual(send_message.await_count, 2)

        budgets = await self.client.get("/api/app/budgets", headers=self.auth)
        budget_items = (await budgets.json())["items"]
        self.assertEqual(budget_items[0]["pct"], 105)

        goal = await self.client.post(
            "/api/app/goals",
            headers=self.auth,
            json={"title": "Отпуск", "target": 80000, "initial": 5000, "icon": "✈"},
        )
        self.assertEqual(goal.status, 200)
        goal_id = (await goal.json())["id"]
        contribution = await self.client.post(
            f"/api/app/goals/{goal_id}/add",
            headers=self.auth,
            json={"amount": 2500},
        )
        self.assertEqual(contribution.status, 200)
        goals = await self.client.get("/api/app/goals", headers=self.auth)
        self.assertEqual((await goals.json())["items"][0]["saved"], 7500)

        settings = await self.client.post(
            "/api/app/settings",
            headers=self.auth,
            json={"theme": "light", "timezone": "Asia/Dushanbe", "weekly_summary": True},
        )
        self.assertEqual(settings.status, 200)
        preferences = await self.client.get("/api/app/settings", headers=self.auth)
        preference_data = await preferences.json()
        self.assertEqual(preference_data["settings"]["timezone"], "Asia/Dushanbe")
        self.assertEqual(preference_data["settings"]["weekly_summary"], 1)

        export = await self.client.get("/api/app/export", headers=self.auth)
        self.assertEqual(export.status, 200)
        self.assertIn("spreadsheetml", export.headers["Content-Type"])

        deleted = await self.client.delete("/api/app/data", headers=self.auth)
        self.assertEqual(deleted.status, 200)
        remaining_goals = await self.client.get("/api/app/goals", headers=self.auth)
        remaining_budgets = await self.client.get("/api/app/budgets", headers=self.auth)
        self.assertEqual((await remaining_goals.json())["items"], [])
        self.assertEqual((await remaining_budgets.json())["items"], [])


if __name__ == "__main__":
    unittest.main()
