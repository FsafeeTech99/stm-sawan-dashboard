from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time
import unittest
import pandas as pd
from streamlit.testing.v1 import AppTest
from dashboard.data import read_workbook, prepare_records, combine_records, summarize
from test_data import workbook_bytes


HEADERS = ["HSUB", "REP", "เดือน", "TRAN_ID", "PP", "ยอดชดเชยทั้งสิ้น"]


class BulkImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payloads, cls.all_rows = [], []
        for index in range(200):
            rows = [[5542, f"REP-{index % 3 + 1}", "2569-09", f"SIM-{index}-{j}", 0.10, 0.10] for j in range(10)]
            # Each independent file may have its own column order and header row.
            order = list(range(6)) if index % 2 else [3, 5, 0, 4, 2, 1]
            cls.payloads.append((f"synthetic-{index}.{'xls' if index % 2 else 'xlsx'}",
                workbook_bytes([HEADERS[i] for i in order], [[row[i] for i in order] for row in rows],
                               metadata=5 + index % 4, legacy=bool(index % 2))))
            cls.all_rows.extend(rows)

    def test_200_raw_files_equal_one_merged_file_across_three_reps(self):
        started = time.perf_counter()
        frames = []
        for name, content in self.payloads:
            sheets, errors = read_workbook(content, name)
            self.assertFalse(errors)
            frames.append(prepare_records(sheets[0], "HSUB", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0])
        separate, duplicates = combine_records(frames)
        merged_bytes = workbook_bytes(HEADERS, self.all_rows)
        sheets, errors = read_workbook(merged_bytes, "merged.xlsx")
        self.assertFalse(errors)
        merged = prepare_records(sheets[0], "HSUB", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0]
        self.assertEqual(len(separate), 2000)
        self.assertEqual(duplicates, 0)
        self.assertEqual(summarize(separate)["ยอดเงิน"].sum(), 200)
        pd.testing.assert_frame_equal(summarize(separate), summarize(merged))
        both, duplicate_rows = combine_records([separate, merged])
        self.assertEqual((len(both), duplicate_rows), (2000, 2000))
        print(f"\nBulk benchmark: 200 mixed XLS/XLSX files / 2,000 rows + merged-file verification: {time.perf_counter()-started:.2f}s")

    def test_repeated_header_same_layout_and_shifted_header_rejected(self):
        first = [5542, "R1", "2569-09", "A", 80, 80]
        second = [5542, "R2", "2569-09", "B", 60, 60]
        good = workbook_bytes(HEADERS, [first, HEADERS, second, ["รวมทั้งสิ้น", None, None, None, 140, 140]])
        sheets, errors = read_workbook(good, "combined.xlsx")
        self.assertFalse(errors)
        self.assertEqual(sheets[0].frame.REP.tolist(), ["R1", "R2"])
        self.assertEqual(sheets[0].dropped_rows, 2)
        changed = ["HSUB", "REP", "เดือน", "TRAN_ID", "ยอดชดเชยทั้งสิ้น", "PP"]
        sheets, errors = read_workbook(workbook_bytes(HEADERS, [first, changed, second]), "shifted.xlsx")
        self.assertEqual(sheets, [])
        self.assertIn("เรียงคอลัมน์ต่าง", errors[0])

    def test_merged_workbook_multiple_sheets_can_use_different_layouts(self):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            for index, cols in enumerate([HEADERS, list(reversed(HEADERS))]):
                pd.DataFrame([[5542, f"R{index}", "2569-09", str(index), 80, 80]], columns=HEADERS)[cols].to_excel(
                    writer, sheet_name=f"REP-{index}", startrow=5 + index, index=False)
        sheets, errors = read_workbook(output.getvalue(), "two-sheets.xlsx")
        self.assertFalse(errors)
        records = [prepare_records(sheet, "HSUB", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0] for sheet in sheets]
        result, _ = combine_records(records)
        self.assertEqual((len(result), result._period.nunique(), result._cents.sum()), (2, 2, 16000))

    def test_200_file_ui_keeps_small_editor_and_mapping_preferences(self):
        uploads = [SimpleNamespace(name=name, getvalue=lambda content=content: content) for name, content in self.payloads]
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=180)
        app.secrets["auth"] = {"users": {}}
        app.session_state["user"] = "Admin05542"
        app.session_state["last_activity"] = time.time()
        with patch("streamlit.file_uploader", side_effect=lambda label, **kw: uploads if label.startswith("1.") else []):
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "200.00")
            self.assertEqual(set(app.multiselect(key="period_filter").options), {"REP-1", "REP-2", "REP-3"})
            self.assertLess(len(app.selectbox), 40)
            prefs = app.session_state["import_mapping_preferences"]
            first_key = next(iter(prefs))
            app.text_input(key=first_key + "_manual").set_value("EXPLICIT-OVERRIDE").run()
            self.assertFalse(app.exception)
            sheet_choice = app.selectbox(key="mapping_sheet_choice_budget")
            sheet_choice.select_index(1).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["import_mapping_preferences"][first_key]["manual_period"], "EXPLICIT-OVERRIDE")
            self.assertIn("EXPLICIT-OVERRIDE", app.multiselect(key="period_filter").options)
            self.assertEqual(app.metric[0].value, "200.00")


if __name__ == "__main__":
    unittest.main()
