"""Service estimates from user-supplied rates; original payouts stay unchanged."""
from __future__ import annotations

import re
import pandas as pd
from dashboard.data import clean_text, money

FOCUS = {"PP": "PP", "FS": "FS", "Drug": "DRUG", "HC": "HC"}
CATEGORIES = {**FOCUS, "Drug (2)": "DRUG__2", "OP": "OP", "AE": "AE", "INST": "INST"}
CATEGORY_NAMES = {"PP": "ส่งเสริมสุขภาพและป้องกันโรค", "FS": "บริการในคอลัมน์ FS",
                  "Drug": "ค่ายา DRUG ตำแหน่งแรก", "HC": "ยาสมุนไพร (ชื่อหมวดตามผู้ใช้)",
                  "Drug (2)": "ค่ายา DRUG ตำแหน่งที่สอง", "OP": "บริการผู้ป่วยนอก",
                  "AE": "บริการในคอลัมน์ AE", "INST": "บริการในคอลัมน์ INST"}
# Reference: the 21-row FY2570 image supplied by the user, not a verified current tariff.
RATES = [
    (1, "PP", 360, "หญิงตั้งครรภ์ • ฝากครรภ์ ANC 1–8 ครั้ง", "จ่ายยาบำรุงครรภ์", "Z340 / Z348 / Z349", "ต่อครั้ง", "8"),
    (2, "PP", 500, "ขัดฟันทำความสะอาดหญิงตั้งครรภ์ ANC", "2330011 + 2277320", "Z34.0–Z35.9", "ต่อครั้ง", "1"),
    (3, "PP", 75, "ทดสอบการตั้งครรภ์ PRT", "30014 / 31101", "Z32.0 / Z32.1", "ต่อครั้ง", "4"),
    (4, "PP", 150, "ตรวจหลังคลอด PNC ครั้งที่ 1–3", "30015", "Z390 / Z391 / Z392", "ต่อครั้ง", "3"),
    (5, "PP", 135, "Triferdine หลังคลอด ครั้งละ 3 เดือน", "30016 + Triferdine", "Z39.2", "ต่อครั้ง", "2"),
    (6, "PP", 60, "FIT test • คัดกรองมะเร็งลำไส้ใหญ่ อายุ 50–70 ปี", "31209 / 300222", "Z12.1", "ต่อครั้ง", "1"),
    (7, "PP", 80, "หญิงไทยแก้มแดง • Ferrofolic หญิงไทย 13–45 ปี", "TMT Ferrofolic", "Z13.0", "ต่อครั้ง", "1"),
    (8, "PP", 30, "คัดกรองโลหิตจาง Hct เด็ก 6–12 เดือน", "30104 / 300011", "Z13.0", "ต่อครั้ง", "1"),
    (9, "PP", 50, "ยาเสริมธาตุเหล็กเด็ก 6–12 เดือน", "TMT Folickid", "Z13.0", "ต่อครั้ง", "1"),
    (10, "PP", 100, "เคลือบฟลูออไรด์กลุ่มเสี่ยง อายุ 25–59 ปี", "61101 / 2387020 / 2387021", "K06.0", "ต่อครั้ง", "2"),
    (11, "FS", 80, "ยาคุมหญิงให้นมบุตร", "TMT ฮอร์โมนเดี่ยว", "G43.1 + Z30.4 + Z30.0", "ต่อแผง", "5"),
    (12, "FS", 40, "ยาเม็ดคุมกำเนิด", "TMT ฮอร์โมนรวม", "Z30.4 + Z30.0", "ต่อแผง", "5"),
    (13, "FS", 60, "ยาฉีดคุมกำเนิด", "TMT ยาฉีดคุมกำเนิด", "Z30.4 + Z30.0", "ต่อครั้ง", "5"),
    (14, "PP", 20, "วัคซีนไข้หวัดใหญ่ 7 กลุ่มเสี่ยง", "TMT Flu", "Z25.1", "ต่อครั้ง", "1"),
    (15, "PP", 50, "เก็บส่งตรวจ HPV อายุ 30–59 ปี", "C30", "Z11.5", "ต่อครั้ง", "1"),
    (16, "PP", 50, "คัดกรองไวรัสตับอักเสบบี HBsAg", "36318", "Z11.5", "ต่อครั้ง", "1"),
    (17, "PP", 50, "คัดกรองไวรัสตับอักเสบซี HCV-Ab", "351425", "Z11.5", "ต่อครั้ง", "1"),
    (18, "PP", 20, "วัคซีน EPI ตามแผนอายุ 0–14 ปี", "TMT ตามชนิดวัคซีน", "ตามชนิดวัคซีน", "ต่อครั้ง", "ตามอายุ"),
    (19, "PP", 20, "วัคซีน dT อายุ 25 ปีขึ้นไป", "TMT dT", "Z23.5 / Z23.6", "ต่อครั้ง", "1"),
    (20, "PP", 150, "ตรวจ HbA1c ผู้ป่วยเบาหวานชนิดที่ 2 สิทธิ UC", "", "E-", "ต่อครั้ง", "2"),
    (21, "PP", 40, "Serum creatinine / potassium ผู้ป่วย HT รายใหม่", "", "I10", "ต่อครั้ง", "1"),
]
RATE_DF = pd.DataFrame(RATES, columns=["ที่", "หมวด", "อัตราอ้างอิง (บาท)", "บริการที่อาจตรง", "CODE (NDP/TMT)", "ICD-10 ตามภาพ", "หน่วยราคา", "จำนวนครั้งตามภาพ"])
DEFAULT_RULES = pd.DataFrame([
    ["PP", 80.0, "หญิงไทยแก้มแดง • Ferrofolic"],
    ["PP", 60.0, "FIT test • คัดกรองมะเร็งลำไส้ใหญ่"],
    ["PP", 360.0, "หญิงตั้งครรภ์ • ฝากครรภ์ ANC"],
], columns=["หมวด", "ยอดต่อรายการ (บาท)", "ชื่อบริการประมาณการ"])


def valid_rows(frame):
    return frame.loc[frame["_valid"]].copy() if "_valid" in frame else frame.iloc[:0].copy()


def walkin_rows(frame):
    if frame.empty or "PROJCODE" not in frame:
        return frame.iloc[:0].copy()
    def marked(value):
        value = clean_text(value).upper()
        if re.search(r"(?:NO|NON|NOT)[\s_-]*WALK[\s_-]*IN", value):
            return False
        return bool(re.search(r"(?<![A-Z])WALK[\s_-]*IN(?![A-Z])", value))
    return frame.loc[frame["PROJCODE"].map(marked)].copy()


def rate_matches(cents, label):
    return RATE_DF.loc[RATE_DF["หมวด"].eq(label) & RATE_DF["อัตราอ้างอิง (บาท)"].map(money).eq(abs(int(cents)))].copy()


def rule_map(rules):
    """Conflicting manual labels are rejected, not resolved by row order."""
    grouped, errors = {}, []
    for _, row in rules.iterrows():
        group = clean_text(row.get("หมวด"))
        amount = money(row.get("ยอดต่อรายการ (บาท)"))
        name = clean_text(row.get("ชื่อบริการประมาณการ"))
        if not group and amount is None and not name:
            continue
        if group not in CATEGORIES or amount is None or amount <= 0 or not name:
            errors.append("กฎต้องมีหมวดที่รองรับ ราคาบวก และชื่อบริการครบ")
            continue
        grouped.setdefault((group, amount), set()).add(name)
    accepted = {}
    for key, names in grouped.items():
        if len(names) == 1:
            accepted[key] = next(iter(names))
        else:
            errors.append(f"{key[0]} {key[1] / 100:,.2f} บาทมีกฎชื่อขัดกัน จะใช้ตารางอ้างอิงแทน")
    return accepted, errors


def estimate_service(label, cents, rules):
    custom = rules.get((label, abs(int(cents))))
    candidates = rate_matches(cents, label)
    possible = " / ".join(candidates["บริการที่อาจตรง"].tolist())
    if custom:
        return custom, "ประมาณการตามกฎผู้ใช้", possible
    if len(candidates) == 1:
        return candidates.iloc[0]["บริการที่อาจตรง"], "ประมาณการจากหมวด + ราคา", possible
    if len(candidates) > 1:
        return "หลายบริการที่เป็นไปได้", "ราคาเดียวกันหลายบริการ", possible
    if label == "HC":
        return "ยาสมุนไพร", "ชื่อหมวดตามผู้ใช้ • ยังไม่ระบุรายการยา", ""
    return "ยังจับคู่บริการไม่ได้", "ไม่มีราคาอ้างอิงตรง", ""


def amount_summary(frame, label, rules=None):
    columns = ["บริการประมาณการ", "สถานะการจับคู่", "ยอดต่อรายการ (บาท)", "จำนวนรายการ", "ยอดบวก (บาท)", "ยอดติดลบ (บาท)", "ยอดสุทธิ (บาท)", "บริการที่อาจตรง"]
    rows = valid_rows(frame)
    column = CATEGORIES[label]
    if rows.empty or column not in rows:
        return pd.DataFrame(columns=columns)
    cents = pd.array(rows[column].map(money), dtype="Int64")
    counts = pd.Series(cents).dropna().loc[lambda s: s.ne(0)].value_counts()
    result = []
    for amount, count in counts.items():
        amount, count = int(amount), int(count)
        name, status, possible = estimate_service(label, amount, rules or {})
        total = amount * count
        result.append([name, status, amount / 100, count, max(total, 0) / 100, min(total, 0) / 100, total / 100, possible])
    return pd.DataFrame(result, columns=columns).sort_values("ยอดสุทธิ (บาท)", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def rows_for_amount(frame, label, cents=None):
    rows = valid_rows(frame)
    column = CATEGORIES[label]
    if column not in rows:
        return rows.iloc[:0].assign(_category_cents=pd.Series(dtype="Int64"))
    rows["_category_cents"] = pd.array(rows[column].map(money), dtype="Int64")
    mask = rows["_category_cents"].notna() & rows["_category_cents"].ne(0)
    if cents is not None:
        mask &= rows["_category_cents"].eq(int(cents))
    return rows.loc[mask].copy()


def category_total(frame, label):
    rows, column = valid_rows(frame), CATEGORIES[label]
    if rows.empty or column not in rows:
        return None
    values = rows[column].map(money)
    return None if values.isna().any() else sum(int(v) for v in values) / 100


def service_details(frame, label, rules=None, show_names=False):
    result = pd.DataFrame(index=frame.index)
    mapping = {"_facility": "รหัสหน่วยบริการ", "_source_file": "ไฟล์", "_source_sheet": "ชีต", "_source_row": "แถวต้นทาง", "_period": "งวด / REP", "REP": "REP", "TRAN_ID": "TRAN_ID", "HN": "HN", "วันเข้ารักษา": "วันเข้ารักษา", "PROJCODE": "PROJCODE"}
    for col, name in mapping.items():
        result[name] = frame[col] if col in frame else None
    if show_names:
        result["ชื่อ-นามสกุล"] = frame.get("ชื่อ-นามสกุล")
    amounts = frame.get("_category_cents", pd.Series(index=frame.index, dtype="Int64"))
    classified = [estimate_service(label, v, rules or {}) for v in amounts]
    result["หมวด"] = label
    result["บริการประมาณการ"] = [v[0] for v in classified]
    result["สถานะการจับคู่"] = [v[1] for v in classified]
    result["บริการที่อาจตรง"] = [v[2] for v in classified]
    result["ยอดหมวดนี้ (บาท)"] = amounts.map(lambda n: int(n) / 100)
    result["ยอดชดเชยทั้งสิ้นจากไฟล์ (บาท)"] = frame["_cents"].map(lambda n: int(n) / 100)
    return result.reset_index(drop=True)


def walkin_table(frame, rules=None, show_names=False):
    rows = valid_rows(walkin_rows(frame))
    columns = ["รหัสหน่วยบริการ", "REP", "TRAN_ID", "HN", "วันเข้ารักษา", "PROJCODE"]
    output = pd.DataFrame(index=rows.index)
    for name in columns:
        source = "_facility" if name == "รหัสหน่วยบริการ" else name
        output[name] = rows[source] if source in rows else None
    if show_names:
        output["ชื่อ-นามสกุล"] = rows.get("ชื่อ-นามสกุล")
    for label, col in FOCUS.items():
        values = rows[col].map(money) if col in rows else pd.Series(None, index=rows.index)
        output[f"{label} (บาท)"] = values.map(lambda n: int(n) / 100 if pd.notna(n) else None)
        output[f"{label} • บริการประมาณการ"] = [estimate_service(label, int(v), rules or {})[0] if pd.notna(v) and v else "" for v in values]
    output["ยอดชดเชยทั้งสิ้นจากไฟล์ (บาท)"] = rows["_cents"].map(lambda n: int(n) / 100)
    for col, label in [("_source_file", "ไฟล์"), ("_source_sheet", "ชีต"), ("_source_row", "แถวต้นทาง")]:
        output[label] = rows[col] if col in rows else None
    return output.reset_index(drop=True)
