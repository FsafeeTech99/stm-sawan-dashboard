import streamlit as st
import pandas as pd
import glob
import os

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="ระบบตรวจสอบ Statement สปสช. - อ.สว่างแดนดิน", layout="wide")

st.title("📊 ระบบตรวจสอบ Statement สปสช. & ยอดค้างจ่าย")
st.subheader("รพร.สว่างแดนดิน - รพ.สต. ในเครือข่าย อบจ.สกลนคร")

# เมนูเลือกรูปแบบการดึงข้อมูล
mode = st.sidebar.radio("เลือกแหล่งข้อมูล:", ["อัปโหลดไฟล์ STM (แนะนำสำหรับเว็บ Cloud)", "อ่านไฟล์จากโฟลเดอร์ในเครื่อง"])

all_data = []

if mode == "อัปโหลดไฟล์ STM (แนะนำสำหรับเว็บ Cloud)":
    uploaded_files = st.file_uploader("ลากไฟล์ Statement (.xls / .xlsx) ทั้งหมดมาวางที่นี่", type=["xls", "xlsx"], accept_multiple_files=True)
    if uploaded_files:
        for file in uploaded_files:
            try:
                df = pd.read_excel(file)
                df['Source_File'] = file.name
                all_data.append(df)
            except Exception as e:
                st.error(f"ไม่สามารถอ่านไฟล์ {file.name} ได้: {e}")

else:
    folder_path = os.path.dirname(os.path.abspath(__file__))
    excel_files = glob.glob(os.path.join(folder_path, "*.xls*"))
    if excel_files:
        st.info(f"📁 พบไฟล์ในโฟลเดอร์ {len(excel_files)} ไฟล์")
        for file in excel_files:
            try:
                df = pd.read_excel(file)
                df['Source_File'] = os.path.basename(file)
                all_data.append(df)
            except Exception as e:
                st.error(f"ไม่สามารถอ่านไฟล์ {os.path.basename(file)} ได้: {e}")
    else:
        st.warning("⚠️ ไม่พบไฟล์ Statement ในโฟลเดอร์เดียวกับ app.py")

# การประมวลผลและแสดงผลตาราง
if all_data:
    combined_df = pd.concat(all_data, ignore_index=True)
    st.divider()
    
    # การ์ดสรุปตัวเลข
    st.markdown("### 📌 สรุปภาพรวม")
    c1, c2 = st.columns(2)
    c1.metric("จำนวนรายการทั้งหมดใน STM", f"{len(combined_df):,} รายการ")
    
    # ช่องค้นหา/กรองข้อมูล
    search_keyword = st.text_input("🔍 ค้นหารหัส / ชื่อ รพ.สต. / รายการกองทุน (เช่น คำสะอาด, OPUCS):")
    
    filtered_df = combined_df.copy()
    if search_keyword:
        mask = filtered_df.astype(str).apply(lambda x: x.str.contains(search_keyword, case=False)).any(axis=1)
        filtered_df = filtered_df[mask]
    
    st.dataframe(filtered_df, use_container_width=True)
    
    # ปุ่มดาวน์โหลด Excel
    output_filename = "สรุปยอด STM_สว่างแดนดิน.xlsx"
    filtered_df.to_excel(output_filename, index=False)
    with open(output_filename, "rb") as f:
        st.download_button(
            label="📥 ดาวน์โหลดข้อมูลตารางนี้เป็น Excel",
            data=f,
            file_name=output_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )