"""Focused, source-preserving financial review. Amounts are integer satang."""
from __future__ import annotations

import hashlib
import json
import pandas as pd
from dashboard.data import clean_text, money

SERVICE_REVIEW_VERSION = 1
GROUPS = ["HC", "HC-DRUG", "PP", "FS"]
TOTAL = "ยอดชดเชยทั้งสิ้น"
EDIT_COLUMNS = ["บริการที่ตรวจเอง", "ต้องติดตาม", "ยอดตามสมุนไพร (กรอกเอง)", "ยอดตาม PP (กรอกเอง)", "บันทึกติดตาม"]


def row_key(row):
    # Include business contents: replacing a file with another file of the same
    # name must never attach a previous patient's annotations to a new patient.
    fields = {str(k): clean_text(v) for k, v in row.items() if not str(k).startswith("_")}
    fields.update({k: clean_text(row.get(k)) for k in ["_facility", "_period", "_source_file", "_source_sheet", "_source_row"]})
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def available(row, column):
    source = clean_text(row.get("_source_columns"))
    return f"|{column}|" in source if source else column in row.index


def component(row, column, empty_zero):
    if not column or not available(row, column):
        return None
    value = row.get(column)
    if empty_zero and clean_text(value) in {"", "-", "–", "—"}:
        return 0
    return money(value)


def review_rows(frame, annotations=None, drug_column="DRUG", empty_zero=True):
    records = []
    annotations = annotations or {}
    for _, row in frame.iterrows():
        if not clean_text(row.get("_facility")):
            continue
        key = row_key(row)
        note = annotations.get(key, {})
        drug = "HC-DRUG" if available(row, "HC-DRUG") else drug_column
        rec = {"_key": key, "รหัสหน่วยบริการ": row.get("_facility"), "งวด / REP": row.get("_period"),
               "TRAN_ID": row.get("TRAN_ID"), "HN": row.get("HN"), "PID": row.get("PID"),
               "ชื่อ-นามสกุล": row.get("ชื่อ-นามสกุล"), "วันเข้ารักษา": row.get("วันเข้ารักษา"),
               "PROJCODE": row.get("PROJCODE"), "บริการจากไฟล์": clean_text(row.get("บริการ")),
               "คอลัมน์ HC-DRUG": drug if drug and available(row, drug) else "ไม่มีคอลัมน์",
               "ไฟล์": row.get("_source_file"), "ชีต": row.get("_source_sheet"), "แถวต้นทาง": row.get("_source_row")}
        for group in GROUPS + ["OP"]:
            rec[group] = component(row, drug if group == "HC-DRUG" else group, empty_zero)
        # A blank total is unknown even if component blanks are treated as zero.
        rec[TOTAL] = money(row.get(TOTAL)) if available(row, TOTAL) else row.get("_cents")
        rec["เรียกเก็บ"] = money(row.get("เรียกเก็บ"))
        rec.update({"บริการที่ตรวจเอง": clean_text(note.get("บริการที่ตรวจเอง")),
                    "ต้องติดตาม": bool(note.get("ต้องติดตาม", False)),
                    "ยอดตามสมุนไพร (กรอกเอง)": note.get("ยอดตามสมุนไพร (กรอกเอง)"),
                    "ยอดตาม PP (กรอกเอง)": note.get("ยอดตาม PP (กรอกเอง)"),
                    "บันทึกติดตาม": clean_text(note.get("บันทึกติดตาม"))})
        rec["บริการ"] = rec["บริการที่ตรวจเอง"] or rec["บริการจากไฟล์"] or "ยังไม่ระบุบริการ"
        rec["ที่มาชื่อบริการ"] = "ผู้ใช้ตรวจเอง" if rec["บริการที่ตรวจเอง"] else "จากไฟล์" if rec["บริการจากไฟล์"] else "ยังไม่ระบุ"
        records.append(rec)
    result = pd.DataFrame(records)
    for col in GROUPS + ["OP", TOTAL, "เรียกเก็บ"]:
        result[col] = pd.array(result[col] if col in result else [], dtype="Int64")
    return result


def total_info(rows, column):
    values = rows[column]
    missing = int(values.isna().sum())
    return {"cents": sum(int(n) for n in values.dropna()), "missing": missing,
            "count": int(values.fillna(0).ne(0).sum())}


def summary(rows):
    result = []
    for col in [TOTAL] + GROUPS:
        info = total_info(rows, col)
        result.append({"หมวด": col, "ยอดอ่านได้ (บาท)": info["cents"] / 100,
                       "รายการมียอด": info["count"], "รายการไม่ทราบยอด": info["missing"],
                       "ความครบถ้วน": "ครบ" if info["missing"] == 0 else "ยอดบางส่วน • รอตรวจสอบ"})
    return pd.DataFrame(result)


def filter_rows(rows, categories=(), query="", service="ทั้งหมด", tracking="ทั้งหมด"):
    if rows.empty:
        return rows.copy()
    mask = pd.Series(True, index=rows.index)
    if categories:
        mask &= rows[list(categories)].fillna(0).ne(0).any(axis=1)
    if query.strip():
        columns = ["PID", "HN", "TRAN_ID", "ชื่อ-นามสกุล", "บริการ", "PROJCODE"]
        mask &= rows[columns].apply(lambda col: col.map(clean_text).str.contains(query.strip(), case=False, regex=False)).any(axis=1)
    if service != "ทั้งหมด":
        mask &= rows["บริการ"].eq(service)
    if tracking == "ต้องติดตาม":
        mask &= rows["ต้องติดตาม"]
    elif tracking == "ยังไม่ระบุบริการ":
        mask &= rows["บริการ"].eq("ยังไม่ระบุบริการ")
    elif tracking == "ยอดรวมว่าง/อ่านไม่ได้":
        mask &= rows[TOTAL].isna()
    return rows.loc[mask].copy()


def export_rows(rows, show_names=True):
    output = rows.drop(columns=["_key", "PID"] + ([] if show_names else ["ชื่อ-นามสกุล"]), errors="ignore").copy()
    for col in GROUPS + ["OP", TOTAL, "เรียกเก็บ"]:
        output[col] = output[col].astype("Float64") / 100
    order = ["รหัสหน่วยบริการ", "งวด / REP", "TRAN_ID", "HN", "ชื่อ-นามสกุล", "วันเข้ารักษา",
             "เรียกเก็บ", *GROUPS, TOTAL, "บริการ", "บริการจากไฟล์", "ที่มาชื่อบริการ", *EDIT_COLUMNS]
    return output[[c for c in order if c in output] + [c for c in output if c not in order]]


def tracking_summary(rows):
    selected = rows.loc[rows["ต้องติดตาม"]] if not rows.empty else rows
    amounts = {}
    for name in ["ยอดตามสมุนไพร (กรอกเอง)", "ยอดตาม PP (กรอกเอง)"]:
        values = selected[name].map(money) if name in selected else pd.Series(dtype=object)
        amounts[name] = sum(int(n) for n in values.dropna()) / 100
    no_amount = (selected[["ยอดตามสมุนไพร (กรอกเอง)", "ยอดตาม PP (กรอกเอง)"]].isna().all(axis=1).sum()
                 if not selected.empty else 0)
    return len(selected), amounts, int(no_amount)


def compare_categories(budget, stm):
    """Only compare complete category amounts from the same facility and period."""
    aggregate = []
    for rows in [budget, stm]:
        table = {}
        if not rows.empty:
            for (code, period), group in rows.groupby(["รหัสหน่วยบริการ", "งวด / REP"]):
                for col in GROUPS:
                    info = total_info(group, col)
                    table[(code, period, col)] = info["cents"] if not info["missing"] else None
        aggregate.append(table)
    result = []
    for key in sorted(set(aggregate[0]) | set(aggregate[1])):
        a, b = (table.get(key) for table in aggregate)
        matched = a is not None and b is not None and key[1] not in {"", "ยังไม่ระบุงวด"}
        result.append({"รหัสหน่วยบริการ": key[0], "งวด / REP": key[1], "หมวด": key[2],
                       "พึงรับ (บาท)": None if a is None else a / 100,
                       "STM (บาท)": None if b is None else b / 100,
                       "ผลต่างรอตรวจสอบ (บาท)": (a - b) / 100 if matched else None,
                       "สถานะ": "เปรียบเทียบงวดเดียวกัน" if matched else "ข้อมูล/งวดไม่ครบ"})
    return pd.DataFrame(result)
