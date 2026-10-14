from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time
import unittest
import pandas as pd
from streamlit.testing.v1 import AppTest
from dashboard import focus as fc
from dashboard.data import ParsedSheet, prepare_records, read_workbook, details, excel_bytes


def make_frame(**overrides):
    values = {"HSUB": [5542, 5542, 5542], "REP": ["TEST"] * 3,
              "TRAN_ID": ["SYN-1", "SYN-2", "SYN-3"], "HN": ["01", "02", "03"],
              "HC": ["-", 20, 0], "HC-Drug": [40, 84, "-"], "DRUG": [999, 999, 999],
              "PP": [0, 80, -80], "FS": [0, 0, 0], "ยอดชดเชยทั้งสิ้น": [40, 184, "-"],
              "บริการ": ["ครีมไพล", "มะขามป้อม", "ยังรอตรวจ"]}
    values.update(overrides)
    buf = BytesIO()
    pd.DataFrame(values).to_excel(buf, index=False, startrow=7)
    parsed, errors = read_workbook(buf.getvalue(), "synthetic.xlsx")
    assert not errors
    return prepare_records(parsed[0], "HSUB", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0], buf.getvalue()


class FocusTests(unittest.TestCase):
    def test_explicit_drug_header_wins_no_double_count_and_blank_total_stays_unknown(self):
        frame, _ = make_frame()
        rows = fc.review_rows(frame)
        self.assertEqual(rows["HC-DRUG"].tolist(), [4000, 8400, 0])
        self.assertEqual(fc.total_info(rows, "PP")["cents"], 0)
        self.assertTrue(pd.isna(rows.iloc[2][fc.TOTAL]))
        self.assertEqual(fc.total_info(rows, fc.TOTAL), {"cents": 22400, "missing": 1, "count": 2})
        self.assertEqual(rows.iloc[0]["HC"], 0)
        strict = fc.review_rows(frame, empty_zero=False)
        self.assertTrue(pd.isna(strict.iloc[0]["HC"]))
        self.assertIn("บริการ", details(frame, "stm"))
        self.assertIn("HC-DRUG", details(frame, "stm"))

    def test_mixed_file_missing_category_does_not_turn_into_zero(self):
        explicit, _ = make_frame()
        raw = pd.DataFrame({"HSUB": [5542], "REP": ["TEST"], "DRUG": [12], "ยอดชดเชยทั้งสิ้น": [12]})
        raw = raw.assign(_source_file="second.xlsx", _source_sheet="Sheet1", _source_row=2)
        other = prepare_records(ParsedSheet("second.xlsx", "Sheet1", raw, 1, 1), "HSUB", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0]
        rows = fc.review_rows(pd.concat([explicit, other], ignore_index=True))
        self.assertEqual(rows.iloc[-1]["HC-DRUG"], 1200)
        self.assertTrue(pd.isna(rows.iloc[-1]["PP"]))
        none = fc.review_rows(other, drug_column=None)
        self.assertTrue(pd.isna(none.iloc[0]["HC-DRUG"]))

    def test_manual_notes_are_bound_to_business_row_and_filters_union_rows(self):
        frame, _ = make_frame()
        key = fc.row_key(frame.iloc[0])
        notes = {key: {"บริการที่ตรวจเอง": "ครีมไพลตรวจแล้ว", "ต้องติดตาม": True,
                       "ยอดตามสมุนไพร (กรอกเอง)": 15.25, "ยอดตาม PP (กรอกเอง)": None}}
        rows = fc.review_rows(frame, notes)
        self.assertEqual(fc.filter_rows(rows, query="ครีมไพลตรวจ").shape[0], 1)
        self.assertEqual(fc.filter_rows(rows, categories=["HC", "HC-DRUG"]).shape[0], 2)
        self.assertEqual(fc.filter_rows(rows, tracking="ยอดรวมว่าง/อ่านไม่ได้").shape[0], 1)
        count, totals, missing = fc.tracking_summary(rows)
        self.assertEqual((count, totals[fc.EDIT_COLUMNS[2]], missing), (1, 15.25, 0))
        changed = frame.copy()
        changed.loc[0, "TRAN_ID"] = "DIFFERENT"
        self.assertEqual(fc.review_rows(changed, notes).iloc[0]["บริการที่ตรวจเอง"], "")
        exported = fc.export_rows(rows, False)
        self.assertNotIn("PID", exported)
        self.assertNotIn("ชื่อ-นามสกุล", exported)
        self.assertEqual(exported.iloc[0]["HC-DRUG"], 40)
        self.assertEqual(exported.iloc[0]["บริการจากไฟล์"], "ครีมไพล")
        xlsx = pd.read_excel(BytesIO(excel_bytes({"รายละเอียด": exported})))
        self.assertEqual(xlsx.iloc[0]["ยอดตามสมุนไพร (กรอกเอง)"], 15.25)

    def test_compare_only_same_known_period_and_complete_categories(self):
        frame, _ = make_frame()
        a = fc.review_rows(frame)
        other = frame.copy()
        other["PP"] = [0, 60, -80]
        b = fc.review_rows(other)
        matched = fc.compare_categories(a, b)
        self.assertEqual(matched.loc[matched["หมวด"].eq("PP"), "ผลต่างรอตรวจสอบ (บาท)"].iloc[0], 20)
        b["งวด / REP"] = "OTHER"
        self.assertTrue(fc.compare_categories(a, b)["ผลต่างรอตรวจสอบ (บาท)"].isna().all())
        a["งวด / REP"] = "ยังไม่ระบุงวด"
        b["งวด / REP"] = "ยังไม่ระบุงวด"
        self.assertTrue(fc.compare_categories(a, b)["ผลต่างรอตรวจสอบ (บาท)"].isna().all())

    def test_ui_filters_and_manual_save_update_summary(self):
        _, content = make_frame()
        upload = SimpleNamespace(name="synthetic.xlsx", getvalue=lambda: content)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=90)
        app.secrets["auth"] = {"users": {}}
        app.session_state["user"] = "Admin05542"
        app.session_state["last_activity"] = time.time()
        with patch("streamlit.file_uploader", side_effect=lambda label, **kw: [upload] if label.startswith("1.") else []):
            app.run()
            self.assertFalse(app.exception)
            app.text_input(key="service_focus_query").set_value("ครีมไพล").run()
            self.assertFalse(app.exception)
            original_editor = __import__("streamlit").data_editor
            def edits(data, **kw):
                if kw.get("key", "").startswith("service_review_editor_"):
                    data = data.copy()
                    data.loc[0, "บริการที่ตรวจเอง"] = "บริการตรวจเอง"
                    data.loc[0, "ต้องติดตาม"] = True
                    data.loc[0, "ยอดตามสมุนไพร (กรอกเอง)"] = 25.0
                return original_editor(data, **kw)
            with patch("streamlit.data_editor", side_effect=edits):
                next(button for button in app.button if button.label == "บันทึกชื่อบริการและรายการติดตาม").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["focus_notes_budget"])
            app.text_input(key="service_focus_query").set_value("").run()
            app.selectbox(key="service_focus_status").set_value("ต้องติดตาม").run()
            self.assertFalse(app.exception)
            self.assertTrue(any("25.00" in block.value and "ยอดตามสมุนไพร" in block.value for block in app.code))


if __name__ == "__main__":
    unittest.main()
