from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import unittest
import time

import pandas as pd
from streamlit.testing.v1 import AppTest

from dashboard import breakdown as bd
from dashboard.data import ParsedSheet, clean_text, prepare_records

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def prepared():
    raw = pd.DataFrame({"HSUB": [5542] * 7, "REP": ["TEST"] * 7,
        "TRAN_ID": [f"SIM-{i}" for i in range(7)],
        "PROJCODE": ["WALKIN", "walk-in", "WALK IN", "PPFS", "NON_WALKIN", "WALKIN01", "walkinside"],
        "PP": [80, 60, 360, 50, -80, 80, 0], "FS": [0, 0, 0, 0, 0, 49, 0],
        "DRUG": [10, 0, 0, 0, 0, 0, 0], "HC": [20, 0, 0, 0, 0, 0, 0],
        "ยอดชดเชยทั้งสิ้น": [110, 60, 360, 50, -80, 129, 0],
    }).assign(_source_file="synthetic.xlsx", _source_sheet="Sheet1", _source_row=range(2, 9))
    sheet = ParsedSheet("synthetic.xlsx", "Sheet1", raw, 1, 1)
    return prepare_records(sheet, "HSUB", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0]


class BreakdownTests(unittest.TestCase):
    def test_rates_match_category_and_price_without_relabeling_49(self):
        rules, _ = bd.rule_map(bd.DEFAULT_RULES)
        self.assertIn("หญิงไทยแก้มแดง", bd.estimate_service("PP", 8000, rules)[0])
        self.assertIn("FIT test", bd.estimate_service("PP", 6000, rules)[0])
        self.assertIn("ANC", bd.estimate_service("PP", 36000, rules)[0])
        self.assertIn("ยาคุม", bd.estimate_service("FS", 8000, rules)[0])
        self.assertEqual(bd.estimate_service("FS", 4900, rules)[0], "ยังจับคู่บริการไม่ได้")
        self.assertEqual(bd.estimate_service("HC", 12345, rules)[0], "ยาทั่วไป")

    def test_ambiguous_rates_and_negative_adjustments(self):
        name, status, possible = bd.estimate_service("PP", 5000, {})
        self.assertEqual(name, "หลายบริการที่เป็นไปได้")
        self.assertIn("HPV", possible)
        self.assertIn("HBsAg", possible)
        self.assertEqual(len(bd.rate_matches(15000, "PP")), 2)
        frame = prepared()
        before = frame.copy(deep=True)
        summary = bd.amount_summary(frame, "PP")
        self.assertEqual(summary["ยอดสุทธิ (บาท)"].sum(), 550)
        selected = bd.rows_for_amount(frame, "PP", -8000)
        self.assertEqual(len(selected), 1)
        self.assertEqual(bd.service_details(selected, "PP")["ยอดหมวดนี้ (บาท)"].iloc[0], -80)
        pd.testing.assert_frame_equal(before, frame)

    def test_walkin_is_projcode_only_and_totals_are_original(self):
        frame = prepared()
        walkin = bd.walkin_rows(frame)
        self.assertEqual(walkin.TRAN_ID.tolist(), ["SIM-0", "SIM-1", "SIM-2", "SIM-5"])
        table = bd.walkin_table(frame)
        self.assertEqual(table["PP (บาท)"].sum(), 580)
        self.assertEqual(table["FS (บาท)"].sum(), 49)
        self.assertEqual(table["ยอดชดเชยทั้งสิ้นจากไฟล์ (บาท)"].sum(), 659)
        self.assertNotIn("ชื่อ-นามสกุล", table)
        self.assertTrue(bd.walkin_rows(frame.drop(columns="PROJCODE")).empty)

    def test_manual_rule_conflicts_and_missing_values(self):
        rules = pd.DataFrame([["FS", 49, "ชื่อที่เจ้าหน้าที่กำหนด"], ["PP", 60, "A"], ["PP", 60, "B"]], columns=bd.DEFAULT_RULES.columns)
        mapped, errors = bd.rule_map(rules)
        self.assertTrue(errors)
        self.assertNotIn(("PP", 6000), mapped)
        self.assertEqual(bd.estimate_service("FS", 4900, mapped)[0], clean_text("ชื่อที่เจ้าหน้าที่กำหนด"))
        frame = prepared()
        frame.loc[0, "HC"] = None
        self.assertIsNone(bd.category_total(frame, "HC"))
        self.assertTrue(bd.amount_summary(frame.drop(columns="FS"), "FS").empty)

    def test_live_ui_flow_walkin_click_price_and_scope(self):
        frame = prepared().drop(columns=[c for c in prepared() if c.startswith("_")])
        extra = frame.iloc[:1].copy()
        extra["HSUB"] = 5555
        extra["PP"] = 990
        extra["TRAN_ID"] = "NOT-OWN"
        output = BytesIO()
        pd.concat([frame, extra], ignore_index=True).to_excel(output, index=False)
        upload = SimpleNamespace(name="synthetic.xlsx", getvalue=lambda: output.getvalue())
        app = AppTest.from_file(APP, default_timeout=60)
        app.secrets["auth"] = {"users": {}}
        app.session_state["user"] = "Admin05542"
        app.session_state["last_activity"] = time.time()
        with patch("streamlit.file_uploader", side_effect=lambda label, **kwargs: [upload] if label.startswith("1.") else []):
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs), 5)
            self.assertEqual(next(m.value for m in app.metric if m.label == "ยอดรวมจากไฟล์ • Walk-in"), "659.00")
            price = next(s for s in app.selectbox if s.label == "เลือกยอดต่อรายการเพื่อเจาะรายละเอียด" and s.key.startswith("service_price"))
            price.set_value("80.00 บาท").run()
            self.assertFalse(app.exception)
            self.assertEqual(next(m.value for m in app.metric if m.label == "รายการ PP ที่เลือก"), "2")
            app.button(key="walkin_open_HC").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio(key="walkin_category").value, "HC")
            for table in app.dataframe:
                if "TRAN_ID" in table.value:
                    self.assertNotIn("NOT-OWN", table.value.TRAN_ID.tolist())


if __name__ == "__main__":
    unittest.main()
