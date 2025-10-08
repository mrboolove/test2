import streamlit as st
import pandas as pd
import docx
import json
import numpy as np
import numpy_financial as npf
from google import genai
from google.genai.types import HarmCategory, HarmBlockThreshold

# Cài đặt: pip install streamlit python-docx numpy-financial google-generativeai pandas numpy

st.set_page_config(
    page_title="Đánh giá Phương án Kinh doanh",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main {background-color: #f0f2f6;}
    .stMetric {background-color: #ffffff; padding: 10px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);}
    </style>
""", unsafe_allow_html=True)

st.title("📈 App Đánh giá Phương án Kinh doanh từ File Word")

# Sidebar cho hướng dẫn
with st.sidebar:
    st.header("Hướng dẫn")
    st.info("""
    1. Tải file Word (.docx) mô tả dự án.
    2. Nhấn nút lọc thông tin bằng AI (cần Gemini API key trong Secrets).
    3. Xây dựng bảng dòng tiền và tính chỉ số.
    4. Yêu cầu AI phân tích.
    """)
    st.info("Cấu hình GEMINI_API_KEY trong Streamlit Secrets.")

@st.cache_data
def extract_project_info(text, api_key):
    """Lọc thông tin dự án bằng Gemini AI."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            generation_config={"temperature": 0.1},
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            }
        )
        prompt = f"""
        Trích xuất thông tin từ văn bản đề xuất dự án sau. Giả sử doanh thu và chi phí hàng năm không đổi.
        - Vốn đầu tư (capital): số tiền đầu tư ban đầu.
        - Dòng đời dự án (lifespan): số năm dự án.
        - Doanh thu hàng năm (revenue): doanh thu/năm.
        - Chi phí hàng năm (cost): chi phí/năm.
        - WACC: chi phí vốn bình quân có trọng số (decimal).
        - Thuế suất (tax): tỷ lệ thuế (0-1).

        Output CHỈ JSON object, không text khác:
        {{"capital": số, "lifespan": số_nguyên, "revenue": số, "cost": số, "wacc": số, "tax": số}}

        Văn bản: {text[:4000]}"""  # Giới hạn text để tránh token limit

        response = model.generate_content(prompt)
        data_str = response.text.strip()
        if data_str.startswith('```json'):
            data_str = data_str[7:-3].strip()
        elif data_str.endswith('```'):
            data_str = data_str[:-3].strip()
        data = json.loads(data_str)
        # Chuyển type
        data['capital'] = float(data['capital'])
        data['lifespan'] = int(data['lifespan'])
        data['revenue'] = float(data['revenue'])
        data['cost'] = float(data['cost'])
        data['wacc'] = float(data['wacc'])
        data['tax'] = float(data['tax'])
        return data
    except Exception as e:
        st.error(f"Lỗi extract: {e}")
        return None

def build_cashflow(data):
    """Xây bảng dòng tiền đơn giản (giả sử dòng tiền hàng năm không đổi)."""
    capital = data['capital']
    lifespan = data['lifespan']
    annual_cf = (data['revenue'] - data['cost']) * (1 - data['tax'])
    CF = [-capital] + [annual_cf] * lifespan
    years = list(range(lifespan + 1))
    df = pd.DataFrame({'Năm': years, 'Dòng tiền (không chiết khấu)': CF})
    # Thêm cột chiết khấu
    discounted = [cf / (1 + data['wacc']) ** t for t, cf in enumerate(CF)]
    df['Dòng tiền chiết khấu'] = discounted
    # Cumulative cho PP/DPP
    df['Tích lũy không chiết khấu'] = np.cumsum(CF)
    df['Tích lũy chiết khấu'] = np.cumsum(discounted)
    return df

def calculate_metrics(df_cf, wacc):
    """Tính NPV, IRR, PP, DPP."""
    CF = df_cf['Dòng tiền (không chiết khấu)'].tolist()
    npv_val = npf.npv(wacc, CF)
    try:
        irr_val = npf.irr(CF)
    except:
        irr_val = np.nan  # Nếu không hội tụ

    # PP: Payback Period (không chiết khấu)
    cum_cf = df_cf['Tích lũy không chiết khấu'].tolist()
    pp = next((i for i, cum in enumerate(cum_cf) if cum >= 0), len(CF))
    if pp < len(CF) and cum_cf[pp-1] < 0:
        pp = (pp - 1) + (-cum_cf[pp-1] / (cum_cf[pp] - cum_cf[pp-1]))

    # DPP: Discounted PP
    cum_disc = df_cf['Tích lũy chiết khấu'].tolist()
    dpp = next((i for i, cum in enumerate(cum_disc) if cum >= 0), len(CF))
    if dpp < len(CF) and cum_disc[dpp-1] < 0:
        dpp = (dpp - 1) + (-cum_disc[dpp-1] / (cum_disc[dpp] - cum_disc[dpp-1]))

    return npv_val, irr_val, pp, dpp

def get_ai_analysis(npv, irr, pp, dpp, wacc, api_key):
    """AI phân tích chỉ số."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Bạn là chuyên gia tài chính ngân hàng. Phân tích hiệu quả dự án dựa trên chỉ số:
        - NPV: {npv:.2f}
        - IRR: {irr:.2%}
        - PP (hoàn vốn): {pp:.2f} năm
        - DPP (hoàn vốn chiết khấu): {dpp:.2f} năm
        - WACC: {wacc:.2%}

        Đưa nhận xét khách quan, ngắn gọn (3-4 đoạn) bằng tiếng Việt, tập trung vào tính khả thi giải ngân vốn vay.
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Lỗi AI: {e}"

# Main app
uploaded_file = st.file_uploader("Tải file Word (.docx) mô tả dự án", type=['docx'])

if uploaded_file is not None:
    doc = docx.Document(uploaded_file)
    full_text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])

    st.subheader("1. Lọc thông tin dự án bằng AI")
    if st.button("Thực hiện lọc dữ liệu", type="primary"):
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            st.error("Thiếu GEMINI_API_KEY trong Secrets.")
        else:
            with st.spinner("Đang phân tích file bằng AI..."):
                extracted_data = extract_project_info(full_text, api_key)
                if extracted_data:
                    st.session_state.extracted = extracted_data
                    st.success("Lọc thành công!")
                    st.json(extracted_data)

    if 'extracted' in st.session_state:
        st.subheader("2. Bảng dòng tiền dự án")
        if st.button("Xây dựng bảng dòng tiền"):
            df_cf = build_cashflow(st.session_state.extracted)
            st.dataframe(df_cf.style.format({
                'Dòng tiền (không chiết khấu)': '{:,.0f}',
                'Dòng tiền chiết khấu': '{:,.0f}',
                'Tích lũy không chiết khấu': '{:,.0f}',
                'Tích lũy chiết khấu': '{:,.0f}'
            }).background_gradient(cmap='viridis'), use_container_width=True)

            st.subheader("3. Các chỉ số đánh giá")
            metrics = calculate_metrics(df_cf, st.session_state.extracted['wacc'])
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                color = "green" if metrics[0] > 0 else "red"
                st.metric("NPV", f"{metrics[0]:,.0f}", delta=None, delta_color=color)
            with col2:
                st.metric("IRR", f"{metrics[1]:.2%}")
            with col3:
                st.metric("PP (năm)", f"{metrics[2]:.2f}")
            with col4:
                st.metric("DPP (năm)", f"{metrics[3]:.2f}")

            st.subheader("4. Phân tích AI")
            if st.button("Yêu cầu AI phân tích chỉ số", type="primary"):
                api_key = st.secrets.get("GEMINI_API_KEY")
                with st.spinner("Đang phân tích..."):
                    analysis = get_ai_analysis(*metrics, st.session_state.extracted['wacc'], api_key)
                    st.info(analysis)
else:
    st.info("👆 Vui lòng tải file Word để bắt đầu.")
