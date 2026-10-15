"""Summaries of user-reviewed service labels. Never infer a service from price."""
import re
import pandas as pd
from dashboard.data import clean_text

VERSION = 1
HERBAL_WORDS = ("ขมิ้น", "อบเช", "ไพล", "ไพรป้อม", "ขามป้อม", "ขามแขก", "มะแว้ง", "แว้ง",
                "ฟ้าทะลาย", "มะระ", "ยาประคบ", "สหัสธารา", "เถาวัล", "เถา+", "หอมนว", "เขียวหอม",
                "เหลืองปิด", "ว่านหาง", "ขิง", "ประสะ", "ปราชมภู", "ธาตุอบ", "ป้อม+")
AMOUNTS = ["HC", "HC-DRUG", "PP", "FS", "OP", "ยอดชดเชยทั้งสิ้น"]


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
