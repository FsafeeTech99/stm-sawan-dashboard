"""Summaries of user-reviewed service labels. Never infer a service from price."""
import re
import pandas as pd
from dashboard.data import clean_text

VERSION = 2
HERBAL_WORDS = ("ขมิ้น", "อบเช", "ไพล", "ไพรป้อม", "ขามป้อม", "ขามแขก", "มะแว้ง", "แว้ง",
                "ฟ้าทะลาย", "มะระ", "ยาประคบ", "สหัสธารา", "เถาวัล", "เถา+", "หอมนว", "เขียวหอม",
                "เหลืองปิด", "ว่านหาง", "ขิง", "ประสะ", "ปราชมภู", "ธาตุอบ", "ป้อม+")
AMOUNTS = ["HC", "HC-DRUG", "PP", "FS", "OP", "ยอดชดเชยทั้งสิ้น"]


def is_walkin_project(value):
    value = clean_text(value).upper()
    if re.search(r"(?:NO|NON|NOT)[\s_-]*WALK[\s_-]*IN", value):
        return False
    return bool(re.search(r"(?<![A-Z])WALK[\s_-]*IN(?![A-Z])", value))


def walkin_status_summary(rows):
    """Summary for FS/Walk-in, using PROJCODE and preserving all pay columns."""
    if rows.empty or "PROJCODE" not in rows:
        return {"รายการ": 0, "คนไม่ซ้ำ": 0, "ชดเชย": 0, "ชดเชยบาท": 0.0,
                "หักคืน": 0, "หักคืนบาท": 0.0, "ศูนย์": 0, "สุทธิบาท": 0.0}
    selected = rows.loc[rows["PROJCODE"].map(is_walkin_project)].copy()
    total = selected.get("ยอดชดเชยทั้งสิ้น", pd.Series(dtype="Float64"))
    pid = selected.get("PID", pd.Series("", index=selected.index)).map(clean_text)
    valid_pid = pid.str.fullmatch(r"\d{13}")
    return {"รายการ": int(len(selected)), "คนไม่ซ้ำ": int(pid.loc[valid_pid].nunique()),
            "ชดเชย": int(total.gt(0).sum()), "ชดเชยบาท": float(total.clip(lower=0).sum()) / 100,
            "หักคืน": int(total.lt(0).sum()), "หักคืนบาท": float(total.clip(upper=0).sum()) / 100,
            "ศูนย์": int(total.eq(0).sum()), "สุทธิบาท": float(total.sum()) / 100}


def service_group(row):
    name = clean_text(row.get("บริการ")) or "ยังไม่ระบุบริการ"
    compact = re.sub(r"\s+", "", name).casefold()
    if compact in {"fittest", "fit-test"}:
        return "FIT test"
    if compact == "tele":
        return "Tele"
    herbal = any(word in compact for word in HERBAL_WORDS)
    amount = row.get("HC-DRUG")
    herbal = herbal or (pd.notna(amount) and amount != 0)
    if herbal:
        # Mixed visits retain their label. Do not allocate their whole payout
        # to herbs when OP, PP, FS or HC also pays on this row.
        others = any(pd.notna(row.get(c)) and row.get(c) != 0 for c in ["HC", "PP", "FS", "OP"])
        mixed_text = bool(re.search(r"tele|walk[\s-]*in|\bfpg\b|fit[\s-]*test|hct", name, re.I))
        if others or mixed_text:
            return "สมุนไพรร่วมหมวดอื่น / ตรวจสอบ: " + name
        return "สมุนไพร"
    return name


def summarize_services(rows, by_price=False):
    """Rows are claim lines, not unique patients. Values are integer satang."""
    if rows.empty:
        return pd.DataFrame()
    source = rows.copy()
    source["กลุ่มบริการ"] = source.apply(service_group, axis=1)
    keys = ["กลุ่มบริการ"] + (["ยอดชดเชยทั้งสิ้น"] if by_price else [])
    records = []
    for key, group in source.groupby(keys, dropna=False, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        total = group["ยอดชดเชยทั้งสิ้น"]
        rec = {"กลุ่มบริการ": key[0]}
        if by_price:
            rec["ชดเชยต่อรายการ (บาท)"] = None if pd.isna(key[1]) else int(key[1]) / 100
        rec.update({"จำนวนรายการ": len(group), "ยอดบวก (บาท)": int(total.dropna().clip(lower=0).sum()) / 100,
                    "ยอดติดลบ (บาท)": int(total.dropna().clip(upper=0).sum()) / 100,
                    "รายการยอดศูนย์": int(total.eq(0).sum()), "รายการไม่ทราบยอด": int(total.isna().sum())})
        for col in AMOUNTS:
            values = group[col] if col in group else pd.Series([None] * len(group))
            rec[col + " (บาท)"] = None if values.isna().any() else int(values.sum()) / 100
        records.append(rec)
    return pd.DataFrame(records)
