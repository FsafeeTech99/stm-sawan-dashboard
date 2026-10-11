import streamlit as st
import pandas as pd
import os

# 1. ตั้งค่าคอนฟิกของหน้าเว็บ
st.set_page_config(
    page_title="สปสช. Statement Dashboard | อ.สว่างแดนดิน",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. ตกแต่ง UI
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Kanit', sans-serif; }
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 24px;
        border-radius: 16px;
        color: white;
        margin-bottom: 25px;
    }
    .main-header h1 { color: white !important; margin: 0; font-size: 1.8rem; }
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 18px;
        border-radius: 12px;
        text-align: center;
    }
    .metric-value { font-size: 1.6rem; font-weight: 600; color: #1e293b; }
    .metric-label { font-size: 0.85rem; color: #64748b; }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="main-header">
        <h1>📊 ระบบตรวจสอบ Statement สปสช. & ติดตามยอดจัดสรรค้างจ่าย</h1>
        <p>เครือข่ายบริการสุขภาพ อ.สว่างแดนดิน (รพร.สว่างแดนดิน 11450 & รพ.สต. สังกัด อบจ.สกลนคร)</p>
    </div>
""", unsafe_allow_html=True)

# ฟังก์ชันอ่านไฟล์และค้นหาบรรทัดหัวตารางจริงอัตโนมัติ (ข้ามข้อความหัวรายงาน)
def parse_nhso_statement(file):
    try:
        raw_df = pd.read_excel(file, header=None, engine='xlrd')
    except Exception:
        raw_df = pd.read_excel(file, header=None)
        
    header_keywords = ['ลำดับ', 'วันที่', 'งวด', 'เลขที่', 'กองทุน', 'จำนวนเงิน', 'รหัส', 'HCODE', 'HSUB', 'รายการ', 'ชดเชย', 'ยอดโอน', 'คงเหลือ']
    
    header_row_idx = None
    for idx, row in raw_df.iterrows():
        row_str = " ".join(row.dropna().astype(str))
        matches = sum(1 for kw in header_keywords if kw in row_str)
        if matches >= 2:
            header_row_idx = idx
            break
            
    if header_row_idx is not None:
        # ใช้บรรทัดที่พบเป็นชื่อคอลัมน์
        df = raw_df.iloc[header_row_idx + 1:].copy()
        df.columns = raw_df.iloc[header_row_idx].values
        df.columns = [str(c).strip().replace('\n', ' ') for c in df.columns]
        
        # ลบแถวที่เป็นค่าว่างทั้งหมด
        df = df.dropna(how='all')
        
        # ตัดคอลัมน์ที่เป็น Unnamed หรือ nan ออก
        valid_cols = [c for c in df.columns if not str(c).lower().startswith('unnamed') and str(c).lower() != 'nan']
        df = df[valid_cols]
        return df
    else:
        try:
            return pd.read_excel(file, engine='xlrd')
        except Exception:
            return pd.read_excel(file)

st.sidebar.title("📌 เมนูควบคุม")
uploaded_files = st.sidebar.file_uploader(
    "อัปโหลดไฟล์ Statement (.xls / .xlsx) ทั้งหมดที่นี่:",
    type=["xls", "xlsx"],
    accept_multiple_files=True
)

all_data = []

if uploaded_files:
    for file in uploaded_files:
        try:
            df = parse_nhso_statement(file)
            df['Source_File'] = file.name
            
            # แปลงทุกคอลัมน์เป็นข้อความให้ค้นหาง่าย
            for col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True)
                
            all_data.append(df)
        except Exception as e:
            st.error(f"ไม่สามารถอ่านไฟล์ {file.name} ได้: {e}")

if all_data:
    combined_df = pd.concat(all_data, ignore_index=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="metric-label">จำนวนไฟล์ที่ประมวลผล</div><div class="metric-value">{len(all_data)} ไฟล์</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div class="metric-label">จำนวนรายการทั้งหมด</div><div class="metric-value">{len(combined_df):,} รายการ</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="metric-label">จำนวนคอลัมน์ข้อมูล</div><div class="metric-value">{len(combined_df.columns)} คอลัมน์</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    st.subheader("🔍 ค้นหาและตรวจสอบยอดตาม รพ.สต. / รายการกองทุน")
    
    search_keyword = st.text_input("พิมพ์รหัส รพ.สต. (เช่น 05542, 5542) หรือชื่อรายการ/กองทุน/เลขที่เบิกจ่าย:", placeholder="พิมพ์คำค้นหาที่นี่...")

    filtered_df = combined_df.copy()
    
    if search_keyword:
        clean_keyword = search_keyword.strip().lstrip('0')
        mask = filtered_df.astype(str).apply(
            lambda x: x.str.contains(search_keyword, case=False) | (x.str.contains(clean_keyword, case=False) if clean_keyword else False)
        ).any(axis=1)
        filtered_df = filtered_df[mask]

    st.caption(f"พบข้อมูลทั้งหมด **{len(filtered_df):,}** รายการ")
    
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
            label="📥 ดาวน์โหลดข้อมูลตารางที่กรองนี้เป็นไฟล์ Excel",
            data=f,
            file_name=output_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

else:
    st.info("👈 ลากไฟล์ Statement สปสช. ทั้ง 25 ไฟล์มาวางที่เมนูด้านซ้ายเพื่อเริ่มประมวลผล")
