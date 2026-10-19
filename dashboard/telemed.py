"""Upload-only Telemedicine reconciliation.

The module deliberately keeps the clinical file in the current Streamlit
session.  It does not connect to JHCIS and it never guesses an identity from
name alone: a claim is linked by citizen ID, service date, and facility.
"""
from __future__ import annotations

from datetime import date
import re

import pandas as pd

from dashboard.data import clean_text, excel_bytes, money, normalize_code
from dashboard.jhcis import identifier, service_date


DEFAULT_DATES = [
    date(2026, 4, 17), date(2026, 4, 10), date(2026, 1, 28),
    date(2025, 12, 17), date(2025, 12, 15),
]
CLAIM_RATE_SATANG = 5_000

TELEMED_COLUMNS = [
    "facility", "pid", "patient_name", "service_date", "rights", "icd10",
    "drugcode", "visit_id", "charge", "pid_source", "match_note", "source_file", "source_sheet", "source_row",
]

ALIASES = {
    "facility": ["facility", "รหัสหน่วยบริการ", "HSUB", "HCODE", "pcucode"],
    "pid": ["pid", "CID", "เลขบัตรประชาชน", "เลขบัตร", "เลขประจำตัวประชาชน", "idcard"],
    "patient_name": ["ชื่อ-นามสกุล", "ชื่อสกุล", "ชื่อผู้รับบริการ", "ชื่อผู้ป่วย", "patient_name"],
    "first_name": ["ชื่อ", "ชื่อจริง", "first_name"],
    "last_name": ["สกุล", "นามสกุล", "last_name"],
    "service_date": ["วันที่รับบริการ", "วันที่บริการ", "วันเข้ารักษา", "visitdate", "service_date"],
    "rights": ["สิทธิ", "สิทธิ์", "สิทธิการรักษา", "สิทธิผู้ป่วย", "MAININSCL", "insurance", "right"],
    "icd10": ["ICD10", "ICD-10", "รหัสโรค", "diagcode", "diagnosis"],
    "drugcode": ["drugcode", "DrugCode", "รหัสยา", "รหัสจ่ายยา", "รหัสบริการยา"],
    "visit_id": ["เลขครั้งรับบริการ", "visitno", "visit", "เลข visit", "visit_id"],
    "charge": ["เรียกเก็บ", "ค่าบริการ", "จำนวนเงิน", "ยอดเรียกเก็บ", "charge", "amount"],
}


def _key(value) -> str:
    return re.sub(r"[\s_\-./():]", "", clean_text(value)).casefold()


def _person_key(value) -> str:
    return re.sub(r"\s+", "", clean_text(value)).casefold()


def column_map(columns) -> dict[str, str]:
    lookup = {_key(alias): field for field, aliases in ALIASES.items() for alias in [field, *aliases]}
    result = {}
    for column in columns:
        field = lookup.get(_key(column))
        if field and field not in result.values():
            result[column] = field
    return result


def _find_header(preview: pd.DataFrame) -> int | None:
    candidates = []
    for index, row in preview.iterrows():
        fields = set(column_map(row.tolist()).values())
        if "service_date" in fields and ("pid" in fields or "patient_name" in fields or ("first_name" in fields and "last_name" in fields)) and len(fields) >= 2:
            candidates.append((len(fields), int(index)))
    return sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1] if candidates else None



def read_file(filename: str, content: bytes):
    """Read CSV/XLS/XLSX, including Navicat/Excel .xls files with metadata rows."""
    if len(content) > 50 * 1024 * 1024:
        raise ValueError("ไฟล์ Telemedicine ต้องไม่เกิน 50 MB ต่อไฟล์")
    if filename.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp874", "tis-620"):
            try:
                return [("CSV", pd.read_csv(pd.io.common.BytesIO(content), encoding=encoding, dtype=object, keep_default_na=False))]
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise ValueError("อ่าน CSV ไม่ได้ ใช้ UTF-8 หรือ Excel")
    engine = "openpyxl" if content.startswith(b"PK") else "xlrd" if content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")) else None
    output = []
    excel_error = None
    if engine:
        try:
            with pd.ExcelFile(pd.io.common.BytesIO(content), engine=engine) as book:
                for sheet in book.sheet_names:
                    preview = book.parse(sheet, header=None, nrows=60, dtype=object)
                    header = _find_header(preview)
                    if header is not None:
                        output.append((sheet, book.parse(sheet, header=header, dtype=object, keep_default_na=False)))
        except Exception as error:
            excel_error = error
            output = []
    # Some Navicat/Excel exports are HTML tables saved with an .xls suffix.
    if not output:
        try:
            html_tables = pd.read_html(pd.io.common.BytesIO(content))
            for index, table in enumerate(html_tables, start=1):
                header = _find_header(table.head(60))
                if header is not None:
                    table = table.iloc[header:].copy()
                    table.columns = table.iloc[0].tolist()
                    output.append((f"HTML-{index}", table.iloc[1:].reset_index(drop=True)))
        except Exception:
            pass
    if not output:
        if excel_error:
            raise ValueError("อ่านไฟล์ Excel ไม่ได้ กรุณาเปิดไฟล์ใน Excel แล้วบันทึกเป็น .xlsx หรือ CSV UTF-8 ก่อนอัปโหลด")
        raise ValueError("ไม่พบหัวตารางวันที่รับบริการและ PID/ชื่อผู้รับบริการ")
    return output

def normalize_service(frame: pd.DataFrame, scope: str, source: str, sheet: str,
                      declare_scope: bool = False) -> tuple[pd.DataFrame, list[str]]:
    rename = column_map(frame.columns)
    required = {"service_date"}
    if not required.issubset(rename.values()) or not ({"pid", "patient_name"} & set(rename.values()) or {"first_name", "last_name"} <= set(rename.values())):
        raise ValueError("ไฟล์ Telemedicine ต้องมีวันที่รับบริการ และเลขบัตรหรือชื่อ-สกุล")
    if "facility" not in rename.values() and not declare_scope:
        raise ValueError("ไฟล์ไม่มีรหัสหน่วยบริการ กรุณาติ๊กยืนยันว่าเป็นข้อมูลของหน่วยบัญชีนี้")
    source_columns = {field: column for column, field in rename.items()}
    rows, notices = [], []
    for ordinal, (_, raw) in enumerate(frame.iterrows(), start=2):
        value = lambda field: clean_text(raw[source_columns[field]]) if field in source_columns else ""
        pid = identifier(value("pid"))
        patient_name = value("patient_name") or " ".join(part for part in (value("first_name"), value("last_name")) if part)
        day = service_date(value("service_date"))
        if day is None or (not pid and not patient_name):
            notices.append(f"แถว {ordinal}: ต้องมีวันที่และเลขบัตรหรือชื่อ-สกุล จึงจะจับคู่ได้")
            continue
        facility = normalize_code(value("facility")) if "facility" in source_columns else scope if declare_scope else ""
        if facility != scope:
            notices.append(f"แถว {ordinal}: ข้ามรหัสหน่วยบริการอื่น/ไม่มีรหัส")
            continue
        rows.append({
            "facility": scope, "pid": pid, "patient_name": patient_name,
            "service_date": day, "rights": value("rights"), "icd10": value("icd10"),
            "drugcode": value("drugcode"), "visit_id": value("visit_id"),
            "charge": value("charge"), "pid_source": "ไฟล์บริการ" if pid else "รอจับคู่",
            "match_note": "", "source_file": source, "source_sheet": sheet,
            "source_row": ordinal,
        })
    return pd.DataFrame(rows, columns=TELEMED_COLUMNS), notices


def _text_tokens(value) -> set[str]:
    return {re.sub(r"[^A-Z0-9]", "", part.upper()) for part in re.split(r"[,;|\s]+", clean_text(value)) if part}


def is_uc(value) -> bool:
    text = clean_text(value).upper()
    if any(term in text for term in ("ไม่ใช่", "ไม่ใช้สิทธิ", "NON-UC", "NON UC")):
        return False
    if any(term in text for term in ("บัตรทอง", "หลักประกันสุขภาพ", "30 บาท")):
        return True
    return bool(re.search(r"(?<![A-Z0-9])(UC|NHSO)(?![A-Z0-9])", text))


def is_telemed(value) -> bool:
    return any(re.sub(r"[^A-Z0-9]", "", part.upper()) == "TELEMED" for part in re.split(r"[,;|\s]+", clean_text(value)) if part)


def is_chronic(value) -> bool:
    """Conservative common NCD ICD-10 groups; Z codes are not chronic diagnoses."""
    for code in _text_tokens(value):
        if code.startswith(("I10", "I11", "I12", "I13", "I20", "I21", "I22", "I23", "I24", "I25",
                            "I50", "I60", "I61", "I62", "I63", "I64", "I65", "I66", "I67", "I68", "I69",
                            "E00", "E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10", "E11", "E12", "E13", "E14",
                            "E66", "E78", "J40", "J41", "J42", "J43", "J44", "J45", "J46", "J47",
                            "K70", "K71", "K72", "K73", "K74", "K75", "K76", "N18", "G20", "G21", "G30", "G31", "G35", "G36", "G40", "G41",
                            "M05", "M06", "M15", "M16", "M17", "M18", "M19", "M32", "M33", "M34", "M35", "M36", "C", "F00", "F01", "F02", "F03")):
            return True
    return False


def default_dates() -> list[date]:
    return list(DEFAULT_DATES)


def _claim_column(frame: pd.DataFrame, candidates) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def prepare_claims(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["claim_index", "facility", "pid", "patient_name", "service_date", "charge_baht", "paid_baht", "service", "projcode", "maininscl", "op_baht", "hc_baht", "hcdrug_baht", "pp_baht", "fs_baht", "op50"])
    pid_col = _claim_column(frame, ["PID", "เลขบัตรประชาชน", "เลขบัตร"])
    name_col = _claim_column(frame, ["ชื่อ-นามสกุล", "ชื่อผู้รับบริการ", "ชื่อ"])
    date_col = _claim_column(frame, ["วันเข้ารักษา", "วันที่รับบริการ", "วันที่บริการ"])
    charge_col = _claim_column(frame, ["เรียกเก็บ", "ยอดเรียกเก็บ"])
    paid_col = _claim_column(frame, ["ยอดชดเชยทั้งสิ้น", "ยอดชดเชยที่จ่ายจริง"])
    service_col = _claim_column(frame, ["บริการ", "ชื่อบริการ"])
    project_col = _claim_column(frame, ["PROJCODE"])
    maininscl_col = _claim_column(frame, ["MAININSCL", "สิทธิ", "สิทธิการรักษา"])
    op_col = _claim_column(frame, ["OP"])
    hc_col = _claim_column(frame, ["HC"])
    hcdrug_col = _claim_column(frame, ["HC-DRUG", "HC_DRUG", "DRUG"])
    pp_col = _claim_column(frame, ["PP"])
    fs_col = _claim_column(frame, ["FS"])
    result = pd.DataFrame(index=frame.index)
    result["claim_index"] = frame.index + 1
    result["facility"] = frame.get("_facility", pd.Series(scope, index=frame.index)).map(normalize_code)
    result["pid"] = frame[pid_col].map(identifier) if pid_col else ""
    result["patient_name"] = frame[name_col].map(clean_text) if name_col else ""
    result["service_date"] = frame[date_col].map(service_date) if date_col else None
    result["charge_baht"] = frame[charge_col].map(money).map(lambda v: None if v is None else v / 100) if charge_col else None
    result["paid_baht"] = frame[paid_col].map(money).map(lambda v: None if v is None else v / 100) if paid_col else None
    result["service"] = frame[service_col].map(clean_text) if service_col else ""
    result["projcode"] = frame[project_col].map(clean_text) if project_col else ""
    result["maininscl"] = frame[maininscl_col].map(clean_text) if maininscl_col else ""
    for out, col in [("op_baht", op_col), ("hc_baht", hc_col), ("hcdrug_baht", hcdrug_col), ("pp_baht", pp_col), ("fs_baht", fs_col)]:
        result[out] = frame[col].map(money).map(lambda v: None if v is None else v / 100) if col else None
    result["op50"] = result["op_baht"].map(lambda v: v is not None and abs(v - 50) < 0.005)
    result["source_file"] = frame.get("_source_file", "")
    result["source_sheet"] = frame.get("_source_sheet", "")
    return result.reset_index(drop=True)



def reconcile(claims: pd.DataFrame, services: pd.DataFrame, selected_dates=None) -> pd.DataFrame:
    selected = set(selected_dates or DEFAULT_DATES)
    claims = prepare_claims(claims, services["facility"].iloc[0] if not services.empty else "")
    if services.empty:
        return pd.DataFrame()
    service_rows = services.copy().reset_index(drop=True)
    service_rows["date_ok"] = service_rows.service_date.isin(selected)
    service_rows["telemed_ok"] = service_rows.drugcode.map(is_telemed)
    service_rows["uc_ok"] = service_rows.rights.map(is_uc)
    service_rows["chronic_ok"] = service_rows.icd10.map(is_chronic)
    service_rows["__person_key"] = service_rows.patient_name.map(_person_key)
    key_claims = claims.assign(_key=list(zip(claims.facility, claims.pid, claims.service_date)))
    grouped = key_claims.groupby("_key", dropna=False)
    name_claims = claims.assign(__person_key=claims.patient_name.map(_person_key))
    name_grouped = name_claims.groupby(["facility", "__person_key", "service_date"], dropna=False)
    out = []
    for _, row in service_rows.iterrows():
        key = (row.facility, row.pid, row.service_date)
        candidates = grouped.get_group(key) if row.pid and key in grouped.groups else pd.DataFrame()
        match_method = "PID + วันที่" if not candidates.empty else ""
        if candidates.empty and row.__person_key:
            nkey = (row.facility, row.__person_key, row.service_date)
            if nkey in name_grouped.groups:
                candidates = name_grouped.get_group(nkey)
                match_method = "ชื่อ-สกุล + วันที่"
        base = {
            "วันที่รับบริการ": row.service_date, "เลขบัตรประชาชน": row.pid,
            "ชื่อผู้รับบริการ": row.patient_name, "สิทธิ": row.rights,
            "ICD10": row.icd10, "DrugCode": row.drugcode, "หน่วยบริการ": row.facility,
            "ผ่านวันเป้าหมาย": "ผ่าน" if row.date_ok else "ไม่อยู่ในวันที่เลือก",
            "TELEMED": "ผ่าน" if row.telemed_ok else "ไม่พบ TELEMED/ไม่ได้ส่งมา",
            "สิทธิ UC": "ผ่าน" if row.uc_ok else "ไม่ใช่ UC/ไม่ระบุ",
            "โรคเรื้อรัง": "ผ่าน" if row.chronic_ok else "ไม่พบ ICD10 (ใช้ได้เมื่อ OP=50)",
            "ผ่านเงื่อนไขเคลม": "รอ OP=50 ในพึงรับ",
            "ไฟล์บริการ": row.source_file, "แถวบริการ": row.source_row,
        }
        if candidates.empty:
            base["ผ่านเงื่อนไขเคลม"] = "ไม่พบแถวพึงรับ"
            out.append({**base, "สถานะ Telemed": "รับบริการ แต่ไม่พบพึงรับ", "สถานะพึงรับ": "ไม่พบแถวพึงรับ",
                        "เลขบัตรที่มา": row.pid, "วิธีจับคู่": "", "OP": None, "OP=50": "ไม่พบ",
                        "HC": None, "HC-DRUG": None, "PP": None, "FS": None,
                        "เลขรายการพึงรับ": "", "เรียกเก็บ": None, "ยอดชดเชย": None, "บริการ": ""})
        else:
            for _, claim in candidates.iterrows():
                paid = claim.paid_baht
                op50 = bool(claim.op50)
                tele_status = "ชดเชย Telemed (OP 50 บาท)" if row.date_ok and op50 else "รับบริการ แต่ไม่มี OP 50 บาท • อาจตกหล่น"
                base["ผ่านเงื่อนไขเคลม"] = "ผ่าน" if row.date_ok and op50 else "ไม่ผ่าน: ไม่มี OP=50"
                status = "ชดเชย 50 บาท" if paid is not None and abs(paid - 50) < 0.005 else (
                    "ไม่ชดเชย (0 บาท)" if paid is not None and abs(paid) < 0.005 else "ชดเชยจำนวนอื่น")
                out.append({**base, "สถานะ Telemed": tele_status, "สถานะพึงรับ": status,
                            "เลขบัตรที่มา": claim.pid or row.pid, "วิธีจับคู่": match_method,
                            "OP": claim.op_baht, "OP=50": "ใช่" if op50 else "ไม่ใช่",
                            "HC": claim.hc_baht, "HC-DRUG": claim.hcdrug_baht,
                            "PP": claim.pp_baht, "FS": claim.fs_baht,
                            "เลขรายการพึงรับ": claim.claim_index, "เรียกเก็บ": claim.charge_baht,
                            "ยอดชดเชย": paid, "บริการ": claim.service,
                            "MAININSCL": claim.maininscl, "PROJCODE": claim.projcode,
                            "ไฟล์พึงรับ": claim.source_file, "ชีตพึงรับ": claim.source_sheet})
    result = pd.DataFrame(out)
    if not result.empty:
        result["เลขบัตรประชาชน"] = result["เลขบัตรประชาชน"].where(result["เลขบัตรประชาชน"].astype(bool), result["เลขบัตรที่มา"])
    return result

def summary(result: pd.DataFrame) -> dict:
    if result.empty:
        return {"คนไม่ซ้ำ": 0, "รายการบริการ": 0, "ผ่านเงื่อนไข": 0, "พบพึงรับ": 0, "ชดเชย50": 0,
                "ไม่ชดเชย": 0, "เรียกเก็บ": 0.0, "ยอดชดเชย": 0.0, "ผลต่าง": 0.0}
    paid = pd.to_numeric(result["ยอดชดเชย"], errors="coerce")
    charge = pd.to_numeric(result["เรียกเก็บ"], errors="coerce")
    found = result["สถานะพึงรับ"].ne("ไม่พบแถวพึงรับ")
    eligible = result["ผ่านเงื่อนไขเคลม"].eq("ผ่าน")
    compensated = result["สถานะพึงรับ"].eq("ชดเชย 50 บาท")
    zero = result["สถานะพึงรับ"].eq("ไม่ชดเชย (0 บาท)")
    charge_total = charge.sum(min_count=1)
    paid_total = paid.sum(min_count=1)
    return {"คนไม่ซ้ำ": result["เลขบัตรประชาชน"].nunique(), "รายการบริการ": len(result),
            "ผ่านเงื่อนไข": int(eligible.sum()), "พบพึงรับ": int(found.sum()),
            "ชดเชย50": int(compensated.sum()), "ไม่ชดเชย": int(zero.sum()),
            "เรียกเก็บ": 0.0 if pd.isna(charge_total) else float(charge_total),
            "ยอดชดเชย": 0.0 if pd.isna(paid_total) else float(paid_total),
            "ผลต่าง": float((charge.fillna(0) - paid.fillna(0)).sum())}


def date_summary(result: pd.DataFrame) -> pd.DataFrame:
    columns = ["วันที่รับบริการ", "รายการบริการ", "คนไม่ซ้ำ", "ผ่านเงื่อนไข", "พบพึงรับ",
               "มี OP 50", "ไม่มี OP 50/ตกหล่น", "ชดเชย 50 บาท", "ไม่ชดเชย", "ยอดเรียกเก็บ", "ยอดชดเชย"]
    if result.empty:
        return pd.DataFrame(columns=columns)
    frame = result.copy()
    frame["_paid"] = pd.to_numeric(frame["ยอดชดเชย"], errors="coerce")
    frame["_charge"] = pd.to_numeric(frame["เรียกเก็บ"], errors="coerce")
    frame["_eligible"] = frame["ผ่านเงื่อนไขเคลม"].eq("ผ่าน")
    frame["_found"] = frame["สถานะพึงรับ"].ne("ไม่พบแถวพึงรับ")
    frame["_op50"] = frame["OP=50"].eq("ใช่")
    frame["_no_op50"] = ~frame["_op50"]
    frame["_50"] = frame["สถานะพึงรับ"].eq("ชดเชย 50 บาท")
    frame["_zero"] = frame["สถานะพึงรับ"].eq("ไม่ชดเชย (0 บาท)")
    grouped = frame.groupby("วันที่รับบริการ", dropna=False).agg({
        "เลขบัตรประชาชน": ["size", "nunique"], "_eligible": "sum", "_found": "sum",
        "_op50": "sum", "_no_op50": "sum", "_50": "sum", "_zero": "sum", "_charge": "sum", "_paid": "sum",
    }).reset_index()
    grouped.columns = ["วันที่รับบริการ", "รายการบริการ", "คนไม่ซ้ำ", "ผ่านเงื่อนไข", "พบพึงรับ",
                       "มี OP 50", "ไม่มี OP 50/ตกหล่น", "ชดเชย 50 บาท", "ไม่ชดเชย", "ยอดเรียกเก็บ", "ยอดชดเชย"]
    return grouped[columns].sort_values("วันที่รับบริการ")


def export(result: pd.DataFrame) -> bytes:
    if result.empty:
        return excel_bytes({"Telemed": result})
    return excel_bytes({"สรุป Telemed": date_summary(result), "รายละเอียดตรวจสอบ": result})

