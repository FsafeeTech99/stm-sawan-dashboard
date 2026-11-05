"""NDP/STM payment tracking for statement workbooks."""
from __future__ import annotations

import re
from io import BytesIO

import pandas as pd

from dashboard.data import clean_text, excel_bytes, money, normalize_code
from dashboard.jhcis import identifier, service_date


ALIASES = {
    "pid": ["PID", "pid", "เลขบัตรประชาชน", "เลขบัตร", "CID"],
    "name": ["ชื่อ-สกุล", "ชื่อ-นามสกุล", "ชื่อผู้รับบริการ", "ชื่อสกุล", "ชื่อ"],
    "service_date": ["วันเข้ารับบริการ", "วันที่รับบริการ", "วันรับบริการ", "วันที่บริการ", "service_date"],
    "amount": ["รายได้ชดเชย", "ยอดชดเชย", "เงินชดเชย", "จำนวนเงิน", "ยอดเงิน", "amount", "paid"],
    "right": ["ประเภทสิทธิ", "สิทธิ", "สิทธิการรักษา", "ประเภทผู้ป่วย", "กองทุน", "fund", "scheme"],
    "rep": ["REP_NO", "REP", "เลขงวด", "งวด"],
    "fund": ["กองทุนหลัก", "กองทุน", "Sub Fund", "กองทุนรอง"],
    "detail": ["รายละเอียด", "รายการ", "บริการ", "ชื่อบริการ"],
    "hcode": ["Hcode", "HCODE", "รหัสหน่วยบริการ"],
}


def _key(value):
    return re.sub(r"[\s_\-./():]", "", clean_text(value)).casefold()


def column_map(columns):
    lookup = {_key(alias): field for field, aliases in ALIASES.items() for alias in [field, *aliases]}
    out = {}
    for column in columns:
        field = lookup.get(_key(column))
        if field and field not in out.values():
            out[column] = field
    return out


def _header(preview):
    hits = []
    for idx, row in preview.iterrows():
        fields = set(column_map(row.tolist()).values())
        if {"pid", "amount"}.issubset(fields) or {"name", "amount"}.issubset(fields):
            hits.append((len(fields), int(idx)))
    return sorted(hits, key=lambda x: (-x[0], x[1]))[0][1] if hits else None


def read_file(filename, content):
    if filename.lower().endswith(".csv"):
        for enc in ("utf-8-sig", "cp874", "tis-620"):
            try:
                return [("CSV", pd.read_csv(BytesIO(content), encoding=enc, dtype=object, keep_default_na=False))]
            except (UnicodeDecodeError, pd.errors.ParserError):
                pass
        raise ValueError("อ่าน CSV ไม่ได้")
    engine = "openpyxl" if content.startswith(b"PK") else "xlrd"
    result = []
    with pd.ExcelFile(BytesIO(content), engine=engine) as book:
        for sheet in book.sheet_names:
            preview = book.parse(sheet, header=None, nrows=80, dtype=object)
            header = _header(preview)
            if header is not None:
                result.append((sheet, book.parse(sheet, header=header, dtype=object, keep_default_na=False)))
            else:
                # NDP exports commonly use HN + citizen ID and a fixed report header.
                for candidate in range(min(15, len(preview))):
                    values = {clean_text(v).upper() for v in preview.iloc[candidate].tolist()}
                    if "HN" in values and len(preview.columns) >= 9:
                        result.append((sheet, book.parse(sheet, header=candidate, dtype=object, keep_default_na=False)))
                        break
    if not result:
        raise ValueError("ไม่พบหัวตาราง PID/ชื่อ และยอดชดเชย")
    return result


def normalize(frame, facility, source, sheet):
    rename = column_map(frame.columns)
    source_col = {field: col for col, field in rename.items()}
    # Some NDP files are encoded with legacy Thai text, so use the stable
    # report layout as a fallback: ID card, name, service date, paid amount.
    if "pid" not in source_col and len(frame.columns) >= 6:
        source_col["pid"] = frame.columns[5]
    if "name" not in source_col and len(frame.columns) >= 7:
        source_col["name"] = frame.columns[6]
    if "service_date" not in source_col and len(frame.columns) >= 8:
        source_col["service_date"] = frame.columns[7]
    if "amount" not in source_col and len(frame.columns) >= 9:
        source_col["amount"] = frame.columns[8]
    if "amount" not in source_col or not ({"pid", "name"} & set(source_col)):
        raise ValueError("ต้องมีเลขบัตร/ชื่อ และคอลัมน์ยอดชดเชย")
    rows = []
    for row_no, (_, raw) in enumerate(frame.iterrows(), start=2):
        get = lambda field: clean_text(raw[source_col[field]]) if field in source_col else ""
        pid = identifier(get("pid"))
        name = get("name")
        amount = money(get("amount"))
        if amount is None or (not pid and not name):
            continue
        rows.append({
            "หน่วยบริการ": normalize_code(get("hcode")) or facility,
            "PID": pid, "ชื่อผู้รับบริการ": name,
            "วันที่รับบริการ": service_date(get("service_date")),
            "สิทธิ": get("right") or get("fund"),
            "กองทุน": get("fund") or get("right"),
            "REP_NO": get("rep"), "รายละเอียด": get("detail"),
            "ยอดชดเชย": amount / 100, "สถานะ": "ชดเชยแล้ว",
            "ไฟล์": source, "ชีต": sheet, "แถวต้นทาง": row_no,
        })
    return pd.DataFrame(rows)


def summary(frame):
    if frame.empty:
        return pd.DataFrame(columns=["สิทธิ", "กองทุน", "จำนวนเคส", "จำนวนคน", "ยอดชดเชย"])
    work = frame.copy()
    work["ยอดชดเชย"] = pd.to_numeric(work["ยอดชดเชย"], errors="coerce").fillna(0)
    return work.groupby(["สิทธิ", "กองทุน"], dropna=False).agg(
        **{"จำนวนเคส": ("PID", "size"), "จำนวนคน": ("PID", "nunique"), "ยอดชดเชย": ("ยอดชดเชย", "sum")}
    ).reset_index().sort_values("ยอดชดเชย", ascending=False)


def sheet_summary(frame):
    if frame.empty:
        return pd.DataFrame(columns=["ชีต", "จำนวนเคส", "จำนวนคน", "ยอดชดเชย"])
    return frame.groupby("ชีต", dropna=False).agg(**{"จำนวนเคส": ("PID", "size"), "จำนวนคน": ("PID", "nunique"), "ยอดชดเชย": ("ยอดชดเชย", "sum")}).reset_index()


def export(frame):
    return excel_bytes({"สรุปตามสิทธิ": summary(frame), "สรุปตามชีต": sheet_summary(frame), "รายละเอียด": frame})


def reconcile(statement, services):
    """Match a service list to paid NDP statement rows by PID/date, then name/date."""
    if services is None or services.empty:
        return pd.DataFrame()
    paid = statement.copy()
    paid["_day"] = paid["วันที่รับบริการ"].map(service_date)
    paid["_pid"] = paid["PID"].map(identifier)
    paid["_name"] = paid["ชื่อผู้รับบริการ"].map(lambda x: re.sub(r"\s+", "", clean_text(x)).casefold())
    by_pid_day = {}
    by_name_day = {}
    for idx, row in paid.iterrows():
        if row["_pid"] and row["_day"] is not None:
            by_pid_day.setdefault((row["_pid"], row["_day"]), []).append(idx)
        if row["_name"] and row["_day"] is not None:
            by_name_day.setdefault((row["_name"], row["_day"]), []).append(idx)
    rows = []
    for _, service in services.iterrows():
        pid = identifier(service.get("pid", ""))
        day = service.get("service_date")
        name = re.sub(r"\s+", "", clean_text(service.get("patient_name", ""))).casefold()
        hits = by_pid_day.get((pid, day), []) if pid and day is not None else []
        method = "PID + วันที่" if hits else ""
        if not hits and name and day is not None:
            hits = by_name_day.get((name, day), [])
            method = "ชื่อ-สกุล + วันที่" if hits else ""
        if hits:
            matched = paid.loc[hits]
            rows.append({"PID": pid, "ชื่อผู้รับบริการ": service.get("patient_name", ""), "วันที่รับบริการ": day,
                         "สถานะ": "ชดเชยแล้ว", "วิธีจับคู่": method, "จำนวนรายการ": len(matched),
                         "ยอดชดเชย": matched["ยอดชดเชย"].sum(), "REP_NO": ", ".join(sorted(set(matched["REP_NO"].astype(str)))),
                         "ชีต": ", ".join(sorted(set(matched["ชีต"].astype(str))))})
        else:
            rows.append({"PID": pid, "ชื่อผู้รับบริการ": service.get("patient_name", ""), "วันที่รับบริการ": day,
                         "สถานะ": "ไม่พบใน Statement", "วิธีจับคู่": "", "จำนวนรายการ": 0,
                         "ยอดชดเชย": 0.0, "REP_NO": "", "ชีต": ""})
    return pd.DataFrame(rows)

