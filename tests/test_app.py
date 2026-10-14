from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from io import BytesIO
import time
import unittest

import pandas as pd

from streamlit.testing.v1 import AppTest

from dashboard.auth import hash_password
from dashboard.registry import DEVELOPER_CREDIT

APP = str(Path(__file__).resolve().parents[1] / "app.py")


class AppTests(unittest.TestCase):
    def test_two_sessions_keep_uploads_and_filters_isolated(self):
        def uploaded(filename, code, amount):
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                pd.DataFrame({"HSUB": [code], "งวด": ["2569-09"], "งบพึงรับ": [amount]}).to_excel(writer, index=False)
            content = output.getvalue()
            return SimpleNamespace(name=filename, getvalue=lambda: content)
        credentials = {"users": {"Admin05542": {"password_hash": hash_password("test-only-passphrase")}}}
        apps = [AppTest.from_file(APP, default_timeout=45) for _ in range(2)]
        uploads = [uploaded("unit_A.xlsx", 5542, 1000), uploaded("unit_B.xlsx", 5555, 250)]
        for app, file, username in zip(apps, uploads, ["Admin05542", "Admin05555"]):
            app.secrets["auth"] = credentials
            app.session_state["user"] = username
            app.session_state["last_activity"] = time.time()
            with patch("streamlit.file_uploader", side_effect=lambda label, file=file, **kwargs: [file] if label.startswith("1.") else []):
                app.run()
                self.assertFalse(app.exception)
        self.assertEqual(apps[0].metric[0].value, "1,000.00")
        self.assertEqual(apps[1].metric[0].value, "250.00")
        with patch("streamlit.file_uploader", side_effect=lambda label, **kwargs: [uploads[0]] if label.startswith("1.") else []):
            apps[0].text_input(key="search").set_value("05555").run()
            self.assertFalse(apps[0].exception)
            self.assertEqual(len(apps[0].metric), 0)
        self.assertEqual(apps[1].text_input(key="search").value, "")
        self.assertEqual(apps[1].metric[0].value, "250.00")

    def test_uploaded_receivable_files_and_stm_categories(self):
        def upload(filename, frame):
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                frame.to_excel(writer, index=False, startrow=7)
            content = output.getvalue()
            return SimpleNamespace(name=filename, getvalue=lambda: content)
        budgets = [upload(f"receivable_{i}.xlsx", pd.DataFrame({
            "REP": ["680300024"], "TRAN_ID": [f"budget-{i}"], "HCODE": [5542], "HCODE_PAID": [11450],
            "PP": [100 if i == 0 else -20], "FS": [0], "ยอดชดเชยทั้งสิ้น": [100 if i == 0 else -20],
        })) for i in range(2)]
        statements = [upload("stm.xlsx", pd.DataFrame({
            "REP": ["680300024"], "TRAN_ID": ["stm-1"], "HCODE": [5542], "HCODE_PAID": [11450],
            "PP": [70], "FS": [0], "ยอดชดเชยทั้งสิ้น": [70],
        }))]
        app = AppTest.from_file(APP, default_timeout=45)
        app.secrets["auth"] = {"users": {"Admin05542": {"password_hash": hash_password("test-only-passphrase")}}}
        app.session_state["user"] = "Admin05542"
        app.session_state["last_activity"] = time.time()
        def files(label, **kwargs):
            return budgets if label.startswith("1.") else statements
        with patch("streamlit.file_uploader", side_effect=files):
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "80.00")
            self.assertEqual(next(m.value for m in app.metric if m.label == "ผลต่างสุทธิที่จับคู่ได้"), "10.00")
            self.assertEqual([m.value for m in app.metric if m.label == "PP สุทธิ"], ["80.00", "70.00"])
            app.text_input(key="search").set_value("5542").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "80.00")
            app.text_input(key="search").set_value("11450").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 0)

    def test_fixed_accounts_need_no_secrets_and_demo_is_separate(self):
        app = AppTest.from_file(APP, default_timeout=45)
        app.secrets["auth"] = {"users": {}}
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.button[0].disabled)
        self.assertTrue(any(DEVELOPER_CREDIT in c.value for c in app.caption))
        self.assertEqual(len(app.tabs), 0)
        app.button[1].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 3)
        self.assertEqual(app.metric[0].value, "325,000.50")
        self.assertEqual(next(m.value for m in app.metric if m.label == "ยอดชดเชย STM"), "310,000.50")
        self.assertEqual(next(m.value for m in app.metric if m.label == "ผลต่างสุทธิที่จับคู่ได้"), "15,000.00")
        app.text_input(key="search").set_value("5542").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "100,000.50")
        app.text_input(key="search").set_value("คำสะอาด").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "100,000.50")
        app.text_input(key="search").set_value("[").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 0)
        self.assertNotIn("demo_workbooks", app.session_state)

    def test_login_and_logout(self):
        app = AppTest.from_file(APP, default_timeout=45)
        app.secrets["auth"] = {"users": {"Admin05542": {"password_hash": hash_password("test-only-passphrase"), "display_name": "ทดสอบ"}}}
        app.run()
        self.assertFalse(app.exception)
        app.text_input[0].set_value("Admin05542")
        app.text_input[1].set_value("wrong")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 0)
        self.assertTrue(app.error)
        app.text_input[1].set_value("test-only-passphrase")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 3)
        self.assertEqual(app.session_state["user"], "Admin05542")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("user", app.session_state)
        self.assertEqual(len(app.tabs), 0)


if __name__ == "__main__":
    unittest.main()
