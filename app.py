import streamlit as st
import pandas as pd
import glob
import os

# 1. ตั้งค่าคอนฟิกของหน้าเว็บ
st.set_page_config(
    page_title="สปสช. Statement Dashboard | อ.สว่างแดนดิน",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. ปรับแต่ง CSS ตกแต่ง UI ให้ดูทันสมัย สไตล์ Dashboard มืออาชีพ
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Kanit', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 24px;
        border-radius: 16px;
        color: white;
        margin-bottom: 25px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    }
    .main-header h1 {
        color: white !important;
        font-weight: 600;
        margin: 0;
        font-size: 1.8rem;
    }
    .main-header p {
        color: #e0e6ed;
        margin-top: 6px;
        margin-bottom: 0;
        font-size: 0.95rem;
    }

    [data-testid="stSidebar"] {
        background-color: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }

    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 20px;
        border-radius: 14px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.03);
        text-align: center;
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(0,0,0,0.06);
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 600;
        color: #1e293b;
    }
    .metric-label {
        font-size: 0.88rem;
        color: #64748b;
        margin-bottom: 4px;
    }
    </style>
""", unsafe_allow_html=True)

# 3. Header Banner สวยงาม
st.markdown("""
    <div class="main-header">
        <h1>📊 ระบบตรวจสอบ Statement สปสช. & ยอดจัดสรรค้างจ่าย</h1>
        <p>เครือข่ายบริการสุขภาพ อ.สว่างแดนดิน | รพ.สต. สังกัด อบจ.สกลนคร & รพร.สว่างแดนดิน</p>
    </div>
""", unsafe_allow_html=True)

# 4. เมนูด้านข้าง (Sidebar Controls)
st.sidebar.image("https://img.icons8.com/isometric-folders/100/hospital.png", width=60)
st.sidebar.title("📌 เมนูควบคุม")
st.sidebar.markdown("---")

mode = st.sidebar.radio(
    "เลือกช่องทางนำเข้าข้อมูล:",
    ["📤 อัปโหลดไฟล์ Statement (สำหรับระบบ Cloud)", "📁 อ่านไฟล์จากโฟลเดอร์เครื่อง"],
    index=0
)

all_data = []

if "อัปโหลดไฟล์" in mode:
    uploaded_files = st.sidebar.file_uploader(
        "ลากไฟล์ STM (.xls / .xlsx) มาวางที่นี่:",
        type=["xls", "xlsx"],
        accept_multiple_files=True
    )
    if uploaded_files:
        for file in uploaded_files:
            try:
                try:
                    df = pd.read_excel(file, engine='xlrd')
                except Exception:
                    df = pd.read_excel(file)
                df['Source_File'] = file.name
                all_data.append(df)
            except Exception as e:
                st.error(f"ไม่สามารถอ่านไฟล์ {file.name} ได้: {e}")
else:
    folder_path = os.path.dirname(os.path.abspath(__file__))
    excel_files = glob.glob(os.path.join(folder_path, "*.xls*"))
    if excel_files:
        st.sidebar.success(f"พบไฟล์ในระบบ {len(excel_files)} ไฟล์")
        for file in excel_files:
            try:
                try:
                    df = pd.read_excel(file, engine='xlrd')
                except Exception:
                    df = pd.read_excel(file)
                df['Source_File'] = os.path.basename(file)
                all_data.append(df)
            except Exception as e:
                st.error(f"ไม่สามารถอ่านไฟล์ {os.path.basename(file)} ได้: {e}")
    else:
        st.sidebar.warning("ไม่พบไฟล์ Statement ในโฟลเดอร์")

# 5. ส่วนแสดงผลตารางและเครื่องมือกรองข้อมูล
if all_data:
    combined_df = pd.concat(all_data, ignore_index=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">จำนวนไฟล์ที่ประมวลผล</div>
                <div class="metric-value">{len(all_data)} <span style="font-size: 1rem; color:#64748b;">ไฟล์</span></div>
            </div>
        """, unsafe_allow_html=True)
        
    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">จำนวนรายการข้อมูลทั้งหมด</div>
                <div class="metric-value">{len(combined_df):,} <span style="font-size: 1rem; color:#64748b;">รายการ</span></div>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        num_cols = len(combined_df.columns)
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">จำนวนคอลัมน์ข้อมูล</div>
                <div class="metric-value">{num_cols} <span style="font-size: 1rem; color:#64748b;">คอลัมน์</span></div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    st.subheader("🔍 ค้นหาและกรองข้อมูล Statement")
    search_keyword = st.text_input("", placeholder="พิมพ์รหัส รพ.สต. / ชื่อหน่วยบริการ / ชื่อกองทุน (เช่น คำสะอาด, OPUCS, PPFS)...")

    filtered_df = combined_df.copy()
    if search_keyword:
        mask = filtered_df.astype(str).apply(lambda x: x.str.contains(search_keyword, case=False)).any(axis=1)
        filtered_df = filtered_df[mask]

    st.caption(f"แสดงผลจำนวน **{len(filtered_df):,}** รายการ")
    
    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("<br>", unsafe_allow_html=True)
    output_filename = "สรุปยอด_Statement_สปสช_สว่างแดนดิน.xlsx"
    filtered_df.to_excel(output_filename, index=False)
    
    with open(output_filename, "rb") as f:
        st.download_button(
            label="📥 ดาวน์โหลดข้อมูลตารางนี้เป็นไฟล์ Excel",
            data=f,
            file_name=output_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

else:
    st.info("👈 กรุณาเลือกอัปโหลดไฟล์ Statement สปสช. (.xls / .xlsx) ที่เมนูด้านซ้ายเพื่อเริ่มประมวลผล")
