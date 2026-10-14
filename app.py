from __future__ import annotations

import html
import importlib
import os
import time
from io import BytesIO

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.auth import LoginThrottle, hash_password, registered_users, verify_password
from dashboard.registry import DEVELOPER_CREDIT, account_code
from dashboard import breakdown as bd
from dashboard import jhcis as jc
from dashboard import local_jhcis as lj
from dashboard import clinical_input as ci
from dashboard import focus_ui as fu
from dashboard import data as data_module
# Streamlit may rerun app.py while imported modules from the prior release
# remain cached. Refresh these changed schemas once, before importing functions.
if not hasattr(data_module, "FOCUS_SCHEMA_VERSION"):
    importlib.reload(data_module)
if "HC-DRUG" not in bd.FOCUS:
    importlib.reload(bd)
import hashlib
from dashboard.data import (
    BUDGET_AMOUNTS, CATEGORY_COLUMNS, DISPLAY_NAMES, DEFAULT_DIRECTORY, NAME_COLUMNS, PERIOD_COLUMNS,
    STM_AMOUNTS, STM_COLUMNS, category_summary, combine_records, content_hash, details, excel_bytes, filter_records,
    first_column, money, normalize_code, prepare_records, read_workbook, reconcile, restrict_to_facility, signed_totals, summarize,
)

st.set_page_config(page_title="KhamTechReCheck • งบพึงรับ & STM", page_icon="🏥", layout="wide")
st.markdown("""
<style>
 .stApp {background:linear-gradient(180deg,#edf5f8 0,#f7f9fc 420px);color:#163946;}
 [data-testid="stSidebar"] {background:#f0f5f8; border-right:1px solid #dce7eb;}
 .block-container {padding-top:2rem;padding-bottom:3rem;max-width:1550px;}
 .hero {background:radial-gradient(ellipse at 90% 0%,#167e85 0,transparent 65%),linear-gradient(115deg,#102f49,#104c60);padding:32px 36px;
   border-radius:24px;margin-bottom:24px;color:white;box-shadow:0 14px 32px #103f4c19;border:1px solid #ffffff25;}
 .hero h1 {font-size:clamp(2rem,4.2vw,3.1rem);font-weight:800;color:white;margin:6px 0 18px;line-height:1.2;letter-spacing:-.025em;}
 .hero p {color:#d2e8ea;margin:0;font-size:.94rem;}
 .eyebrow {font-size:.75rem;letter-spacing:.14em;color:#8ce4cd;font-weight:700;}
 [data-testid="stMetric"] {background:white;border:1px solid #dce7eb;border-radius:16px;padding:18px 20px;}
 [data-testid="stMetricValue"] {color:#125f67;font-size:1.7rem;}
 [data-testid="stTabs"] button {font-weight:600;}
 .step {background:white;padding:20px;border:1px solid #dce7eb;border-radius:15px;height:155px;}
 .step strong {color:#166a70;font-size:1rem;} .step p {font-size:.92rem;margin-top:12px;}
 .stButton button, .stDownloadButton button {border-radius:10px;}
 .stButton button:hover,.stDownloadButton button:hover {transform:translateY(-1px);box-shadow:0 5px 16px #103f4c12;}
 [data-testid="stTabs"] [role="tablist"] {gap:8px;padding:6px;background:#e8eff4;border-radius:14px;margin-bottom:22px;}
 [data-testid="stTabs"] [role="tab"] {border-radius:10px;padding:10px 18px;height:auto;}
 [data-testid="stTabs"] [aria-selected="true"] {background:#fff;color:#12676c;box-shadow:0 2px 6px #103f4c12;}
 .section-kicker {font-size:.72rem;letter-spacing:.14em;font-weight:800;color:#52758a;margin:18px 0 10px;}
 .money-grid {display:grid;grid-template-columns:1.35fr repeat(4,1fr);gap:12px;margin:16px 0;}
 .money-card {background:#fff;border:1px solid #e1e9ee;border-top:4px solid var(--accent);border-radius:16px;padding:19px 17px;box-shadow:0 5px 16px #123f4c06;transition:transform .15s;}
 .money-card:hover {transform:translateY(-3px);}
 .money-card span {display:block;font-weight:750;font-size:.96rem;color:var(--accent);}
 .money-card strong {display:block;font-size:clamp(1.25rem,2vw,2rem);font-weight:800;color:#153b4e;letter-spacing:-.04em;margin:9px 0;}
 .money-card small {display:block;font-size:.72rem;color:#5b7081;min-height:30px;}
 .money-card em {display:block;font-style:normal;font-size:.7rem;color:#65798a;margin-top:9px;}
 .money-card.navy {--accent:#123f5b;background:#123f5b;}
 .money-card.navy span,.money-card.navy strong {color:white;}
 .money-card.navy small,.money-card.navy em {color:#bfdbed;}
 .teal {--accent:#0891b2;} .green {--accent:#059669;} .purple {--accent:#7c3aed;} .amber {--accent:#d97706;}
 .followup-banner {background:#fff8eb;border:1px solid #f0dcb6;border-left:5px solid #d97706;border-radius:14px;padding:18px 22px;margin:18px 0 10px;}
 .followup-banner b {display:block;color:#8c4e14;margin-bottom:8px;}
 .followup-banner span {font-size:.94rem;color:#75562e;} .followup-banner strong {font-size:1.15rem;}
 [data-testid="stDataFrame"] {border-radius:12px;overflow:hidden;}
 [data-testid="stForm"] {border-color:#dce7eb;border-radius:16px;background:#ffffff80;}
 @media(max-width:1000px) {.money-grid {grid-template-columns:repeat(2,minmax(0,1fr));}.money-card.navy{grid-column:1/-1;}}
 @media(max-width:550px) {.hero {padding:22px;}.money-card{padding:14px;}.block-container{padding-left:1rem;padding-right:1rem;}}
 @media(prefers-reduced-motion:reduce) {.money-card,.stButton button,.stDownloadButton button{transition:none;transform:none!important;}}
</style>
""", unsafe_allow_html=True)


def hero():
    st.markdown("""<div class="hero"><div class="eyebrow">เครือข่ายบริการสุขภาพ อ.สว่างแดนดิน</div>
    <h1>KhamTechReCheck</h1>
    <p>ตรวจยอดชดเชยให้ชัด • HC & สมุนไพร · PP · FS · Walk-in</p>
    <p>เครือข่ายบริการสุขภาพ อ.สว่างแดนดิน · รพร.สว่างแดนดิน 11450 · รพ.สต. สังกัด อบจ.สกลนคร</p></div>""", unsafe_allow_html=True)


@st.cache_resource
def login_resources():
    # Only throttle and dummy hash are shared; uploaded Excel is session-local.
    return LoginThrottle(), hash_password("unused-dummy-password")


def users_config():
    try:
        overrides = dict(st.secrets.get("auth", {}).get("users", {}))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        overrides = {}
    return registered_users(overrides)


def clear_session():
    for key in list(st.session_state):
        del st.session_state[key]


def authenticate() -> tuple[str, bool]:
    users = users_config()
    now = time.time()
    if st.session_state.get("user") in users:
        if now - st.session_state.get("last_activity", 0) < 1800:
            st.session_state.last_activity = now
            return str(users[st.session_state.user].get("display_name", st.session_state.user)), False
        clear_session()
        st.warning("หมดเวลาใช้งานหลังไม่มีการทำรายการ 30 นาที กรุณาเข้าสู่ระบบอีกครั้ง")
    elif st.session_state.get("user"):
        clear_session()
    if st.session_state.get("demo"):
        return "ผู้เยี่ยมชม · ข้อมูลจำลอง", True
    hero()
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.subheader("เข้าสู่ระบบสำหรับเจ้าหน้าที่")
        st.caption("อัปโหลดไฟล์ ตรวจยอดรายหน่วยบริการ และส่งออกข้อมูลที่กรองแล้ว")
        st.info("ใช้ชื่อผู้ใช้ Admin ตามด้วยรหัสหน่วยบริการ 5 หลัก เช่น Admin05542 รหัสผ่านเริ่มต้นคือรหัสหน่วยบริการ 5 หลัก ระบบแสดงข้อมูลเฉพาะหน่วยบริการของบัญชี")
        with st.form("login"):
            username = st.text_input("ชื่อผู้ใช้", placeholder="Admin05542")
            password = st.text_input("รหัสผ่าน", type="password")
            submitted = st.form_submit_button("เข้าสู่ระบบ", type="primary", width="stretch", disabled=not users)
        if submitted:
            throttle, dummy = login_resources()
            account = username.strip()
            bucket = account if account in users else "__unknown__"
            if not throttle.allowed(bucket):
                st.error("พยายามเข้าสู่ระบบเกินกำหนด กรุณารอ 5 นาที")
            else:
                config = users.get(account, {})
                valid = verify_password(password, config.get("password_hash", dummy))
                if valid and account in users:
                    throttle.reset(bucket)
                    st.session_state.user = account
                    st.session_state.last_activity = now
                    st.rerun()
                throttle.failed(bucket)
                st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        if st.button("ดู Dashboard ด้วยข้อมูลจำลอง", width="stretch"):
            st.session_state.demo = True
            st.rerun()
    with right:
        st.subheader("รวมยอดให้ตรวจสอบได้ง่าย")
        st.markdown("""
        - งบพึงรับแยกตาม HSUB และหน่วยบริการ
        - STM รองรับหัวรายงานและรหัสที่เลขศูนย์หาย
        - เปรียบเทียบงวดเดียวกัน พร้อมรายการที่ยังจับคู่ไม่ได้
        - Excel พร้อมตารางสรุปและข้อมูลอ้างอิงไฟล์ต้นทาง
        """)
        st.caption("โหมดตัวอย่างใช้ข้อมูลสมมติเท่านั้น และไม่เปิดให้อัปโหลดไฟล์จริง")
        with st.expander("รายชื่อหน่วยบริการที่เข้าใช้งานได้ · 19 แห่ง"):
            st.dataframe(pd.DataFrame(DEFAULT_DIRECTORY.items(), columns=["รหัส", "ชื่อหน่วยบริการ"]), hide_index=True, width="stretch")
    st.caption(DEVELOPER_CREDIT)
    st.stop()


def demo_workbooks():
    budget = pd.DataFrame({"HSUB": [5542, 5542, 5555],
                           "HCODE": [5542, 5542, 5555], "HCODE_PAID": [11450] * 3,
                           "REP": ["DEMO-001"] * 3, "TRAN_ID": ["BUD-001", "BUD-002", "BUD-003"],
                           "ชื่อหน่วยบริการ": ["รพ.สต.คำสะอาด", "รพ.สต.คำสะอาด", "รพ.สต.บ้านตาลโกน"],
                           "งวด": ["2569-09"] * 3, "ยอดชดเชยทั้งสิ้น": [200, 60, 400],
                           "PP": [80, 60, 360], "HC": [120, 0, 0], "DRUG": [0, 0, 40],
                           "PROJCODE": ["WALKIN", "PPFS", "WALK-IN"]})
    stm = pd.DataFrame({"REP": ["DEMO-001"] * 3, "TRAN_ID": ["SIM-001", "SIM-002", "SIM-003"],
                        "HN": ["00001", "00002", "00003"], "HCODE": [11450] * 3,
                        "HSUB": [5542, 5542, 5555], "งวด": ["2569-09"] * 3,
                        "ชื่อ-นามสกุล": ["ผู้รับบริการสมมติ ก", "ผู้รับบริการสมมติ ข", "ผู้รับบริการสมมติ ค"],
                        "ยอดชดเชยทั้งสิ้น": [180, 60, 380], "PP": [80, 60, 320],
                        "HC": [100, 0, 0], "DRUG": [0, 0, 60], "PROJCODE": ["WALKIN", "PPFS", "WALK-IN"]})
    result = []
    for group, frame in (("budget", budget), ("stm", stm)):
        for col in CATEGORY_COLUMNS:
            if col not in frame:
                frame[col] = 0
        extras = [c for c in frame if c not in STM_COLUMNS]
        frame = frame.reindex(columns=STM_COLUMNS + extras)
        frame.columns = [c.split("__")[0] for c in frame.columns]
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame([['รายงานตัวอย่าง สปสช.'], ['ข้อมูลสมมติ ไม่มีผู้ป่วยจริง']]).to_excel(writer, index=False, header=False)
            frame.to_excel(writer, index=False, startrow=7)
        result.append((group, f"ตัวอย่าง_{group}.xlsx", output.getvalue()))
    return result


def load_group(uploads, group, demo=False):
    parsed, errors, duplicates = [], [], []
    seen = set()
    active_cache_keys = set()
    for filename, content in uploads:
        digest = content_hash(content)
        if digest in seen:
            duplicates.append(filename)
            continue
        seen.add(digest)
        with st.sidebar.expander(f"ตั้งค่าหัวตาราง · {filename}", expanded=False):
            automatic = st.checkbox("ตรวจหัวตารางอัตโนมัติ", value=True, disabled=demo, key=f"auto_{group}_{digest}")
            override = None
            if not automatic:
                override = int(st.number_input("เลขแถวหัวตาราง (เริ่มที่ 1)", min_value=1, max_value=500,
                                               value=8, key=f"header_{group}_{digest}")) - 1
        key = f"parsed_{group}_{filename}_{digest}_{override}"
        active_cache_keys.add(key)
        # Session cache avoids cross-user caching of patient data.
        if key not in st.session_state:
            try:
                st.session_state[key] = read_workbook(content, filename, override)
            except Exception as exc:
                errors.append(f"{filename}: อ่านไฟล์ไม่สำเร็จ ({type(exc).__name__}) กรุณาตรวจว่าไฟล์ไม่เสียหายหรือมีรหัสผ่าน")
                continue
        sheets, sheet_errors = st.session_state[key]
        parsed.extend(sheets)
        errors.extend(sheet_errors)
    for key in list(st.session_state):
        if key.startswith(f"parsed_{group}_") and key not in active_cache_keys:
            del st.session_state[key]
    return parsed, errors, duplicates


def mapped_group(parsed_sheets, group, directory, demo, scope=None):
    frames, audits, warnings = [], [], []
    label = "งบพึงรับ" if group == "budget" else "STM"
    for parsed in parsed_sheets:
        df = parsed.frame
        columns = [c for c in df.columns if not c.startswith("_")]
        auto_facility = first_column(df, ["HSUB", "HCODE"])
        auto_amount = first_column(df, BUDGET_AMOUNTS if group == "budget" else STM_AMOUNTS)
        auto_name = first_column(df, NAME_COLUMNS)
        auto_period = first_column(df, PERIOD_COLUMNS)
        key = f"map_{group}_{parsed.filename}_{parsed.sheet}_{parsed.header_row}"
        with st.sidebar.expander(f"จับคู่คอลัมน์ {label} · {parsed.filename} / {parsed.sheet}", expanded=not auto_amount):
            st.caption(f"หัวตารางแถว {parsed.header_row} · {len(df):,} รายการ")
            options = ["— เลือกคอลัมน์ —"] + columns
            facility = st.selectbox("คอลัมน์รหัส รพ.สต.", options,
                                    index=options.index(auto_facility) if auto_facility else 0, key=key + "_code", disabled=demo or bool(scope))
            if scope:
                facility = auto_facility
            amount = st.selectbox("คอลัมน์ยอดเงิน (บาท)", options,
                                  index=options.index(auto_amount) if auto_amount else 0, key=key + "_amount", disabled=demo)
            optional = ["— ไม่ใช้ —"] + columns
            name = st.selectbox("ชื่อหน่วยบริการ", optional, index=optional.index(auto_name) if auto_name else 0, key=key + "_name", disabled=demo)
            period = st.selectbox("คอลัมน์งวดข้อมูล / REP", optional, index=optional.index(auto_period) if auto_period else 0, key=key + "_period", disabled=demo)
            manual_period = st.text_input("กำหนดงวดให้ทั้งชีต (แทนค่าคอลัมน์งวด)",
                                          placeholder="เช่น 2569-09", key=key + "_manual", disabled=demo)
        if facility not in columns or amount not in columns:
            warnings.append(f"{parsed.filename} / {parsed.sheet}: ยังไม่ได้เลือกคอลัมน์รหัสและยอดเงิน ไม่รวมชีตนี้ในการสรุป")
            continue
        records, audit = prepare_records(parsed, facility, amount, name if name in columns else None,
                                         period if period in columns else None, manual_period, directory)
        if scope:
            records = restrict_to_facility(records, scope)
            # Import diagnostics exported to the user concern their unit only.
            audit["รายการ"] = len(records)
            audit["รหัสไม่ถูกต้อง"] = int(records["_facility"].eq("").sum())
            audit["ยอดเงินว่าง/ไม่ถูกต้อง"] = int(records["_cents"].isna().sum())
            audit["ไม่มีงวด"] = int(records["_period"].eq("ยังไม่ระบุงวด").sum())
        frames.append(records)
        audits.append({"ประเภท": label, **audit})
        warnings.extend(f"{parsed.filename} / {parsed.sheet}: {w}" for w in parsed.warnings)
        if facility == "HCODE" and "HCODE_PAID" in df:
            warnings.append(f"{parsed.filename} / {parsed.sheet}: ใช้ HCODE ของผู้ให้บริการสรุปพึงรับ ส่วน HCODE_PAID เป็นหน่วยรับโอนเงิน ไม่ใช้แทนรหัส รพ.สต.")
        elif facility != "HSUB":
            warnings.append(f"{parsed.filename} / {parsed.sheet}: รวมยอดตาม {facility} กรุณายืนยันว่าเป็นรหัส รพ.สต. ไม่ใช่รหัสแม่ข่าย")
    return frames, audits, warnings


def download(label, sheets, filename, key):
    st.download_button(label, excel_bytes(sheets), file_name=filename,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=key, width="stretch")


def amount_total(frame):
    return int(frame.loc[frame["_valid"], "_cents"].sum()) / 100 if not frame.empty else 0


def quality_table(frame):
    if frame.empty:
        return pd.DataFrame()
    cols = {"_source_file": "ไฟล์", "_source_sheet": "ชีต", "_source_row": "แถว",
            "_facility": "รหัสหน่วยบริการ", "_period": "งวด", "_issue": "ปัญหา"}
    return frame.loc[~frame["_valid"], list(cols)].rename(columns=cols)


def source_table(frame):
    cols = {"_source_file": "ไฟล์", "_source_sheet": "ชีต", "_source_row": "แถว",
            "_facility": "รหัสหน่วยบริการ", "_facility_name": "ชื่อหน่วยบริการ",
            "_period": "งวด", "_issue": "ปัญหา"}
    return frame.reindex(columns=cols).rename(columns=cols)


def dataset_tab(frame, group, audits, uploaded_count):
    label = "ยอดพึงรับ รพ.สต." if group == "budget" else "ยอดชดเชย STM"
    if frame.empty:
        st.info(f"ยังไม่มีรายการ{label}ตรงกับตัวกรอง กรุณาอัปโหลดไฟล์หรือปรับตัวกรอง")
        return
    summary = summarize(frame)
    cols = st.columns(4)
    cols[0].metric(label, f"{amount_total(frame):,.2f}", "บาท", delta_color="off")
    cols[1].metric("หน่วยบริการ", f"{summary['รหัสหน่วยบริการ'].nunique():,}")
    cols[2].metric("รายการที่รวมยอด", f"{int(frame['_valid'].sum()):,}")
    cols[3].metric("ไฟล์ในผลกรอง", f"{frame['_source_file'].nunique():,} / {uploaded_count}")
    fu.brief(frame, group)
    claim_like = "TRAN_ID" in frame or "ยอดชดเชยทั้งสิ้น" in frame
    components = None
    if claim_like:
        positive, negative = signed_totals(frame)
        headline = category_summary(frame, columns=["PP"])
        money_cols = st.columns(3)
        money_cols[0].metric("ยอดชดเชยบวก", f"{positive:,.2f}", "บาท", delta_color="off")
        money_cols[1].metric("ยอดปรับลด / เรียกคืน", f"{negative:,.2f}", "บาท", delta_color="off")
        pp = None if headline.empty or headline["PP"].isna().any() else headline["PP"].sum()
        money_cols[2].metric("PP สุทธิ", "ไม่มีข้อมูลครบ" if pp is None else f"{pp:,.2f}", "บาท", delta_color="off")
        st.subheader("ชดเชยราย รพ.สต. แยกหมวดเงิน")
        if group == "budget":
            st.caption("รวมไฟล์พึงรับ รพ.สต. 19–21 ไฟล์ตามหัวตารางตัวอย่าง ใช้ HSUB หรือ HCODE ของผู้ให้บริการ")
        chosen = st.multiselect("หมวดเงินที่ต้องการดู", CATEGORY_COLUMNS,
                               default=["OP", "ยอดชดเชยที่จ่ายจริง", "HC", "DRUG", "AE", "DRUG__2", "INST", "ยอดชดเชยที่จ่ายจริง__2", "DMIS_DRUG", "Palliative care", "DMISHD", "PP", "FS"],
                               format_func=lambda c: DISPLAY_NAMES.get(c, c), key=f"categories_{group}")
        split_period = st.checkbox("แยกยอดหมวดเงินตามงวด / REP", value=False, key=f"split_categories_{group}")
        components = category_summary(frame, split_period, chosen)
        st.dataframe(components, hide_index=True, width="stretch")
        st.caption("ยอดชดเชยทั้งสิ้นใช้คอลัมน์ยอดรวมจากไฟล์ ไม่บวกหมวดเข้าด้วยกัน เพราะบางคอลัมน์เป็นยอดย่อย/ยอดคำนวณที่ซ้อนกัน ค่าว่างแสดงว่าไม่มีข้อมูลหมวดนั้นครบ")
        nonzero = []
        for col in chosen:
            name = DISPLAY_NAMES.get(col, col)
            values = components[name]
            if not values.empty and values.notna().all() and values.abs().sum() > 0:
                nonzero.append({"หมวดเงิน": name, "บาท": values.sum()})
        if nonzero:
            chart = alt.Chart(pd.DataFrame(nonzero)).mark_bar(color="#eba74c", cornerRadiusEnd=4).encode(
                x=alt.X("บาท:Q"), y=alt.Y("หมวดเงิน:N", sort="-x", title=None),
                tooltip=["หมวดเงิน", alt.Tooltip("บาท:Q", format=",.2f")],
            ).properties(height=max(160, len(nonzero) * 32))
            st.altair_chart(chart, width="stretch")
    st.subheader("ยอดสรุปแยกหน่วยบริการและงวด")
    if not summary.empty:
        chart_df = summary.groupby(["รหัสหน่วยบริการ", "ชื่อหน่วยบริการ"], as_index=False)["ยอดเงิน"].sum()
        chart_df["หน่วยบริการ"] = chart_df["รหัสหน่วยบริการ"] + " · " + chart_df["ชื่อหน่วยบริการ"]
        chart = alt.Chart(chart_df).mark_bar(color="#1c8c87", cornerRadiusEnd=5).encode(
            x=alt.X("ยอดเงิน:Q", title="บาท"), y=alt.Y("หน่วยบริการ:N", sort="-x", title=None),
            tooltip=["รหัสหน่วยบริการ", "ชื่อหน่วยบริการ", alt.Tooltip("ยอดเงิน:Q", format=",.2f")],
        ).properties(height=max(170, min(650, len(chart_df) * 38)))
        st.altair_chart(chart, width="stretch")
    st.dataframe(summary, hide_index=True, width="stretch")
    st.subheader("รายละเอียดรายการที่กรองแล้ว")
    table = details(frame, group)
    if group == "stm" or claim_like:
        st.caption("คอลัมน์ตามแบบที่กำหนด · (2) คือคอลัมน์ชื่อซ้ำลำดับที่สอง · คอลัมน์ไม่มีในไฟล์จะแสดงค่าว่าง")
    st.dataframe(table, hide_index=True, width="stretch")
    issues = quality_table(frame)
    if not issues.empty:
        st.warning(f"{len(issues):,} รายการไม่ถูกรวมยอด เนื่องจากรหัสหรือยอดเงินไม่ถูกต้อง")
        st.dataframe(issues, hide_index=True, width="stretch")
    export_sheets = {
        "สรุปรายหน่วยบริการ": summary,
        "รายละเอียด": table.rename(columns={v: k.split("__")[0] for k, v in DISPLAY_NAMES.items()}),
        "อ้างอิงรายการ": source_table(frame), "ตรวจการนำเข้า": pd.DataFrame(audits),
    }
    if components is not None:
        export_sheets = {"พึงรับแยกหมวด" if group == "budget" else "STM แยกหมวด": components, **export_sheets}
    download(f"ดาวน์โหลด {label} ตามตัวกรอง · Excel", export_sheets, f"sawan_{group}_filtered.xlsx", group + "_export")
    st.caption("ชีตตรวจการนำเข้าแสดงข้อมูลทั้งชุดไฟล์ ส่วนสรุป รายละเอียด และอ้างอิงรายการใช้ตัวกรองปัจจุบัน")


def comparison_tab(budget, stm):
    if budget.empty and stm.empty:
        st.info("อัปโหลดงบพึงรับและ STM เพื่อเปรียบเทียบรายหน่วยบริการ")
        return
    comparison = reconcile(budget, stm)
    st.info("ผลต่างรอตรวจสอบ = งบพึงรับ − ยอดชดเชย STM เฉพาะหน่วยบริการและงวดที่จับคู่ได้ ยังไม่ใช่หลักฐานยอดโอนเงินจริงหรือยอดค้างจ่ายที่ยืนยันแล้ว")
    valid = comparison["ผลต่างรอตรวจสอบ"].notna()
    cols = st.columns(3)
    cols[0].metric("ผลต่างสุทธิที่จับคู่ได้", f"{comparison.loc[valid, 'ผลต่างรอตรวจสอบ'].sum():,.2f}", "บาท", delta_color="off")
    cols[1].metric("พึงรับสูงกว่า STM", f"{comparison['ผลต่างรอตรวจสอบ'].clip(lower=0).sum():,.2f}", "บาท", delta_color="off")
    cols[2].metric("หน่วยบริการ/งวดที่ยังจับคู่ไม่ได้", f"{int((~valid).sum()):,}")
    statuses = st.multiselect("สถานะที่ต้องการติดตาม", sorted(comparison["สถานะ"].unique()), key="status_filter")
    if statuses:
        comparison = comparison.loc[comparison["สถานะ"].isin(statuses)]
    if valid.any():
        chart_df = comparison.loc[comparison["ผลต่างรอตรวจสอบ"].notna()].melt(
            id_vars=["รหัสหน่วยบริการ", "ชื่อหน่วยบริการ", "งวด"], value_vars=["งบพึงรับ", "ยอดชดเชย STM"],
            var_name="ประเภท", value_name="บาท")
        if not chart_df.empty:
            chart_df["หน่วยบริการ / งวด"] = chart_df["รหัสหน่วยบริการ"] + " · " + chart_df["งวด"]
            chart = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4).encode(
                x=alt.X("บาท:Q"), y=alt.Y("หน่วยบริการ / งวด:N", title=None),
                yOffset="ประเภท:N", color=alt.Color("ประเภท:N", scale=alt.Scale(range=["#176e74", "#eba74c"])),
                tooltip=["ชื่อหน่วยบริการ", "งวด", "ประเภท", alt.Tooltip("บาท:Q", format=",.2f")],
            ).properties(height=max(200, min(700, len(chart_df) * 26)))
            st.altair_chart(chart, width="stretch")
    st.dataframe(comparison, hide_index=True, width="stretch")
    download("ดาวน์โหลดผลเปรียบเทียบตามตัวกรอง · Excel", {"ผลเปรียบเทียบ": comparison},
             "sawan_comparison_filtered.xlsx", "comparison_export")


def choose_category(label, key):
    st.session_state[key] = label


def local_clinical(scope):
    st.caption("โหมดเครื่องส่วนตัว • อ่านฐานโดยตรง ไม่ต้องสร้าง clinical view • ค่าเชื่อมต่ออยู่ในเซสชันนี้")
    st.caption("ระบบตรวจตาราง person / visit / visitdiag / visitdrug และคอลัมน์ที่จำเป็นก่อนอ่าน หากโครงสร้างต่างกันจะแจ้งให้ปรับตัวอ่าน")
    with st.form("local_jhcis_connection"):
        st.text_input("รหัสหน่วยบริการ JHCIS", value=scope, disabled=True)
        host = st.text_input("เครื่อง JHCIS / IP หรือปลายทาง tunnel", value="127.0.0.1", key="local_db_host")
        port = st.number_input("พอร์ตฐาน / พอร์ต tunnel", min_value=1, max_value=65535, value=3306, step=1, key="local_db_port")
        database = st.text_input("ชื่อฐานข้อมูล", value="jhcisdb" + scope, key="local_db_name")
        db_user = st.text_input("ผู้ใช้ฐานข้อมูล", value="root", key="local_db_user")
        password = st.text_input("รหัสผ่านฐานข้อมูล JHCIS", type="password", key="local_db_password")
        transport = st.selectbox("ช่องทางเชื่อม", ["เครื่องนี้ / LAN ภายใน", "SSH tunnel ที่เปิดไว้ (localhost)", "Internet พร้อม TLS"], key="local_db_transport")
        dates = st.date_input("วันที่รับบริการจาก JHCIS", value=(pd.Timestamp.today().date().replace(day=1), pd.Timestamp.today().date()), key="local_db_dates")
        submitted = st.form_submit_button("เชื่อมและอ่าน JHCIS แบบ read-only", width="stretch")
    st.caption("ใช้ SELECT เท่านั้น ไม่มีการแก้ฐาน • ฐานบน Internet ที่ไม่เปิด TLS ให้ใช้ SSH tunnel/VPN ภายในก่อน • แนะนำบัญชีฐานที่มีสิทธิอ่าน")
    if submitted:
        st.session_state.pop("clinical_records", None)
        if not host.strip() or not database.strip() or not db_user.strip() or not password or len(dates) != 2:
            st.error("กรอกค่าเชื่อมต่อและช่วงวันที่ให้ครบ")
        else:
            config = {"host": host.strip(), "port": int(port), "database": database.strip(), "user": db_user.strip(),
                      "password": password, "transport": {"เครื่องนี้ / LAN ภายใน": "local", "SSH tunnel ที่เปิดไว้ (localhost)": "ssh", "Internet พร้อม TLS": "tls"}[transport]}
            try:
                with st.spinner("ตรวจโครงสร้างและอ่าน JHCIS…"):
                    records = lj.read_standard(config, scope, *dates)
                st.session_state.clinical_records = (scope, records, dates)
            except Exception as error:
                # A running process can still have the previous module in sys.modules.
                # Never resolve a newly added exception class in an except clause.
                schema_error = getattr(lj, "SchemaMismatch", ())
                formatter = getattr(lj, "user_error_message", None)
                if isinstance(error, schema_error):
                    st.error(str(error))
                elif callable(formatter):
                    st.error(formatter(error))
                else:
                    st.error("เชื่อมฐานไม่ได้ กรุณาตรวจ host/ช่องทางเชื่อม หรือใช้กรอกทีละราย/อัปโหลดข้อมูลบริการ หากเพิ่งอัปเดตโค้ดให้ปิดตัวรันแล้วเปิดใหม่")
            finally:
                config["password"] = None
    if st.button("ล้างข้อมูลและค่าเชื่อม JHCIS", key="local_db_clear"):
        for key in list(st.session_state):
            if key.startswith("local_db_") or key == "clinical_records":
                del st.session_state[key]
        st.rerun()
    loaded = st.session_state.get("clinical_records")
    if loaded and loaded[0] == scope:
        st.success(f"อ่าน {len(loaded[1]):,} visit • {loaded[2][0]} ถึง {loaded[2][1]}")
        female_text = st.text_input("รหัสเพศหญิงในฐานนี้", value="2,F,FEMALE,หญิง", key="local_db_female")
        nation_codes = sorted({str(value) for value in loaded[1].nationality.dropna() if str(value).strip()})
        thai_codes = st.multiselect("เลือกรหัสที่หมายถึงสัญชาติไทยในฐานนี้", nation_codes,
                                    default=[value for value in nation_codes if value in ("ไทย", "TH", "THAI")], key="local_db_thai")
        if not thai_codes:
            st.info("ยังไม่ระบุรหัสสัญชาติไทย จะขึ้นว่าข้อมูลเงื่อนไขสัญชาติยังไม่ครบ")
        return (loaded[1], scope, [value.strip() for value in female_text.split(",") if value.strip()], thai_codes)
    return None


def entered_clinical(scope, mode):
    stored = st.session_state.get("entered_clinical")
    existing = stored[1] if stored and stored[0] == scope else pd.DataFrame(columns=jc.VIEW_COLUMNS + ['_evidence_source'])
    st.caption(f"ข้อมูลบริการของหน่วย {scope} • ใช้ข้อมูลที่ผู้ใช้กรอก/อัปโหลดประกอบการตรวจสอบ ไม่ได้ดึงจากฐาน JHCIS")
    if mode == "กรอกทีละราย":
        st.caption("หนึ่งแบบฟอร์มต่อหนึ่งครั้งรับบริการ • กรอกรหัสวินิจฉัยและยาของครั้งเดียวกัน")
        with st.form("person_service_input", clear_on_submit=True):
            pid = st.text_input("เลขบัตรประชาชน 13 หลัก", key="evidence_pid")
            name = st.text_input("ชื่อ-นามสกุล (ถ้ามี)", key="evidence_name")
            day = st.date_input("วันที่รับบริการ", value=pd.Timestamp.today().date(), key="evidence_day")
            visit = st.text_input("เลขครั้งรับบริการ / visit (ถ้ามี)", key="evidence_visit")
            sex = st.selectbox("เพศ", ["ยังไม่ระบุ", "หญิง", "ชาย"], key="evidence_sex")
            birth = st.date_input("วันเกิด (ถ้ามี)", value=None, min_value=pd.Timestamp('1900-01-01').date(), max_value=pd.Timestamp.today().date(), key="evidence_birth")
            nationality = st.selectbox("สัญชาติ", ["ยังไม่ระบุ", "ไทย", "อื่น ๆ"], key="evidence_nation")
            icd = st.text_input("ICD-10 ของครั้งนี้", placeholder="เช่น Z13.0; Z30.0", key="evidence_icd")
            drug = st.text_input("drugcode ของครั้งนี้", placeholder="เช่น 14001; 12345", key="evidence_drug")
            add = st.form_submit_button("เพิ่มข้อมูลรายนี้", width="stretch")
        if add:
            values = dict(facility=scope, pid=pid, patient_name=name, service_date=day, visit_id=visit,
                          sex='' if sex == 'ยังไม่ระบุ' else sex, birth_date=birth,
                          nationality='' if nationality == 'ยังไม่ระบุ' else nationality, icd10=icd, drugcode=drug)
            try:
                records, notices = ci.manual_record(values, scope)
                for notice in notices:
                    st.warning(notice)
                if not records.empty:
                    existing = ci.merge(existing, records)
                    st.session_state.entered_clinical = (scope, existing)
                    st.success("เพิ่มข้อมูลบริการแล้ว เปิดแท็บรายละเอียดบริการหรือ Walk-in เพื่อเทียบยอด")
            except ValueError as error:
                st.error(str(error))
    else:
        st.caption("หนึ่งแถวต่อหนึ่งครั้งรับบริการ • ใช้เลขบัตร + วันที่เทียบกับพึงรับ/STM • ICD/ยาหลายรหัสคั่นด้วย ; ได้")
        st.download_button("ดาวน์โหลดแม่แบบข้อมูลบริการ", ci.template_bytes(scope), "KhamTechReCheck_service_template.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="clinical_template")
        uploads = st.file_uploader("ข้อมูลบริการรายบุคคลจาก Excel/CSV", type=['xls', 'xlsx', 'csv'], accept_multiple_files=True, key="clinical_uploads")
        declare = st.checkbox(f"ไฟล์ที่ไม่มีรหัสหน่วยบริการเป็นข้อมูลของหน่วย {scope}", key="clinical_declare")
        if st.button("นำเข้าข้อมูลบริการจากไฟล์", key="clinical_import"):
            if not uploads:
                st.info("เลือกไฟล์ข้อมูลบริการก่อน")
            for upload in uploads or []:
                try:
                    content = upload.getvalue()
                    token = hashlib.sha256(content).hexdigest()
                    for sheet, raw in ci.read_file(upload.name, content):
                        records, notices = ci.normalize(raw, scope, f"ผู้ใช้อัปโหลด: {upload.name} / {sheet}", declare, token + sheet)
                        existing = ci.merge(existing, records)
                        st.session_state.entered_clinical = (scope, existing)
                        st.success(f"{upload.name} / {sheet}: นำเข้า {len(records):,} แถว")
                        for notice in notices[:10]:
                            st.warning(notice)
                        if len(notices) > 10:
                            st.warning(f"มีข้อสังเกตอีก {len(notices) - 10:,} แถวที่ยังไม่ได้แสดง")
                except Exception:
                    st.error(f"นำเข้า {upload.name} ไม่สำเร็จ ตรวจหัวตาราง รหัสหน่วย และรูปแบบข้อมูลตามแม่แบบ")
    st.caption("ชื่ออย่างเดียวเสนอรายการให้ตรวจสอบ แต่ไม่ยืนยันตัวตนหรือบริการอัตโนมัติ")
    if st.button("ล้างข้อมูลบริการที่กรอก/อัปโหลด", key="entered_clinical_clear"):
        st.session_state.pop("entered_clinical", None)
        existing = existing.iloc[:0]
    if not existing.empty:
        st.success(f"ข้อมูลบริการในเซสชัน {len(existing):,} แถว")
        preview = existing[['pid', 'service_date', 'visit_id', 'icd10', 'drugcode', '_evidence_source']].copy()
        preview['pid'] = preview.pid.map(lambda value: '*********' + value[-4:] if value else '')
        st.dataframe(preview.rename(columns={**ci.LABELS, '_evidence_source': 'แหล่งข้อมูล'}), hide_index=True, width="stretch")
        st.download_button("ดาวน์โหลดข้อมูลบริการเพื่อใช้ครั้งหน้า", ci.export_bytes(existing), "KhamTechReCheck_entered_services.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="entered_services_export")
        return (existing, scope, ['2', 'F', 'FEMALE', 'หญิง'], ['ไทย', 'TH', 'THAI'])
    return None


def clinical_sidebar(scope, demo):
    with st.expander("ข้อมูลบริการรายบุคคล • กรอก/นำเข้า/ฐาน JHCIS"):
        st.caption("จับคู่เลขบัตร + วันรับบริการ + หน่วยบริการ • ชื่อใช้เสนอให้ตรวจสอบเท่านั้น")
        if demo:
            st.info("โหมดตัวอย่างไม่รับข้อมูลผู้ป่วยจริง")
            return None
        mode = st.radio("วิธีนำเข้าข้อมูลบริการ", ['กรอกทีละราย', 'อัปโหลด Excel/CSV', 'เชื่อมฐาน JHCIS'], key="clinical_input_mode")
        if mode != 'เชื่อมฐาน JHCIS':
            return entered_clinical(scope, mode)
        if os.environ.get("KHAMTECH_LOCAL") == "1":
            if st.get_option("server.address") not in ("127.0.0.1", "localhost", "::1"):
                st.error("โหมดเครื่องส่วนตัวต้อง bind server.address = 127.0.0.1 ตามตัวเปิดโปรแกรม")
                return None
            return local_clinical(scope)
        try:
            config = dict(st.secrets.get("jhcis", {}).get(scope, {}))
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            config = {}
        if not config.get("enabled", False):
            st.info("ยังไม่ได้ตั้งค่าฐาน JHCIS ของหน่วยนี้ ผู้ดูแลต้องตั้ง server Secrets และ clinical view ตามคู่มือ JHCIS_SETUP.md")
            return None
        # Default public facility passwords must not unlock server-held clinical data.
        if verify_password(scope, users_config()[st.session_state.user]["password_hash"]):
            st.warning("ก่อนเชื่อมฐานผู้ป่วย ผู้ดูแลต้องเปลี่ยนรหัสผ่านบัญชีนี้จากรหัสหน่วยบริการใน Secrets")
            return None
        dates = st.date_input("ช่วงวันที่อ่านจาก JHCIS", value=(pd.Timestamp.today().date().replace(day=1), pd.Timestamp.today().date()), key="jhcis_dates")
        if st.button("อ่านข้อมูล JHCIS ตามช่วงวันที่", key="jhcis_read", width="stretch"):
            st.session_state.pop("clinical_records", None)
            if len(dates) != 2:
                st.error("เลือกวันเริ่มต้นและวันสิ้นสุด")
            else:
                try:
                    with st.spinner("กำลังอ่าน clinical view…"):
                        records = jc.read_view(config, scope, *dates)
                    st.session_state.clinical_records = (scope, records, dates)
                except Exception:
                    # Never print connector exceptions: they can contain host/user/SQL.
                    st.error("อ่าน JHCIS ไม่สำเร็จ ตรวจการเชื่อมต่อ สิทธิ SELECT, TLS, clinical view และช่วงวันที่ตามคู่มือ")
        if st.button("ล้างข้อมูล JHCIS ในเซสชัน", key="jhcis_clear"):
            st.session_state.pop("clinical_records", None)
        loaded = st.session_state.get("clinical_records")
        if loaded and loaded[0] == scope:
            st.success(f"อ่าน {len(loaded[1]):,} แถวหลักฐาน • {loaded[2][0]} ถึง {loaded[2][1]}")
            st.caption("เก็บในเซสชันปัจจุบัน อ่านใหม่เมื่อข้อมูล JHCIS เปลี่ยน ไม่แสดงเลขบัตรในตารางผล")
            return (loaded[1], scope, config.get("female_values", ["2", "F", "FEMALE", "หญิง"]), config.get("thai_values", ["ไทย", "TH", "THAI"]))
    return None


def clinical_details(frame, evidence):
    if evidence is None:
        return None
    records, scope, females, thai = evidence
    result = jc.match_claims(frame, records, scope, females, thai).reset_index(drop=True)
    if 'แหล่งข้อมูลบริการ' not in result:
        # Old cached matching modules still return the original five columns.
        sources = sorted(set(records['_evidence_source'].dropna())) if '_evidence_source' in records else ['ฐาน JHCIS']
        result['แหล่งข้อมูลบริการ'] = ('' if not sources else sources[0] if len(sources) == 1 else 'ชุดข้อมูล: ' + ' / '.join(sources))
    return result.rename(columns={name: name.replace('JHCIS', 'ข้อมูลบริการ') for name in result.columns})


def service_tab(datasets, rules, prefix, only_walkin=False, evidence=None):
    labels = {"พึงรับ รพ.สต.": "budget", "Statement สปสช.": "stm"}
    selected = st.selectbox("ชุดข้อมูลที่วิเคราะห์", list(labels),
                            index=1 if datasets["budget"].empty and not datasets["stm"].empty else 0,
                            key=prefix + "_source")
    frame = datasets[labels[selected]]
    if frame.empty:
        st.info("ยังไม่มีรายการตรงตัวกรองในชุดนี้ กรุณาอัปโหลดไฟล์หรือเลือกอีกชุดข้อมูล")
        return
    if only_walkin:
        st.subheader("Walk-in • ยอดและบริการของแต่ละรายการ")
        st.caption("คัดเฉพาะ PROJCODE ที่ระบุ WALKIN, WALK-IN หรือ WALK IN ตามที่ผู้ใช้กำหนด")
        if "PROJCODE" not in frame:
            st.warning("ไฟล์นี้ไม่มี PROJCODE จึงยังระบุ Walk-in ไม่ได้")
            return
        frame = bd.walkin_rows(frame)
        if frame.empty:
            st.info("ไม่พบ PROJCODE ที่ระบุ Walk-in ในผลกรองนี้ ระบบไม่ถือ OP ทั้งหมดเป็น Walk-in")
            return
    fu.workspace(frame, labels[selected], prefix, download)
    # Use the same explicit/per-file mapping in price drill-down and Walk-in.
    resolved = fu.prepared(frame, labels[selected])
    frame = frame.copy()
    frame["HC-DRUG"] = pd.Series(pd.NA, index=frame.index, dtype="Float64")
    own_rows = frame["_facility"].fillna("").ne("")
    frame.loc[own_rows, "HC-DRUG"] = pd.array(resolved["HC-DRUG"], dtype="Float64") / 100
    st.subheader("วิเคราะห์ราคาและหลักฐานประกอบบริการ")
    st.info("ชื่อบริการเป็นการประมาณการจากหมวดและยอดเงิน โดยอ้างอิงภาพราคาปี 2570 ที่ผู้ใช้ให้ ไม่ได้ยืนยันจากรหัสบริการ อายุ หรือสิทธิการรักษา ยอดเงินต้นทางยังคงเดิม")
    overview = st.columns(5)
    overview[0].metric("ยอดรวมจากไฟล์ • " + ("Walk-in" if only_walkin else "ผลกรองนี้"), f"{amount_total(frame):,.2f}", "บาท", delta_color="off")
    category_key = prefix + "_category"
    for column, label in zip(overview[1:], bd.FOCUS):
        total = bd.category_total(frame, label)
        column.metric(label, "ข้อมูลไม่ครบ" if total is None else f"{total:,.2f}", "บาท", delta_color="off")
        column.button(f"ดูรายการ {label}", key=prefix + "_open_" + label,
                      on_click=choose_category, args=(label, category_key), width="stretch")
    st.caption("PP / FS / HC-DRUG / HC เป็นยอดแต่ละคอลัมน์ ไม่เอามาบวกแทนยอดชดเชยทั้งสิ้น เพราะรายงานอาจมียอดย่อยซ้อนกัน จำนวนรายการเป็นแถวใน STM ไม่ใช่จำนวนครั้งบริการที่ยืนยันแล้ว")
    show_names = st.checkbox("แสดงชื่อผู้รับบริการในตารางเจาะรายการ", key=prefix + "_names", value=False)
    if only_walkin:
        table = bd.walkin_table(frame, rules, show_names)
        clinical = clinical_details(bd.valid_rows(frame), evidence)
        if clinical is not None:
            table = pd.concat([table, clinical], axis=1)
        st.write(f"**Walk-in {len(table):,} รายการ** • แยก PP, FS, HC-DRUG และ HC ต่อรายการ")
        st.dataframe(table, hide_index=True, width="stretch")
        download("Export รายการ Walk-in และยอดทั้ง 4 หมวด", {"Walk-in รายรายการ": table},
                 "KhamTechReCheck_walkin.xlsx", prefix + "_walkin_export")
    label = st.radio("คลิกเลือกหมวดบริการ", list(bd.CATEGORIES), key=category_key, horizontal=True)
    st.caption(f"{label} • {bd.CATEGORY_NAMES[label]}")
    summary = bd.amount_summary(frame, label, rules)
    if summary.empty:
        st.info(f"ไม่มีจำนวนเงินที่ไม่เป็นศูนย์ในคอลัมน์ {bd.CATEGORIES[label]} หรือข้อมูลอ่านไม่ได้")
        return
    digest = hashlib.sha256(summary.to_json(orient="split", force_ascii=False).encode()).hexdigest()[:12]
    st.caption("คลิกแถวราคาเพื่อเปิดรายการเบื้องหลัง เช่น PP 80 → หญิงไทยแก้มแดง • PP 60 → FIT test • PP 360 → ANC")
    event = st.dataframe(summary, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"{prefix}_amount_{label}_{digest}")
    picked = event.selection.rows
    picked_cents = None
    if picked and 0 <= picked[0] < len(summary):
        picked_cents = money(summary.iloc[picked[0]]["ยอดต่อรายการ (บาท)"])
    options = ["ทุกยอด"] + summary["ยอดต่อรายการ (บาท)"].map(lambda n: f"{n:,.2f} บาท").tolist()
    # A dropdown supports keyboards/mobile and works even without row selection.
    amount_choice = st.selectbox("เลือกยอดต่อรายการเพื่อเจาะรายละเอียด", options, key=f"{prefix}_price_{label}_{digest}")
    if amount_choice != "ทุกยอด":
        picked_cents = money(amount_choice.replace(" บาท", ""))
    detail_rows = bd.rows_for_amount(frame, label, picked_cents)
    detail = bd.service_details(detail_rows, label, rules, show_names)
    clinical = clinical_details(detail_rows, evidence)
    if clinical is not None:
        detail = pd.concat([detail, clinical], axis=1)
        st.caption("ตรวจข้อมูลบริการตามเงื่อนไขผู้ใช้: หญิง อายุ 13–45 ปี ณ วันรับบริการ, Z13.0, drugcode 14001 และสัญชาติไทยในครั้งเดียวกัน • ดูแหล่งข้อมูลว่าเป็นผู้ใช้กรอก/อัปโหลดหรือฐาน JHCIS • ผลนี้ไม่ใช่การยืนยันสิทธิชดเชยของ สปสช.")
        with st.expander("สรุปหลักฐานบริการของรายการที่เลือก", expanded=True):
            signed = clinical.assign(_amount=detail_rows["_category_cents"].reset_index(drop=True).map(int))
            signed["_positive"] = signed["_amount"].clip(lower=0)
            signed["_negative"] = signed["_amount"].clip(upper=0)
            evidence_summary = signed.groupby(["การจับคู่ ข้อมูลบริการ", "ผลตรวจเงื่อนไข ข้อมูลบริการ"], dropna=False).agg(
                **{"จำนวนรายการ": ("_amount", "size"), "ยอดบวกหมวดที่เลือก (บาท)": ("_positive", "sum"),
                   "ยอดติดลบหมวดที่เลือก (บาท)": ("_negative", "sum"), "ยอดสุทธิหมวดที่เลือก (บาท)": ("_amount", "sum")}).reset_index()
            for column in evidence_summary.columns[3:]:
                evidence_summary[column] = evidence_summary[column] / 100
            st.dataframe(evidence_summary, hide_index=True, width="stretch")
    else:
        st.caption("ยังไม่มีข้อมูลบริการในเซสชันนี้ กรอกทีละรายหรืออัปโหลดที่ sidebar ได้ ชื่อบริการข้างต้นยังเป็นการประมาณการจากราคา")
    positives = sum(int(n) for n in detail_rows["_category_cents"] if n > 0) / 100
    negatives = sum(int(n) for n in detail_rows["_category_cents"] if n < 0) / 100
    metrics = st.columns(4)
    metrics[0].metric(f"รายการ {label} ที่เลือก", f"{len(detail):,}")
    metrics[1].metric("ยอดบวกของหมวดที่เลือก", f"{positives:,.2f}")
    metrics[2].metric("ยอดติดลบของหมวดที่เลือก", f"{negatives:,.2f}")
    metrics[3].metric("ยอดสุทธิของหมวดที่เลือก", f"{positives + negatives:,.2f}")
    st.dataframe(detail, hide_index=True, width="stretch")
    if picked_cents is not None:
        matches = bd.rate_matches(picked_cents, label)
        if not matches.empty:
            with st.expander("เหตุผลที่จับคู่ราคา • บริการและรหัสอ้างอิงที่เป็นไปได้", expanded=True):
                st.dataframe(matches, hide_index=True, width="stretch")
        else:
            st.caption("ไม่พบราคาตรงในภาพอ้างอิง หมวด HC ใช้ชื่อยาสมุนไพรตามผู้ใช้ หรือเพิ่มกฎประมาณการใน sidebar ได้")
    export_tables = {"สรุปราคาหมวดที่เลือก": summary, "รายละเอียดที่เลือก": detail,
             "กฎชื่อประมาณการ": pd.DataFrame([[g, c / 100, name] for (g, c), name in rules.items()],
                                      columns=bd.DEFAULT_RULES.columns), "อัตราอ้างอิงจากภาพ": bd.RATE_DF}
    if clinical is not None:
        export_tables["สรุปหลักฐานบริการ"] = evidence_summary
    download("Export สรุปราคาและรายการที่เลือก", export_tables,
             f"KhamTechReCheck_{label.replace(' ', '_')}_details.xlsx", prefix + "_details_export")


def main():
    user, demo = authenticate()
    scope = None if demo else account_code(st.session_state.user)
    if not demo and scope is None:
        clear_session()
        st.rerun()
    with st.sidebar:
        st.markdown("### 🏥 KhamTechReCheck")
        st.caption("ศูนย์ตรวจสอบงบเครือข่าย")
        st.caption(html.escape(user))
        if scope:
            st.success(f"หน่วยบริการ {scope}")
        if st.button("กลับหน้าล็อกอิน" if demo else "ออกจากระบบ", width="stretch"):
            clear_session()
            st.rerun()
        if not demo and st.button("ล้างไฟล์และเริ่มใหม่", width="stretch"):
            current_user = st.session_state.user
            clear_session()
            st.session_state.user = current_user
            st.session_state.last_activity = time.time()
            st.rerun()
        st.divider()
        st.subheader("นำเข้าข้อมูล")
        budget_uploads = st.file_uploader("1. รวมไฟล์พึงรับ รพ.สต. (19–21 ไฟล์)", type=["xls", "xlsx"], accept_multiple_files=True,
                                         key="budget_files", disabled=demo, help="ไฟล์พึงรับตามแบบ 43 คอลัมน์ รวมได้หลายไฟล์ ใช้ HSUB หรือ HCODE ของ รพ.สต. ไม่ใช่ HCODE_PAID ของแม่ข่าย")
        stm_uploads = st.file_uploader("2. Statement สปสช. (STM)", type=["xls", "xlsx"], accept_multiple_files=True,
                                      key="stm_files", disabled=demo, help="รองรับ STM ทั้ง 25 ไฟล์ และทุกชีตที่มีตาราง")
        st.caption("แต่ละคนอัปโหลดและกรองของตนเอง ข้อมูลแยกตามเซสชัน ไม่บันทึกไฟล์ผู้ป่วยลงดิสก์")
        evidence = clinical_sidebar(scope, demo)
        fu.mapping_controls()
        remove_duplicates = st.checkbox("ตัดรายการเหมือนกันระหว่างไฟล์/ชีต", value=True,
                                        help="รักษารายการซ้ำภายในชีตเดิมและรายการแก้ไขที่มียอดต่างกัน")
        with st.expander("ทะเบียนชื่อหน่วยบริการ"):
            st.caption("รายชื่อคงที่ตามรายการหน่วยบริการที่กำหนด")
            st.dataframe(pd.DataFrame(DEFAULT_DIRECTORY.items(), columns=["รหัส", "ชื่อ"]), hide_index=True, width="stretch")
        with st.expander("ตั้งชื่อบริการตามราคา • ประมาณการ"):
            st.caption("กฎนี้ใช้เฉพาะเซสชันของคุณ จับคู่หมวด + ราคาต่อแถวแบบตรงกัน ไม่หารยอดรวมเพื่อเดาจำนวนบริการ")
            rule_frame = st.data_editor(bd.DEFAULT_RULES, num_rows="dynamic", hide_index=True,
                                       key="service_rules", disabled=demo,
                                       column_config={"หมวด": st.column_config.SelectboxColumn(options=list(bd.CATEGORIES)),
                                                      "ยอดต่อรายการ (บาท)": st.column_config.NumberColumn(min_value=0.01, format="%.2f")})
        with st.expander("อัตราอ้างอิงปี 2570 • จากภาพผู้ใช้"):
            st.dataframe(bd.RATE_DF, hide_index=True, width="stretch")
    rules, rule_errors = bd.rule_map(rule_frame)
    for error in rule_errors:
        st.warning(error)
    directory = DEFAULT_DIRECTORY
    hero()
    if scope:
        st.caption(f"กำลังตรวจสอบข้อมูล {scope} · {directory[scope]} · แสดงและส่งออกเฉพาะหน่วยบริการของบัญชี")
    if demo:
        st.warning("โหมดตัวอย่าง · ข้อมูลทั้งหมดเป็นข้อมูลสมมติ · ไม่เปิดให้อัปโหลดข้อมูลจริง")
        if "demo_workbooks" not in st.session_state:
            st.session_state.demo_workbooks = demo_workbooks()
        sample = st.session_state.demo_workbooks
        budget_files = [(n, b) for g, n, b in sample if g == "budget"]
        stm_files = [(n, b) for g, n, b in sample if g == "stm"]
    else:
        budget_files = [(f.name, f.getvalue()) for f in budget_uploads]
        stm_files = [(f.name, f.getvalue()) for f in stm_uploads]
    datasets, audits, notices, failures = {}, [], [], []
    with st.spinner("ตรวจหัวตารางและเตรียมข้อมูล…"):
        for group, uploads in (("budget", budget_files), ("stm", stm_files)):
            sheets, errors, duplicate_files = load_group(uploads, group, demo)
            frames, group_audits, warnings = mapped_group(sheets, group, directory, demo, scope)
            datasets[group], duplicate_rows = combine_records(frames, remove_duplicates)
            audits.extend(group_audits)
            failures.extend(errors)
            notices.extend(warnings)
            if duplicate_files:
                notices.append("ข้ามไฟล์เนื้อหาซ้ำ: " + ", ".join(duplicate_files))
            if duplicate_rows:
                notices.append(f"{group}: พบรายการเหมือนกันระหว่างไฟล์/ชีต {duplicate_rows:,} รายการ " +
                               ("(ตัดออกแล้ว)" if remove_duplicates else "(ยังรวมยอดอยู่)"))
    if failures or notices:
        with st.expander(f"ตรวจการนำเข้า · {len(failures)} ข้อผิดพลาด / {len(notices)} ข้อสังเกต", expanded=bool(failures)):
            for message in failures:
                st.error(message)
            for message in notices:
                st.warning(message)
    if audits:
        with st.expander("รายละเอียดการตรวจหัวตารางและคุณภาพข้อมูล"):
            st.dataframe(pd.DataFrame(audits), hide_index=True, width="stretch")
    usable = [df for df in datasets.values() if not df.empty]
    if usable:
        all_records = pd.concat(usable, ignore_index=True)
        lookup = all_records.loc[all_records["_facility"].ne("")].drop_duplicates("_facility").set_index("_facility")["_facility_name"].to_dict()
        with st.sidebar:
            st.divider()
            st.subheader("ตัวกรองร่วมทั้ง 5 แท็บ")
            query = st.text_input("ค้นหารหัสหรือชื่อหน่วยบริการ", placeholder="05542 / 5542 / คำสะอาด", key="search")
            facilities = st.multiselect("หน่วยบริการ", sorted(lookup), default=[scope] if scope in lookup else [],
                                        disabled=bool(scope), format_func=lambda c: f"{c} · {lookup[c]}", key="facility_filter")
            periods = st.multiselect("งวดข้อมูล / REP", sorted(all_records["_period"].unique()), key="period_filter")
        datasets = {g: filter_records(df, query, facilities, periods) for g, df in datasets.items()}
        missing_period = sum(int(df["_period"].eq("ยังไม่ระบุงวด").sum()) for df in datasets.values() if not df.empty)
        if missing_period:
            st.warning(f"{missing_period:,} รายการยังไม่ระบุงวด เลือกคอลัมน์งวดหรือกำหนดงวดในเมนูจับคู่คอลัมน์ก่อนเปรียบเทียบ")
    else:
        st.caption("เริ่มต้นจากอัปโหลดไฟล์ Excel สองกลุ่มที่แถบด้านซ้าย")
        cols = st.columns(3)
        for col, title, description in zip(cols,
            ["01 / นำเข้า Excel", "02 / ตรวจรหัสและงวด", "03 / สรุปและส่งออก"],
            ["เลือกงบพึงรับและ STM หลายไฟล์พร้อมกัน ระบบตรวจหัวตารางให้", "ใช้ HSUB ของ รพ.สต. และตั้งงวดตรงกันทั้งสองชุด", "ดูยอดรายหน่วยบริการ ผลต่างรอตรวจสอบ และดาวน์โหลด Excel"]):
            col.markdown(f'<div class="step"><strong>{title}</strong><p>{description}</p></div>', unsafe_allow_html=True)
    tabs = st.tabs(["01 พึงรับ รพ.สต.", "02 STM", "03 เปรียบเทียบ", "04 รายละเอียดบริการ", "05 Walk-in"])
    with tabs[0]:
        dataset_tab(datasets["budget"], "budget", [a for a in audits if a["ประเภท"] == "งบพึงรับ"], len(budget_files))
    with tabs[1]:
        dataset_tab(datasets["stm"], "stm", [a for a in audits if a["ประเภท"] == "STM"], len(stm_files))
    with tabs[2]:
        comparison_tab(datasets["budget"], datasets["stm"])
        fu.category_comparison(datasets["budget"], datasets["stm"], download)
    with tabs[3]:
        service_tab(datasets, rules, "service", evidence=evidence)
    with tabs[4]:
        service_tab(datasets, rules, "walkin", only_walkin=True, evidence=evidence)
    st.caption("KhamTechReCheck · สรุปจากไฟล์ที่อัปโหลดและตัวกรองปัจจุบัน · ยอดเงินหน่วยบาท · ใช้เพื่อประกอบการตรวจสอบ")
    st.caption(DEVELOPER_CREDIT)


if __name__ == "__main__":
    main()
