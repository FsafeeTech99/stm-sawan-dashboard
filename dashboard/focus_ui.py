"""Review workspace for HC, herbal DRUG, PP and FS."""
import hashlib
import html
import math
import altair as alt
import pandas as pd
import streamlit as st
from dashboard import focus as fc
from dashboard.data import clean_text


def cards(rows):
    colours = ["navy", "teal", "green", "purple", "amber"]
    subtitles = ["ยอดรวมต้นทาง", "หมวด HC", "สมุนไพร • คอลัมน์ที่เลือก", "ส่งเสริมสุขภาพ / ป้องกันโรค", "หมวด FS"]
    blocks = []
    for col, colour, sub in zip([fc.TOTAL] + fc.GROUPS, colours, subtitles):
        info = fc.total_info(rows, col)
        value = "—" if len(rows) and info["missing"] == len(rows) else f'{info["cents"] / 100:,.2f}'
        status = f'ไม่ทราบยอด {info["missing"]:,} รายการ' if info["missing"] else f'มียอด {info["count"]:,} รายการ'
        blocks.append(f'<div class="money-card {colour}"><span>{html.escape(col)}</span><strong>{value}</strong>'
                      f'<small>บาท · {html.escape(sub)}</small><em>{status}</em></div>')
    st.markdown('<div class="money-grid">' + ''.join(blocks) + '</div>', unsafe_allow_html=True)


def mapping_controls():
    with st.sidebar.expander("ตั้งค่าหมวดสมุนไพร / ช่องว่าง", expanded=False):
        drug = st.selectbox("เมื่อไม่มีหัว HC-DRUG ให้ใช้คอลัมน์", ["DRUG", "DRUG__2", "ไม่จับคู่"],
                            format_func=lambda s: {"DRUG": "DRUG ตำแหน่งแรก (ตามตัวอย่าง)", "DRUG__2": "DRUG ตำแหน่งที่สอง"}.get(s, s),
                            key="focus_drug_source")
        zero = st.checkbox("ช่องว่างหรือขีดในหมวดเงิน = 0 ตามแบบรายงาน", value=True, key="focus_empty_zero")
        st.caption("ใช้ HC-DRUG เมื่อไฟล์ระบุหัวนี้โดยตรงเสมอ ตัวเลือกนี้ใช้เฉพาะไฟล์ที่ไม่มีหัว HC-DRUG • ยอดรวมว่างหรือคอลัมน์ที่ไม่มี จะยังแสดงว่าไม่ทราบยอด")
    return None if drug == "ไม่จับคู่" else drug, zero


def prepared(frame, source):
    notes = st.session_state.get("focus_notes_" + source, {})
    drug = st.session_state.get("focus_drug_source", "DRUG")
    return fc.review_rows(frame, notes, None if drug == "ไม่จับคู่" else drug,
                          st.session_state.get("focus_empty_zero", True))


def brief(frame, source):
    if frame.empty:
        return
    rows = prepared(frame, source)
    st.markdown('<div class="section-kicker">PAYMENT OVERVIEW</div>', unsafe_allow_html=True)
    cards(rows)
    st.caption("HC / HC-DRUG / PP / FS แสดงแยกตามคอลัมน์ • ยอดชดเชยทั้งสิ้นยึดไฟล์ต้นทาง • เปิดแท็บ 04 เพื่อค้นหารายบุคคลและบันทึกรายการติดตาม")


def category_comparison(budget, stm, download):
    result = fc.compare_categories(prepared(budget, "budget"), prepared(stm, "stm"))
    if result.empty:
        return
    st.subheader("ติดตามผลต่างรายหมวด • พึงรับ − STM")
    st.caption("เปรียบเทียบเฉพาะหน่วยและงวดเดียวกันที่มีข้อมูลหมวดครบ ผลต่างนี้รอตรวจสอบ ไม่ใช่ยอดค้างจ่ายที่ยืนยันแล้ว")
    st.dataframe(result, hide_index=True, width="stretch")
    download("ดาวน์โหลดผลต่าง HC / HC-DRUG / PP / FS", {"ผลต่างรายหมวด": result}, "KhamTechReCheck_category_compare.xlsx", "focus_compare_export")


def workspace(frame, source, prefix, download):
    all_rows = prepared(frame, source)
    if all_rows.empty:
        return
    st.markdown('<div class="section-kicker">SERVICE REVIEW WORKSPACE</div>', unsafe_allow_html=True)
    st.subheader("สรุปเงิน • ค้นบริการ • ติดตามรายบุคคล")
    a, b = st.columns([3, 2])
    categories = a.multiselect("กรองรายการที่มียอดในหมวด", fc.GROUPS + [fc.TOTAL], key=prefix + "_focus_categories",
                               placeholder="ทุกหมวด • เลือกหลายหมวดได้")
    query = b.text_input("ค้นหาบุคคล / บริการ", placeholder="HN · เลขบัตร · ชื่อ · ครีมไพล · FIT", key=prefix + "_focus_query")
    c, d = st.columns(2)
    choices = ["ทั้งหมด"] + sorted(all_rows["บริการ"].unique().tolist())
    service_key = prefix + "_focus_service"
    if st.session_state.get(service_key, "ทั้งหมด") not in choices:
        st.session_state[service_key] = "ทั้งหมด"
    service = c.selectbox("ชื่อบริการ", choices, key=service_key)
    status = d.selectbox("สถานะที่ต้องการดู", ["ทั้งหมด", "ต้องติดตาม", "ยังไม่ระบุบริการ", "ยอดรวมว่าง/อ่านไม่ได้"], key=prefix + "_focus_status")
    rows = fc.filter_rows(all_rows, categories, query, service, status)
    st.caption(f"ผลกรอง {len(rows):,} / {len(all_rows):,} รายการ • เลือกหลายหมวดใช้เงื่อนไขมียอดอย่างน้อยหนึ่งหมวด • ยอดด้านล่างเปลี่ยนตามตัวกรองชุดนี้")
    cards(rows)
    st.caption("ตัวเลขที่มีรายการไม่ทราบยอดเป็นผลรวมเฉพาะส่วนที่อ่านได้ หมวดเงินอาจซ้อนกัน จึงไม่บวกแทนยอดชดเชยทั้งสิ้น")
    if rows.empty:
        st.info("ไม่มีรายการตรงตัวกรอง ลองล้างคำค้นหรือเลือกทุกหมวด")
        return
    count, amounts, unknown = fc.tracking_summary(rows)
    st.markdown(f'<div class="followup-banner"><b>รายการที่คุณเลือกติดตาม {count:,} รายการ</b>'
                f'<span>สมุนไพร <strong>{amounts[fc.EDIT_COLUMNS[2]]:,.2f}</strong> บาท'
                f' &nbsp; • &nbsp; PP <strong>{amounts[fc.EDIT_COLUMNS[3]]:,.2f}</strong> บาท'
                f' &nbsp; • &nbsp; ยังไม่ระบุยอด {unknown:,} รายการ</span></div>', unsafe_allow_html=True)
    st.caption("ยอดตามสมุนไพรและ PP คือยอดที่ผู้ใช้กรอกเองเฉพาะแถวที่ติ๊กต้องติดตาม • หากต้องการพึงรับลบ STM ให้ดูแท็บ 03")
    left, right = st.columns([1, 1])
    totals = fc.summary(rows)
    with left:
        plot = totals.iloc[1:]
        st.altair_chart(alt.Chart(plot).mark_bar(cornerRadiusEnd=6).encode(
            x=alt.X("ยอดอ่านได้ (บาท):Q", title="บาท"), y=alt.Y("หมวด:N", sort=fc.GROUPS, title=None),
            color=alt.Color("หมวด:N", scale=alt.Scale(domain=fc.GROUPS, range=["#0891b2", "#059669", "#7c3aed", "#d97706"]), legend=None),
            tooltip=["หมวด", alt.Tooltip("ยอดอ่านได้ (บาท):Q", format=",.2f"), "รายการไม่ทราบยอด"]
        ).properties(height=185), width="stretch")
    with right:
        st.markdown("**สรุปพร้อมใช้งาน**")
        lines = []
        for _, item in totals.iterrows():
            suffix = f' (ไม่ทราบยอด {item["รายการไม่ทราบยอด"]} รายการ)' if item["รายการไม่ทราบยอด"] else ""
            lines.append(f'{item["หมวด"]}: {item["ยอดอ่านได้ (บาท)"]:,.2f} บาท{suffix}')
        lines += [f'ยอดตามสมุนไพรที่กรอกเอง: {amounts[fc.EDIT_COLUMNS[2]]:,.2f} บาท',
                  f'ยอดตาม PP ที่กรอกเอง: {amounts[fc.EDIT_COLUMNS[3]]:,.2f} บาท']
        st.code("\n".join(lines), language=None)
    show_names = st.checkbox("แสดงชื่อในตารางและไฟล์ส่งออกชุดนี้", key=prefix + "_focus_names")
    table = fc.export_rows(rows, show_names)
    st.markdown("**รายละเอียดและบันทึกติดตาม**")
    st.caption("เติมชื่อในช่อง ‘บริการที่ตรวจเอง’ และติ๊ก ‘ต้องติดตาม’ จากนั้นบันทึก • ชื่อจากไฟล์และยอดชดเชยต้นทางแก้ไม่ได้ • บันทึกอยู่ในเซสชันนี้ ควร Export ก่อนออกจากระบบ")
    pages = max(1, math.ceil(len(rows) / 100))
    digest = hashlib.sha256(("|".join(rows["_key"]) + str(st.session_state.get("focus_revision", 0))).encode()).hexdigest()[:12]
    page = st.selectbox("หน้าตาราง (หน้าละ 100 รายการ)", list(range(1, pages + 1)), key=prefix + "_page_" + digest)
    start = (page - 1) * 100
    page_table = table.iloc[start:start + 100].reset_index(drop=True)
    configs = {c: st.column_config.NumberColumn(format="%.2f") for c in fc.GROUPS + [fc.TOTAL, "เรียกเก็บ"]}
    configs.update({c: st.column_config.NumberColumn(min_value=0, format="%.2f", help="จำนวนเงินที่คุณต้องการติดตาม ไม่คำนวณจากราคาโดยอัตโนมัติ") for c in fc.EDIT_COLUMNS[2:4]})
    configs["บริการที่ตรวจเอง"] = st.column_config.TextColumn(width="medium")
    configs["ต้องติดตาม"] = st.column_config.CheckboxColumn()
    with st.form(prefix + "_review_form_" + digest + str(page)):
        edited = st.data_editor(page_table, hide_index=True, width="stretch", height=420,
                                disabled=[c for c in page_table if c not in fc.EDIT_COLUMNS], column_config=configs,
                                key=prefix + "_review_editor_" + digest + str(page))
        save = st.form_submit_button("บันทึกชื่อบริการและรายการติดตาม", type="primary")
    if save:
        notes_key = "focus_notes_" + source
        notes = dict(st.session_state.get(notes_key, {}))
        for key, (_, entry) in zip(rows["_key"].iloc[start:start + 100], edited.iterrows()):
            note = {col: None if pd.isna(entry[col]) else entry[col] for col in fc.EDIT_COLUMNS}
            for col in fc.EDIT_COLUMNS[2:4]:
                if note[col] is not None and (not math.isfinite(float(note[col])) or float(note[col]) < 0):
                    st.error("ยอดติดตามต้องเป็นจำนวนเงินตั้งแต่ 0 ขึ้นไป")
                    return
            note["ต้องติดตาม"] = bool(note["ต้องติดตาม"])
            notes[key] = note
        st.session_state[notes_key] = notes
        st.session_state["focus_revision"] = st.session_state.get("focus_revision", 0) + 1
        st.rerun()
    service_summary = []
    for name, group in rows.groupby("บริการ", sort=True):
        item = {"บริการ": name, "จำนวนรายการ": len(group)}
        for col in fc.GROUPS + [fc.TOTAL]:
            info = fc.total_info(group, col)
            item[col] = info["cents"] / 100 if not info["missing"] else None
        service_summary.append(item)
    by_service = pd.DataFrame(service_summary)
    with st.expander("สรุปยอดแยกชื่อบริการ", expanded=False):
        st.dataframe(by_service, hide_index=True, width="stretch")
        st.caption("ค่าว่างหมายถึงข้อมูลหมวดนั้นไม่ครบในบริการนี้")
    download("Export สรุปและรายการตามตัวกรอง", {"สรุปยอด": totals, "สรุปรายบริการ": by_service,
             "รายละเอียด": table, "รายการติดตาม": table.loc[table["ต้องติดตาม"]]},
             "KhamTechReCheck_service_review.xlsx", prefix + "_focus_export")
    st.divider()
