"""Upload-only Telemedicine reconciliation.

The module deliberately keeps uploaded clinical files in the current
Streamlit session.  Name matching is only a fallback with service date and a
unique reference ID; a name alone never establishes identity.
"""
from __future__ import annotations

from datetime import date
import re

import pandas as pd

from dashboard.data import clean_text, excel_bytes, money, normalize_code
from dashboard.jhcis import identifier, name_key, service_date


DEFAULT_DATES = [
    date(2026, 4, 17), date(2026, 4, 10), date(2026, 1, 28),
    date(2025, 12, 17), date(2025, 12, 15),
]
CLAIM_RATE_SATANG = 5_000

TELEMED_COLUMNS = [
    "facility", "pid", "patient_name", "service_date", "rights", "icd10",
    "drugcode", "visit_id", "charge", "pid_source", "match_note",
    "source_file", "source_sheet", "source_row",
]

ALIASES = {
    "facility": ["facility", "รหัสหน่วยบริการ", "HSUB", "HCODE", "pcucode"],
    "pid": ["pid", "CID", "เลขบัตรประชาชน", "เลขบัตร", "เลขประจำตัวประชาชน", "idcard"],
    "patient_name": ["ชื่อ-นามสกุล", "ชื่อสกุล", "ชื่อผู้รับบริการ", "patient_name", "ชื่อ"],
    "first_name": ["ชื่อ", "ชื่อจริง", "fname", "firstname"],
    "last_name": ["สกุล", "นามสกุล", "lname", "lastname"],
    "service_date": ["วันที่รับบริการ", "วันที่บริการ", "วันเข้ารักษา", "visitdate", "service_date"],
    "rights": ["สิทธิ", "สิทธิ์", "สิทธิการรักษา", "สิทธิผู้ป่วย", "MAININSCL", "insurance", "right"],
    "icd10": ["ICD10", "ICD-10", "รหัสโรค", "diagcode", "diagnosis"],
    "drugcode": ["drugcode", "DrugCode", "รหัสยา", "รหัสจ่ายยา", "รหัสบริการยา"],
    "visit_id": ["เลขครั้งรับบริการ", "visitno", "visit", "เลข visit", "visit_id"],
    "charge": ["เรียกเก็บ", "ค่าบริการ", "จำนวนเงิน", "ยอดเรียกเก็บ", "charge", "amount"],
}


def _key(value) -> str:
    return re.sub(r"[\s_\-./():]", "", clean_text(value)).casefold()


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
        has_name = bool(fields.intersection({"patient_name", "first_name", "last_name"}))
        if "service_date" in fields and ("pid" in fields or has_name) and len(fields) >= 3:
            candidates.append((len(fields), int(index)))
    return sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1] if candidates else None


def read_file(filename: str, content: bytes):
    """Read CSV/XLS/XLSX with metadata rows before the real header."""
    if len(content) > 50 * 1024 * 1024:
        raise ValueError("ไฟล์ Telemedicine ต้องไม่เกิน 50 MB ต่อไฟล์")
    if filename.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp874"):
            try:
                return [("CSV", pd.read_csv(pd.io.common.BytesIO(content), encoding=encoding, dtype=object, keep_default_na=False))]
            except UnicodeDecodeError:
                continue
        raise ValueError("อ่าน CSV ไม่ได้ ใช้ UTF-8 หรือ Excel")
    engine = "openpyxl" if content.startswith(b"PK") else "xlrd" if content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")) else None
    if engine is None:
        raise ValueError("ไฟล์นี้ไม่ใช่ Excel .xls/.xlsx ที่รองรับ")
    output = []
    with pd.ExcelFile(pd.io.common.BytesIO(content), engine=engine) as book:
        for sheet in book.sheet_names:
            preview = book.parse(sheet, header=None, nrows=60, dtype=object)
            header = _find_header(preview)
            if header is not None:
                output.append((sheet, book.parse(sheet, header=header, dtype=object, keep_default_na=False)))
    if not output:
        raise ValueError("ไม่พบหัวตารางที่มีวันที่รับบริการ + ชื่อ/เลขบัตร + สิทธิ/ICD10/DrugCode")
    return output


def normalize_service(frame: pd.DataFrame, scope: str, source: str, sheet: str,
                      declare_scope: bool = False) -> tuple[pd.DataFrame, list[str]]:
    rename = column_map(frame.columns)
    if "service_date" not in rename.values() or not set(rename.values()).intersection({"pid", "patient_name", "first_name", "last_name"}):
        raise ValueError("ไฟล์ Telemedicine ต้องมีวันที่รับบริการ และเลขบัตรหรือชื่อ-สกุล")
    if "facility" not in rename.values() and not declare_scope:
        raise ValueError("ไฟล์ไม่มีรหัสหน่วยบริการ กรุณาติ๊กยืนยันว่าเป็นข้อมูลของหน่วยบัญชีนี้")
    source_columns = {field: column for column, field in rename.items()}
    rows, notices = [], []
    for ordinal, (_, raw) in enumerate(frame.iterrows(), start=2):
        value = lambda field: clean_text(raw[source_columns[field]]) if field in source_columns else ""
        pid = identifier(value("pid"))
        day = service_date(value("service_date"))
        first = value("first_name")
        last = value("last_name")
        patient_name = value("patient_name") or " ".join(part for part in (first, last) if part).strip()
        if (not pid and not patient_name) or day is None:
            if any(value(field) for field in ("pid", "patient_name", "first_name", "last_name", "service_date", "drugcode", "icd10", "rights")):
                notices.append(f"แถว {ordinal}: ชื่อ/เลขบัตรหรือวันที่อ่านไม่ได้ จึงยังไม่ใช้จับคู่")
            continue
        facility = normalize_code(value("facility")) if "facility" in source_columns else scope if declare_scope else ""
        if facility != scope:
            notices.append(f"แถว {ordinal}: ข้ามรหัสหน่วยบริการอื่น/ไม่มีรหัส")
            continue
        rows.append({
            "facility": scope, "pid": pid, "patient_name": patient_name,
            "service_date": day, "rights": value("rights"), "icd10": value("icd10"),
            "drugcode": value("drugcode"), "visit_id": value("visit_id"),
            "charge": value("charge"), "pid_source": "มีในไฟล์บริการ" if pid else "ยังไม่มีเลขบัตร",
            "match_note": "รอเทียบไฟล์อ้างอิง" if not pid else "",
            "source_file": source, "source_sheet": sheet, "source_row": ordinal,
        })
    return pd.DataFrame(rows, columns=TELEMED_COLUMNS), notices


def from_jhcis(records: pd.DataFrame, scope: str) -> pd.DataFrame:
    """Adapt the existing read-only JHCIS visit evidence to the Telemed schema."""
    if records is None or records.empty:
        return pd.DataFrame(columns=TELEMED_COLUMNS)
    rows = []
    for _, row in records.iterrows():
        pid = identifier(row.get("pid", ""))
        day = service_date(row.get("service_date"))
        if not pid or day is None:
            continue
        rows.append({
            "facility": scope, "pid": pid, "patient_name": clean_text(row.get("patient_name", "")),
            "service_date": day, "rights": clean_text(row.get("rights", "")),
            "icd10": clean_text(row.get("icd10", "")), "drugcode": clean_text(row.get("drugcode", "")),
            "visit_id": clean_text(row.get("visit_id", "")), "charge": "",
            "pid_source": "JHCIS", "match_note": "", "source_file": "JHCIS", "source_sheet": "", "source_row": "",
        })
    return pd.DataFrame(rows, columns=TELEMED_COLUMNS)


def fill_missing_pids(services: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Fill blank IDs only when name+date resolves to one reference ID."""
    if services.empty or reference.empty:
        return services.copy()
    result = services.copy()
    ref = reference.copy()
    ref["_name_key"] = ref["patient_name"].map(name_key)
    ref["_key"] = list(zip(ref.facility, ref._name_key, ref.service_date))
    lookup = {}
    for key, group in ref.groupby("_key", dropna=False):
        ids = sorted({pid for pid in group.pid if pid})
        if len(ids) == 1:
            lookup[key] = ids[0]
    for index, row in result.iterrows():
        if row.pid:
            continue
        key = (row.facility, name_key(row.patient_name), row.service_date)
        if key in lookup:
            result.at[index, "pid"] = lookup[key]
            result.at[index, "pid_source"] = "เติมจากไฟล์อ้างอิง"
            result.at[index, "match_note"] = "เติมเลขบัตรจากชื่อ-สกุล + วันที่"
        else:
            result.at[index, "match_note"] = "ไม่พบเลขบัตรที่ตรงกัน หรือมีหลายคนชื่อเดียวกัน"
    return result


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
        return pd.DataFrame(columns=["claim_index", "facility", "pid", "patient_name", "service_date", "charge_baht", "paid_baht", "service", "projcode"])
    pid_col = _claim_column(frame, ["PID", "เลขบัตรประชาชน", "เลขบัตร"])
    name_col = _claim_column(frame, ["ชื่อ-นามสกุล", "ชื่อผู้รับบริการ", "ชื่อสกุล"])
    first_col = _claim_column(frame, ["ชื่อ", "fname", "firstname"])
    last_col = _claim_column(frame, ["สกุล", "นามสกุล", "lname", "lastname"])
    date_col = _claim_column(frame, ["วันเข้ารักษา", "วันที่รับบริการ", "วันที่บริการ"])
    charge_col = _claim_column(frame, ["เรียกเก็บ", "ยอดเรียกเก็บ"])
    paid_col = _claim_column(frame, ["ยอดชดเชยทั้งสิ้น", "ยอดชดเชยที่จ่ายจริง"])
    service_col = _claim_column(frame, ["บริการ", "ชื่อบริการ"])
    project_col = _claim_column(frame, ["PROJCODE"])
    result = pd.DataFrame(index=frame.index)
    result["claim_index"] = frame.index + 1
    result["facility"] = frame.get("_facility", pd.Series(scope, index=frame.index)).map(normalize_code)
    result["pid"] = frame[pid_col].map(identifier) if pid_col else ""
    if name_col:
        result["patient_name"] = frame[name_col].map(clean_text)
    else:
        first = frame[first_col].map(clean_text) if first_col else pd.Series("", index=frame.index)
        last = frame[last_col].map(clean_text) if last_col else pd.Series("", index=frame.index)
        result["patient_name"] = [" ".join(part for part in (a, b) if part).strip() for a, b in zip(first, last)]
    result["service_date"] = frame[date_col].map(service_date) if date_col else None
    result["charge_baht"] = frame[charge_col].map(money).map(lambda v: None if v is None else v / 100) if charge_col else None
    result["paid_baht"] = frame[paid_col].map(money).map(lambda v: None if v is None else v / 100) if paid_col else None
    result["service"] = frame[service_col].map(clean_text) if service_col else ""
    result["projcode"] = frame[project_col].map(clean_text) if project_col else ""
    result["source_file"] = frame.get("_source_file", "")
    result["source_sheet"] = frame.get("_source_sheet", "")
    for output, candidates in {
        "HC_baht": ["HC"], "HC_DRUG_baht": ["HC-DRUG", "HC_DRUG", "DRUG"],
        "PP_baht": ["PP"], "FS_baht": ["FS"], "OP_baht": ["OP"],
    }.items():
        col = _claim_column(frame, candidates)
        values = frame[col].map(money) if col else pd.Series(None, index=frame.index)
        result[output] = values.map(lambda v: None if v is None else v / 100)
    return result.reset_index(drop=True)


def reconcile(claims: pd.DataFrame, services: pd.DataFrame, selected_dates=None) -> pd.DataFrame:
    selected = set(selected_dates or DEFAULT_DATES)
    claims = prepare_claims(claims, services["facility"].iloc[0] if not services.empty else "")
    if services.empty:
        return pd.DataFrame()
    service_rows = services.copy().reset_index(drop=True)
    service_rows["service_index"] = service_rows.index + 1
    service_rows["date_ok"] = service_rows.service_date.isin(selected)
    service_rows["telemed_ok"] = service_rows.drugcode.map(is_telemed)
    service_rows["uc_ok"] = service_rows.rights.map(is_uc)
    service_rows["chronic_ok"] = service_rows.icd10.map(is_chronic)
    service_rows["eligible"] = service_rows[["date_ok", "telemed_ok", "uc_ok", "chronic_ok"]].all(axis=1)
    key_claims = claims.assign(_pid_key=list(zip(claims.facility, claims.pid, claims.service_date)),
                               _name_key=list(zip(claims.facility, claims.patient_name.map(name_key), claims.service_date)))
    key_services = service_rows.assign(_pid_key=list(zip(service_rows.facility, service_rows.pid, service_rows.service_date)),
                                       _name_key=list(zip(service_rows.facility, service_rows.patient_name.map(name_key), service_rows.service_date)))
    grouped_pid = key_claims.groupby("_pid_key", dropna=False)
    grouped_name = key_claims.groupby("_name_key", dropna=False)
    out = []
    for _, row in key_services.iterrows():
        candidates = grouped_pid.get_group(row["_pid_key"]) if row.pid and row["_pid_key"] in grouped_pid.groups else pd.DataFrame()
        match_kind = "เลขบัตร + วันที่"
        if candidates.empty and row.patient_name:
            candidates = grouped_name.get_group(row["_name_key"]) if row["_name_key"] in grouped_name.groups and row["_name_key"][1] else pd.DataFrame()
            match_kind = "ชื่อ-สกุล + วันที่"
        base = {
            "วันที่รับบริการ": row.service_date, "เลขบัตรประชาชน": row.pid,
            "ชื่อผู้รับบริการ": row.patient_name, "สิทธิ": row.rights,
            "ICD10": row.icd10, "DrugCode": row.drugcode, "หน่วยบริการ": row.facility,
            "ผ่านวันเป้าหมาย": "ผ่าน" if row.date_ok else "ไม่อยู่ในวันที่เลือก",
            "TELEMED": "ผ่าน" if row.telemed_ok else "ไม่พบ TELEMED",
            "สิทธิ UC": "ผ่าน" if row.uc_ok else "ไม่ใช่ UC/ไม่ระบุ",
            "โรคเรื้อรัง": "ผ่าน" if row.chronic_ok else "ไม่พบ ICD10 โรคเรื้อรัง",
            "ผ่านเงื่อนไขเคลม": "ผ่าน" if row.eligible else "ไม่ผ่าน",
            "เลขบัตรที่มา": row.pid_source, "วิธีจับคู่": "", "ไฟล์บริการ": row.source_file, "แถวบริการ": row.source_row,
        }
        if candidates.empty:
            out.append({**base, "สถานะพึงรับ": "ไม่พบแถวพึงรับ", "เลขรายการพึงรับ": "", "เรียกเก็บ": None, "ยอดชดเชย": None, "บริการ": "", "วิธีจับคู่": "ยังไม่พบจากเลขบัตร/ชื่อ + วันที่",
                        "HC": None, "HC-DRUG": None, "PP": None, "FS": None, "OP": None,
                        "สถานะ HC": "ไม่พบพึงรับ", "สถานะ HC-DRUG": "ไม่พบพึงรับ"})
        else:
            for _, claim in candidates.iterrows():
                paid = claim.paid_baht
                status = "พบพึงรับ แต่ไม่ผ่านเงื่อนไข" if not row.eligible else (
                    "ชดเชย 50 บาท" if paid is not None and abs(paid - 50) < 0.005 else
                    "ไม่ชดเชย (0 บาท)" if paid is not None and abs(paid) < 0.005 else "ชดเชยจำนวนอื่น")
                out.append({**base, "เลขบัตรประชาชน": row.pid or claim.pid,
                            "สถานะพึงรับ": status, "เลขรายการพึงรับ": claim.claim_index,
                            "เรียกเก็บ": claim.charge_baht, "ยอดชดเชย": paid, "บริการ": claim.service,
                            "PROJCODE": claim.projcode, "วิธีจับคู่": match_kind,
                            "HC": claim.HC_baht, "HC-DRUG": claim.HC_DRUG_baht, "PP": claim.PP_baht, "FS": claim.FS_baht,
                            "สถานะ HC": "ชดเชย" if (claim.HC_baht or 0) > 0 else "ไม่ชดเชย/ไม่มี",
                            "สถานะ HC-DRUG": "ชดเชย" if (claim.HC_DRUG_baht or 0) > 0 else "ไม่ชดเชย/ไม่มี",
                            "OP": claim.OP_baht, "ไฟล์พึงรับ": claim.source_file, "ชีตพึงรับ": claim.source_sheet})
    return pd.DataFrame(out)


def summary(result: pd.DataFrame) -> dict:
    if result.empty:
        return {"คนไม่ซ้ำ": 0, "รายการบริการ": 0, "ผ่านเงื่อนไข": 0, "พบพึงรับ": 0, "ชดเชย50": 0,
                "ไม่ชดเชย": 0, "เรียกเก็บ": 0.0, "ยอดชดเชย": 0.0, "ผลต่าง": 0.0, "HC": 0.0, "HC-DRUG": 0.0}
    paid = pd.to_numeric(result["ยอดชดเชย"], errors="coerce")
    charge = pd.to_numeric(result["เรียกเก็บ"], errors="coerce")
    found = result["สถานะพึงรับ"].ne("ไม่พบแถวพึงรับ")
    eligible = result["ผ่านเงื่อนไขเคลม"].eq("ผ่าน")
    compensated = result["สถานะพึงรับ"].eq("ชดเชย 50 บาท")
    zero = result["สถานะพึงรับ"].eq("ไม่ชดเชย (0 บาท)")
    charge_total = charge.sum(min_count=1)
    paid_total = paid.sum(min_count=1)
    hc_total = pd.to_numeric(result.get("HC"), errors="coerce").sum(min_count=1) if "HC" in result else None
    herb_total = pd.to_numeric(result.get("HC-DRUG"), errors="coerce").sum(min_count=1) if "HC-DRUG" in result else None
    return {"คนไม่ซ้ำ": result["เลขบัตรประชาชน"].nunique(), "รายการบริการ": len(result),
            "ผ่านเงื่อนไข": int(eligible.sum()), "พบพึงรับ": int(found.sum()),
            "ชดเชย50": int(compensated.sum()), "ไม่ชดเชย": int(zero.sum()),
            "เรียกเก็บ": 0.0 if pd.isna(charge_total) else float(charge_total),
            "ยอดชดเชย": 0.0 if pd.isna(paid_total) else float(paid_total),
            "ผลต่าง": float((charge.fillna(0) - paid.fillna(0)).sum()),
            "HC": 0.0 if pd.isna(hc_total) else float(hc_total),
            "HC-DRUG": 0.0 if pd.isna(herb_total) else float(herb_total)}


def date_summary(result: pd.DataFrame) -> pd.DataFrame:
    columns = ["วันที่รับบริการ", "รายการบริการ", "คนไม่ซ้ำ", "ผ่านเงื่อนไข", "พบพึงรับ",
               "ชดเชย 50 บาท", "ไม่ชดเชย", "ยอดเรียกเก็บ", "ยอดชดเชย", "HC", "HC-DRUG"]
    if result.empty:
        return pd.DataFrame(columns=columns)
    frame = result.copy()
    frame["_paid"] = pd.to_numeric(frame["ยอดชดเชย"], errors="coerce")
    frame["_charge"] = pd.to_numeric(frame["เรียกเก็บ"], errors="coerce")
    frame["_eligible"] = frame["ผ่านเงื่อนไขเคลม"].eq("ผ่าน")
    frame["_found"] = frame["สถานะพึงรับ"].ne("ไม่พบแถวพึงรับ")
    frame["_50"] = frame["สถานะพึงรับ"].eq("ชดเชย 50 บาท")
    frame["_zero"] = frame["สถานะพึงรับ"].eq("ไม่ชดเชย (0 บาท)")
    for component in ("HC", "HC-DRUG"):
        frame["_" + component] = pd.to_numeric(frame.get(component), errors="coerce")
    grouped = frame.groupby("วันที่รับบริการ", dropna=False).agg({
        "เลขบัตรประชาชน": ["size", "nunique"], "_eligible": "sum", "_found": "sum",
        "_50": "sum", "_zero": "sum", "_charge": "sum", "_paid": "sum", "_HC": "sum", "_HC-DRUG": "sum",
    }).reset_index()
    grouped.columns = ["วันที่รับบริการ", "รายการบริการ", "คนไม่ซ้ำ", "ผ่านเงื่อนไข", "พบพึงรับ",
                       "ชดเชย 50 บาท", "ไม่ชดเชย", "ยอดเรียกเก็บ", "ยอดชดเชย", "HC", "HC-DRUG"]
    return grouped[columns].sort_values("วันที่รับบริการ")


def export(result: pd.DataFrame) -> bytes:
    if result.empty:
        return excel_bytes({"Telemed": result})
    return excel_bytes({"สรุป Telemed": date_summary(result), "รายละเอียดตรวจสอบ": result})

