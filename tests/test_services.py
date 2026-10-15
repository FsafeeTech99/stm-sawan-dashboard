import unittest
import pandas as pd
from dashboard import services as sv
from dashboard import breakdown as bd
from dashboard.data import ParsedSheet, prepare_records
from dashboard.focus import review_rows


class ServiceSummaryTests(unittest.TestCase):
    def rows(self):
        frame = pd.DataFrame({
            "HCODE": ["05542"] * 7, "REP": ["SYNTHETIC"] * 7,
            "บริการ": ["fittest", "HCT เด็ก", "HCT เด็ก", "ธาตุอบเชย+ขมิ้นชัน", "ไพล+Tele", "ไพล+อบเชย", "เขียวหอมไม่จ่าย"],
            "HC": [0, 0, 0, 0, 0, 87.34, 0], "HC-DRUG": [0, 0, 0, 98, 40, 0, 0],
            "PP": [30, 80, 0, 0, 0, 0, 0], "FS": [0, 0, -48.99, 0, 0, 0, 0],
            "OP": [0, 0, 0, 0, 50, 0, 0], "ยอดชดเชยทั้งสิ้น": [30, 80, -48.99, 98, 90, 87.34, 0]})
        parsed = ParsedSheet("synthetic.xlsx", "Sheet1", frame, 1, 1)
        prepared = prepare_records(parsed, "HCODE", "ยอดชดเชยทั้งสิ้น", period_column="REP")[0]
        return review_rows(prepared), prepared

    def test_actual_labels_override_tariff_and_preserve_negative_and_zero(self):
        rows, _ = self.rows()
        report = sv.summarize_services(rows, by_price=True)
        fit = report.loc[report["กลุ่มบริการ"].eq("FIT test")].iloc[0]
        self.assertEqual((fit["ชดเชยต่อรายการ (บาท)"], fit["จำนวนรายการ"]), (30, 1))
        self.assertAlmostEqual(report["ยอดชดเชยทั้งสิ้น (บาท)"].sum(), 336.35)
        self.assertEqual(report["ยอดติดลบ (บาท)"].sum(), -48.99)
        self.assertEqual(report["รายการยอดศูนย์"].sum(), 1)
        self.assertEqual(report["จำนวนรายการ"].sum(), len(rows))

    def test_herbs_rollup_excludes_other_money_on_mixed_rows(self):
        rows, _ = self.rows()
        groups = rows.apply(sv.service_group, axis=1)
        self.assertEqual(groups.iloc[3], "สมุนไพร")
        self.assertTrue(groups.iloc[4].startswith("สมุนไพรร่วม"))
        self.assertTrue(groups.iloc[5].startswith("สมุนไพรร่วม"))
        self.assertEqual(rows["HC-DRUG"].sum(), 13800)
        self.assertEqual(rows["HC"].sum(), 8734)
        rows.loc[0, "ยอดชดเชยทั้งสิ้น"] = pd.NA
        report = sv.summarize_services(rows)
        self.assertEqual(report["รายการไม่ทราบยอด"].sum(), 1)
        self.assertTrue(pd.isna(report.loc[report["กลุ่มบริการ"].eq("FIT test"), "ยอดชดเชยทั้งสิ้น (บาท)"].iloc[0]))

    def test_price_estimates_do_not_override_supplied_services(self):
        _, frame = self.rows()
        self.assertTrue(bd.amount_summary(frame, "PP").empty)
        detail = bd.service_details(bd.rows_for_amount(frame, "PP"), "PP")
        self.assertEqual(detail.iloc[0]["บริการประมาณการ"], "fittest")
        self.assertEqual(bd.estimate_service("HC", 8734, {})[0], "ยาทั่วไป")
        self.assertEqual(bd.estimate_service("HC-DRUG", 9800, {})[0], "ยาสมุนไพร")


if __name__ == "__main__":
    unittest.main()

