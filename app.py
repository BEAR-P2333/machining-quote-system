import streamlit as st
from google import genai
from google.genai import types
import os
import json
import base64
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta

# ==========================================
# 0. 경로 및 기본 데이터베이스 설정 (클라우드/로컬 자동 호환)
# ==========================================
# 실행 중인 파일 기준 상대 경로로 설정하여 리눅스 클라우드에서도 정상 동작하도록 처리
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(DATA_DIR, "pricing_settings.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders_database.json")
USERS_FILE = os.path.join(DATA_DIR, "system_users.json")

DEFAULT_USERS = {
    "admin": {"password": "admin1234!", "name": "총괄관리자", "role": "admin"},
    "factory1": {"password": "factory1234!", "name": "제1가공공장", "role": "user"},
    "sales": {"password": "sales1234!", "name": "영업팀장", "role": "user"}
}

DEFAULT_SETTINGS = {
    "company_info": {
        "company_name": "(주)마시닝솔루션스",
        "biz_num": "123-45-67890",
        "ceo_name": "홍길동",
        "tel": "031-123-4567",
        "email": "quote@machiningsol.com",
        "address": "경기도 시흥시 시화벤처로 123"
    },
    "materials": {
        "S45C / 탄소강": 4500,
        "SS400 / 일반강": 4000,
        "AL6061 / 알루미늄": 9500,
        "SUS304 / 스테인리스": 13000,
        "기타 / 미상": 8000
    },
    "machines": {
        "3축 머시닝센터(MCT)": 40000,
        "5축 머시닝센터(MCT)": 75000,
        "CNC 복합선반": 45000,
        "범용 가공 / 톱절단": 30000
    },
    "surface_treatments": {
        "무처리 (가공원형)": 0,
        "샌딩 / 아노다이징 (백색)": 5000,
        "아노다이징 (흑색/유색)": 7000,
        "무전해 니켈도금": 8000,
        "열처리 (QT/고주파)": 10000
    },
    "default_setup_fee": 50000,
    "default_margin_rate": 25
}

PROCESS_STAGES = ["1. 견적제출", "2. 발주확정", "3. 소재입고", "4. 가공진행(MCT/선반)", "5. 열처리/후처리", "6. 치수검사/세척", "7. 출하완료"]

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users_db = load_json(USERS_FILE, DEFAULT_USERS)
settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
orders_db = load_json(ORDERS_FILE, [])

# ==========================================
# 1. UI 테마 & 로그인 세션 관리
# ==========================================
st.set_page_config(page_title="MACHINING MES | 초정밀 절삭가공 통합 솔루션", page_icon="⚙️", layout="wide")

st.markdown("""
<style>
    .metric-card {
        background: #1e2430;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 8px;
    }
    .metric-label { color: #94a3b8; font-size: 12px; font-weight: 500; }
    .metric-value { color: #f8fafc; font-size: 22px; font-weight: 700; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

if not st.session_state["auth_user"]:
    login_c1, login_c2, login_c3 = st.columns([1, 1.2, 1])
    with login_c2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔒 MACHINING MES 포털")
        st.caption("사전 등록된 공장 및 인가된 담당자 전용 시스템입니다.")
        
        with st.form("login_form"):
            in_id = st.text_input("아이디 (User ID)")
            in_pw = st.text_input("비밀번호 (Password)", type="password")
            submit_login = st.form_submit_button("시스템 접속", use_container_width=True, type="primary")
            
            if submit_login:
                if in_id in users_db and users_db[in_id]["password"] == in_pw:
                    st.session_state["auth_user"] = users_db[in_id]
                    st.session_state["auth_user_id"] = in_id
                    st.success(f"{users_db[in_id]['name']}님 환영합니다.")
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 일치하지 않습니다.")
        st.info("💡 초기 관리자 계정: `admin` / 비밀번호: `admin1234!`")
    st.stop()

# ==========================================
# 2. 상단 헤더 & 사이드바
# ==========================================
head_l, head_r = st.columns([3, 1])
with head_l:
    st.title("⚙️ MACHINING MES | 견적·공정 관리 시스템")
    st.caption(f"접속자: **{st.session_state['auth_user']['name']}** ({st.session_state['auth_user']['role']}) | 사업장: {settings['company_info']['company_name']}")
with head_r:
    if st.button("🚪 로그아웃", use_container_width=True):
        st.session_state["auth_user"] = None
        st.rerun()

with st.sidebar:
    st.header("🔑 AI 비전 엔진 설정")
    # Streamlit Cloud의 Secrets에 등록된 키가 있으면 자동 주입
    default_api_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key = st.text_input("Gemini API Key", value=default_api_key, type="password", help="도면 Vision 판독용 API Key입니다.")
    selected_model = st.selectbox("AI 모델", ["gemini-3.8-flash"], index=0)
    st.divider()
    st.caption(f"기준 셋업비: **{settings['default_setup_fee']:,} 원**")
    st.caption(f"표준 마진율: **{settings['default_margin_rate']} %**")

# ==========================================
# 3. PDF 견적서 생성 유틸리티 (윈도우/리눅스 폰트 동시 지원)
# ==========================================
def create_formal_pdf(q):
    pdf = FPDF(format="A4")
    pdf.add_page()
    
    # 윈도우(Malgun) 및 리눅스 클라우드(NanumGothic) 폰트 자동 탐색
    font_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # 리눅스 클라우드 표준 경로
        r"C:\Windows\Fonts\malgun.ttf",                     # 윈도우 로컬 경로
        os.path.join(DATA_DIR, "NanumGothic.ttf")
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        r"C:\Windows\Fonts\malgunbd.ttf",
        os.path.join(DATA_DIR, "NanumGothicBold.ttf")
    ]

    selected_font = next((p for p in font_candidates if os.path.exists(p)), None)
    selected_bold = next((p for p in bold_candidates if os.path.exists(p)), selected_font)

    if selected_font:
        pdf.add_font("KoreanFont", "", selected_font)
        pdf.add_font("KoreanFontB", "", selected_bold)
        main_font, bold_font = "KoreanFont", "KoreanFontB"
    else:
        main_font, bold_font = "helvetica", "helvetica"

    pdf.set_font(bold_font, size=18)
    pdf.cell(0, 12, "가 공 견 적 서 (QUOTATION)", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font(main_font, size=9)
    pdf.cell(95, 6, f"견적번호: {q.get('quote_no', 'QT-NEW')}", ln=False)
    pdf.cell(95, 6, f"발행일자: {q.get('date', '-')}", ln=True, align="R")
    pdf.cell(95, 6, "유효기간: 발행일로부터 15일간", ln=False)
    pdf.cell(95, 6, f"납기요청일: {q.get('due_date', '-')}", ln=True, align="R")
    pdf.ln(2)

    y_pos = pdf.get_y()
    pdf.rect(10, y_pos, 90, 30)
    pdf.set_xy(12, y_pos + 2)
    pdf.set_font(bold_font, size=10)
    pdf.cell(86, 6, f"수신: {q.get('client_name', '고객사')} 귀하", ln=True)
    pdf.set_font(main_font, size=8)
    pdf.set_x(12)
    pdf.cell(86, 5, f"담당자: {q.get('client_manager', '담당자')} 님", ln=True)
    pdf.set_x(12)
    pdf.cell(86, 5, f"품명(도면): {q.get('filename', '도면')}", ln=True)
    pdf.set_x(12)
    pdf.cell(86, 5, f"현재상태: {q.get('status', '1. 견적제출')}", ln=True)

    c_info = settings["company_info"]
    pdf.rect(105, y_pos, 95, 30)
    pdf.set_xy(107, y_pos + 2)
    pdf.set_font(bold_font, size=9)
    pdf.cell(91, 5, f"공급자: {c_info.get('company_name','')} (대표: {c_info.get('ceo_name','')})", ln=True)
    pdf.set_font(main_font, size=8)
    pdf.set_x(107)
    pdf.cell(91, 5, f"사업자번호: {c_info.get('biz_num','')}", ln=True)
    pdf.set_x(107)
    pdf.cell(91, 5, f"소재지: {c_info.get('address','')}", ln=True)
    pdf.set_x(107)
    pdf.cell(91, 5, f"연락처: {c_info.get('tel','')} / {c_info.get('email','')}", ln=True)

    pdf.set_y(y_pos + 34)
    pdf.set_font(bold_font, size=11)
    pdf.cell(0, 9, f"견적 공급가액 총계: 일금 {q.get('total_price', 0):,} 원정 (VAT 별도)", border=1, ln=True, align="C")
    pdf.ln(3)

    pdf.set_font(bold_font, size=8)
    pdf.cell(38, 7, "품명 및 사양", border=1, align="C")
    pdf.cell(16, 7, "수량", border=1, align="C")
    pdf.cell(34, 7, "재질 / 중량", border=1, align="C")
    pdf.cell(36, 7, "설비 / 후처리", border=1, align="C")
    pdf.cell(32, 7, "개당 단가", border=1, align="C")
    pdf.cell(34, 7, "합계 공급가", border=1, align="C")
    pdf.ln()

    pdf.set_font(main_font, size=8)
    pdf.cell(38, 7, str(q.get('filename', '도면'))[:16], border=1, align="C")
    pdf.cell(16, 7, f"{q.get('qty', 1):,} EA", border=1, align="C")
    pdf.cell(34, 7, f"{str(q.get('material','')).split('/')[0]} ({q.get('weight',0)}kg)", border=1, align="C")
    pdf.cell(36, 7, f"{str(q.get('machine_type','')).split()[0]} / {str(q.get('surface','')).split()[0]}", border=1, align="C")
    pdf.cell(32, 7, f"{q.get('unit_price', 0):,} 원", border=1, align="R")
    pdf.cell(34, 7, f"{q.get('total_price', 0):,} 원", border=1, align="R")
    pdf.ln(10)

    pdf.set_font(bold_font, size=9)
    pdf.cell(0, 6, "[ 세부 원가 산출 명세 ]", ln=True)
    pdf.set_font(main_font, size=8)
    pdf.cell(0, 5, f"- 재료비 합계: {q.get('material_cost_total', 0):,} 원 (개당 {q.get('weight', 0)}kg x {q.get('material_unit_price', 0):,}원 x {q.get('qty', 1)}개)", ln=True)
    pdf.cell(0, 5, f"- 가공비 합계: {q.get('machining_cost_total', 0):,} 원 (가공 {q.get('hours', 0)}h x {q.get('machine_hourly_rate', 0):,}원 x {q.get('qty', 1)}개 x 공차할증 {q.get('tolerance_factor', 'x1.0')})", ln=True)
    pdf.cell(0, 5, f"- 셋업비(초도 세팅): {q.get('setup_fee', 0):,} 원 (수량 분산: 개당 {int(q.get('setup_fee',0)/max(q.get('qty',1),1)):,}원)", ln=True)
    pdf.cell(0, 5, f"- 표면/후처리비: {q.get('surface_cost_total', 0):,} 원 ({q.get('surface', '무처리')})", ln=True)
    pdf.cell(0, 5, f"- 일반관리비 및 이윤 ({q.get('margin_rate', 25)}%): {q.get('margin_amount', 0):,} 원", ln=True)
    
    if q.get('memo'):
        pdf.ln(2)
        pdf.set_font(bold_font, size=8)
        pdf.cell(0, 5, f"[ 현장 특이사항 및 메모 ]: {q.get('memo')}", ln=True)

    return bytes(pdf.output())

def get_pdf_display_html(pdf_bytes, height=500):
    b64 = base64.b64encode(pdf_bytes).decode('utf-8')
    return f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}px" type="application/pdf" style="border: 1px solid #334155; border-radius: 6px;"></iframe>'

# ==========================================
# 4. 메인 탭 네비게이션
# ==========================================
tab_quote, tab_process, tab_calendar, tab_history, tab_settings = st.tabs([
    "🚀 견적 산출 (AI / 수동)",
    "🏭 공정흐름 관리 (MES)",
    "📅 납기 캘린더",
    "📦 묶음 발주 & 이력",
    "⚙️ 단가 및 계정 관리"
])

# ------------------------------------------
# TAB 1: 견적 산출
# ------------------------------------------
with tab_quote:
    st.markdown("#### 1. 기본 발주 사양 입력")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        client_name = st.text_input("고객사(발주처)", value="(주)한국정밀")
    with c2:
        client_manager = st.text_input("담당자 성함/직함", value="김철수 부장")
    with c3:
        order_qty = st.number_input("발주 수량 (EA)", min_value=1, value=10, step=1)
    with c4:
        due_date = st.date_input("납기 요청일", value=datetime.today() + timedelta(days=12))

    quote_mode = st.radio("견적 산출 방식 선택", ["🤖 AI 도면 비전 자동 판독", "✍️ 엔지니어 직접 수동 입력"], horizontal=True)

    parsed_weight = 0.5
    parsed_hours = 0.5
    parsed_holes = 0
    parsed_diff = "중"
    parsed_reasoning = "수동 산출 모드"

    uploaded_file = None
    if quote_mode == "🤖 AI 도면 비전 자동 판독":
        col_up, col_prev = st.columns([1, 1])
        with col_up:
            uploaded_file = st.file_uploader("가공 도면 업로드 (PDF, PNG, JPG, JPEG)", type=["pdf", "png", "jpg", "jpeg"])
            ai_btn = st.button("⚡ AI 도면 판독 실행", type="primary", use_container_width=True)
            
            if uploaded_file:
                with st.expander("🔍 [대형 화면] 업로드 도면 정밀 확대 보기"):
                    file_ext = uploaded_file.name.split(".")[-1].lower()
                    if file_ext in ["png", "jpg", "jpeg"]:
                        st.image(uploaded_file, use_container_width=True)
                    elif file_ext == "pdf":
                        st.markdown(get_pdf_display_html(uploaded_file.getvalue(), height=750), unsafe_allow_html=True)

        with col_prev:
            if uploaded_file:
                st.caption("📄 원본 도면 요약 프리뷰")
                file_ext = uploaded_file.name.split(".")[-1].lower()
                if file_ext in ["png", "jpg", "jpeg"]:
                    st.image(uploaded_file, use_container_width=True)
                elif file_ext == "pdf":
                    st.markdown(get_pdf_display_html(uploaded_file.getvalue(), height=260), unsafe_allow_html=True)

        if ai_btn and uploaded_file and api_key:
            with st.spinner("Gemini 3.8 Flash가 형상, 가공 여유, 툴패스를 정밀 계산 중입니다..."):
                try:
                    client = genai.Client(api_key=api_key.strip())
                    mime_type = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"
                    doc_part = types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=mime_type)
                    
                    prompt = """
                    당신은 20년 경력의 절삭가공(MCT/CNC) 공장장입니다.
                    업로드된 도면을 분석하여 다음 항목을 JSON으로만 추출하세요.
                    {
                        "material_type": "재질 (예: AL6061, SUS304, S45C, SS400 등)",
                        "estimated_weight_kg": 숫자 (개당 예상 소재 중량 kg, 소수점 둘째자리),
                        "estimated_machining_hours": 숫자 (개당 순수 가공 소요 시간, 소수점 둘째자리),
                        "recommended_machine": "추천 설비 (3축 머시닝센터(MCT), 5축 머시닝센터(MCT), CNC 복합선반 중 1개)",
                        "holes_count": 숫자 (홀 총 개수),
                        "difficulty": "가공 난이도 (상, 중, 하)",
                        "reasoning": "산출 근거 (2줄 요약)"
                    }
                    """
                    resp = client.models.generate_content(
                        model=selected_model,
                        contents=[doc_part, prompt],
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    clean = resp.text.strip().replace("```json", "").replace("```", "").strip()
                    st.session_state["quote_ai_cache"] = json.loads(clean)
                    st.session_state["quote_filename"] = uploaded_file.name
                    st.success("AI 도면 판독이 완료되었습니다.")
                except Exception as e:
                    st.error(f"판독 에러: {str(e)}")

        if "quote_ai_cache" in st.session_state:
            cached = st.session_state["quote_ai_cache"]
            parsed_weight = float(cached.get("estimated_weight_kg", 0.5))
            parsed_hours = float(cached.get("estimated_machining_hours", 0.5))
            parsed_holes = cached.get("holes_count", 0)
            parsed_diff = cached.get("difficulty", "중")
            parsed_reasoning = cached.get("reasoning", "")
    else:
        st.session_state["quote_filename"] = st.text_input("품목명 / 도면 품번", value="BRACKET-M01")

    st.divider()
    st.markdown("#### 2. 가공 조건 및 단가 산정")
    
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        mat_keys = list(settings["materials"].keys())
        sel_material = st.selectbox("소재 재질", mat_keys)
    with sc2:
        mac_keys = list(settings["machines"].keys())
        sel_machine = st.selectbox("가공 설비", mac_keys)
    with sc3:
        surf_keys = list(settings["surface_treatments"].keys())
        sel_surface = st.selectbox("표면 / 후처리", surf_keys)
    with sc4:
        tol_grade = st.selectbox("공차 등급", ["일반 공차 (±0.1)", "정밀 공차 (±0.01 / +20% 공임)", "초정밀 공차 (±0.005 / +50% 공임)"])

    adj1, adj2, adj3 = st.columns([1, 1, 2])
    with adj1:
        final_weight = st.number_input("개당 소재 중량 (kg)", value=float(parsed_weight), step=0.05, format="%.2f")
    with adj2:
        final_hours = st.number_input("개당 가공 소요시간 (h)", value=float(parsed_hours), step=0.05, format="%.2f")
    with adj3:
        order_memo = st.text_input("현장 특이사항 / 도면 비고 메모", value=parsed_reasoning)

    tol_factor = 1.0
    if "정밀 공차" in tol_grade: tol_factor = 1.2
    elif "초정밀 공차" in tol_grade: tol_factor = 1.5

    mat_unit = settings["materials"][sel_material]
    mac_rate = settings["machines"][sel_machine]
    surf_unit = settings["surface_treatments"][sel_surface]
    setup_fee = settings["default_setup_fee"]
    margin_pct = settings["default_margin_rate"]

    mat_total = int(final_weight * mat_unit * order_qty)
    mac_total = int(final_hours * mac_rate * tol_factor * order_qty)
    surf_total = int(surf_unit * order_qty)
    subtotal = mat_total + mac_total + surf_total + setup_fee
    margin_val = int(subtotal * (margin_pct / 100))
    total_supply = subtotal + margin_val
    unit_price = int(total_supply / order_qty)

    now_id = datetime.now().strftime("%Y%m%d%H%M%S")
    quote_no = f"QT-{now_id[-8:]}"

    quote_payload = {
        "id": now_id,
        "quote_no": quote_no,
        "group_id": "",
        "status": "1. 견적제출",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "due_date": due_date.strftime("%Y-%m-%d"),
        "client_name": client_name,
        "client_manager": client_manager,
        "filename": st.session_state.get("quote_filename", "수동품목"),
        "qty": order_qty,
        "material": sel_material,
        "material_unit_price": mat_unit,
        "material_cost_total": mat_total,
        "machine_type": sel_machine,
        "machine_hourly_rate": mac_rate,
        "machining_cost_total": mac_total,
        "tolerance_factor": f"x{tol_factor}",
        "setup_fee": setup_fee,
        "surface": sel_surface,
        "surface_cost_total": surf_total,
        "subtotal": subtotal,
        "margin_rate": margin_pct,
        "margin_amount": margin_val,
        "total_price": total_supply,
        "unit_price": unit_price,
        "weight": final_weight,
        "hours": final_hours,
        "holes": parsed_holes,
        "difficulty": parsed_diff,
        "reasoning": parsed_reasoning,
        "memo": order_memo
    }

    pdf_bytes = create_formal_pdf(quote_payload)

    st.divider()
    res1, res2 = st.columns([1, 1])
    with res1:
        st.markdown("#### 📊 최종 견적 결과 지표")
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>개당 공급단가 (VAT별도)</div><div class='metric-value'>{unit_price:,} 원</div></div>", unsafe_allow_html=True)
        with m2:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>총 견적 금액 ({order_qty}개)</div><div class='metric-value' style='color:#38bdf8;'>{total_supply:,} 원</div></div>", unsafe_allow_html=True)
        
        st.write(f"- 원재료비 합계: **{mat_total:,} 원** | 순수가공비: **{mac_total:,} 원**")
        st.write(f"- 셋업비(초도 세팅): **{setup_fee:,} 원** | 후처리비: **{surf_total:,} 원**")
        
        b1, b2 = st.columns(2)
        with b1:
            st.download_button("📥 정식 견적서 PDF 다운로드", data=pdf_bytes, file_name=f"{quote_no}_{client_name}.pdf", mime="application/pdf", type="primary", use_container_width=True)
        with b2:
            if st.button("💾 발주/공정 DB에 즉시 등록", use_container_width=True):
                orders_db.insert(0, quote_payload)
                save_json(ORDERS_FILE, orders_db)
                st.success(f"견적 [{quote_no}] 건이 공정 관리 DB에 성공적으로 등록되었습니다!")
                st.rerun()

    with res2:
        st.markdown("#### 🖨️ 견적서 미리보기")
        st.markdown(get_pdf_display_html(pdf_bytes, height=360), unsafe_allow_html=True)
        with st.expander("🔍 [대형 화면] 견적서 풀스크린 정밀 확인"):
            st.markdown(get_pdf_display_html(pdf_bytes, height=800), unsafe_allow_html=True)

# ------------------------------------------
# TAB 2: 공정흐름 관리
# ------------------------------------------
with tab_process:
    st.subheader("🏭 실시간 가공 공정흐름 트래킹")
    if not orders_db:
        st.info("등록된 수주 건이 없습니다.")
    else:
        stat_cols = st.columns(len(PROCESS_STAGES))
        for idx, stage in enumerate(PROCESS_STAGES):
            count = sum(1 for o in orders_db if o.get("status") == stage)
            with stat_cols[idx]:
                st.markdown(f"<div class='metric-card'><div class='metric-label'>{stage}</div><div class='metric-value' style='font-size:18px;'>{count} 건</div></div>", unsafe_allow_html=True)

        st.divider()
        for idx, o in enumerate(orders_db):
            with st.expander(f"📌 [{o.get('quote_no')}] {o.get('client_name')} - {o.get('filename')} ({o.get('qty')}개 | {o.get('total_price',0):,}원 | 납기: {o.get('due_date')})"):
                row1, row2, row3 = st.columns([1.5, 2.5, 1])
                with row1:
                    cur_idx = PROCESS_STAGES.index(o.get("status", PROCESS_STAGES[0])) if o.get("status") in PROCESS_STAGES else 0
                    new_status = st.selectbox("현재 가공 단계", PROCESS_STAGES, index=cur_idx, key=f"status_{o['id']}")
                with row2:
                    new_memo = st.text_input("현장 메모", value=o.get("memo", ""), key=f"memo_{o['id']}")
                with row3:
                    st.write("")
                    st.write("")
                    if st.button("💾 상태 저장", key=f"save_{o['id']}", use_container_width=True):
                        orders_db[idx]["status"] = new_status
                        orders_db[idx]["memo"] = new_memo
                        save_json(ORDERS_FILE, orders_db)
                        st.success("저장 완료")
                        st.rerun()

# ------------------------------------------
# TAB 3: 납기 캘린더
# ------------------------------------------
with tab_calendar:
    st.subheader("📅 납기 스케줄 & D-Day 모니터링")
    if not orders_db:
        st.info("스케줄링할 수주 건이 없습니다.")
    else:
        today = datetime.today().date()
        cal_list = []
        for o in orders_db:
            due_str = o.get("due_date", "")
            try:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
                diff = (due_dt - today).days
                if diff < 0: d_day_str = f"⚠️ {abs(diff)}일 지연"
                elif diff == 0: d_day_str = "🔥 오늘 납기"
                else: d_day_str = f"D-{diff}"
            except Exception:
                d_day_str = "-"

            cal_list.append({
                "D-Day": d_day_str,
                "납기일": o.get("due_date"),
                "견적번호": o.get("quote_no"),
                "고객사": o.get("client_name"),
                "품목명": o.get("filename"),
                "수량": f"{o.get('qty', 1):,} EA",
                "현재공정": o.get("status"),
                "현장메모": o.get("memo", "")
            })
        st.dataframe(pd.DataFrame(cal_list).sort_values(by="납기일"), use_container_width=True)

# ------------------------------------------
# TAB 4: 묶음 발주 & 이력
# ------------------------------------------
with tab_history:
    st.subheader("📦 다품종 수주 묶음(그룹화) 및 과거 이력 관리")
    if not orders_db:
        st.info("데이터베이스가 비어 있습니다.")
    else:
        grp_c1, grp_c2 = st.columns([2, 1])
        with grp_c1:
            group_title_input = st.text_input("새 묶음 프로젝트명", placeholder="예: 반도체 라인 지그 4종 1차 발주")
        with grp_c2:
            st.write("")
            st.write("")
            create_group_btn = st.button("🔗 선택 항목 그룹화 실행", type="primary", use_container_width=True)

        selected_ids = []
        for idx, o in enumerate(orders_db):
            chk_col, info_col = st.columns([0.4, 9.6])
            with chk_col:
                if st.checkbox("", key=f"chk_{o['id']}"):
                    selected_ids.append(o["id"])
            with info_col:
                grp_tag = f"🏷️ [{o['group_id']}] " if o.get("group_id") else ""
                st.write(f"**{grp_tag}[{o.get('quote_no')}]** {o.get('client_name')} | **{o.get('filename')}** | 수량: {o.get('qty')}EA | 합계: **{o.get('total_price',0):,}원** | 납기: {o.get('due_date')} | 상태: `{o.get('status')}`")

        if create_group_btn:
            if not group_title_input.strip() or not selected_ids:
                st.warning("프로젝트명 입력 및 1개 이상의 항목을 체크하세요.")
            else:
                for o in orders_db:
                    if o["id"] in selected_ids:
                        o["group_id"] = group_title_input.strip()
                save_json(ORDERS_FILE, orders_db)
                st.success("그룹화 완료")
                st.rerun()

        st.divider()
        groups = {}
        for o in orders_db:
            if o.get("group_id"):
                groups.setdefault(o["group_id"], []).append(o)

        for gname, items in groups.items():
            tot_price = sum(it.get("total_price", 0) for it in items)
            tot_qty = sum(it.get("qty", 1) for it in items)
            with st.expander(f"📁 [그룹 발주] {gname} (총 {len(items)}종 | 수량: {tot_qty}EA | 총액: {tot_price:,} 원)"):
                sub_rows = [{"견적번호": it.get("quote_no"), "도면명": it.get("filename"), "수량": f"{it.get('qty'):,} EA", "단가": f"{it.get('unit_price',0):,} 원", "합계": f"{it.get('total_price',0):,} 원", "상태": it.get("status")} for it in items]
                st.dataframe(pd.DataFrame(sub_rows), use_container_width=True)

# ------------------------------------------
# TAB 5: 기준 단가 및 인가 계정 관리
# ------------------------------------------
with tab_settings:
    st.subheader("⚙️ 공장 기준 단가 및 사용자 계정 관리")
    if st.session_state["auth_user"]["role"] != "admin":
        st.warning("계정 관리 기능은 관리자(admin) 전용입니다.")
    else:
        u_col1, u_col2 = st.columns([1.5, 2.5])
        with u_col1:
            st.markdown("##### ➕ 새 작업자 계정 추가")
            new_uid = st.text_input("아이디")
            new_upw = st.text_input("비밀번호", type="password")
            new_uname = st.text_input("담당자명/공장명")
            new_urole = st.selectbox("권한", ["user", "admin"])
            if st.button("계정 생성", type="primary"):
                if new_uid and new_upw:
                    users_db[new_uid] = {"password": new_upw, "name": new_uname, "role": new_urole}
                    save_json(USERS_FILE, users_db)
                    st.success(f"[{new_uid}] 계정 생성 완료")
                    st.rerun()
        with u_col2:
            st.markdown("##### 👥 등록된 계정")
            st.dataframe(pd.DataFrame([{"아이디": k, "이름": v["name"], "권한": v["role"]} for k, v in users_db.items()]), use_container_width=True)

    st.divider()
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        c_name = st.text_input("상호명", value=settings["company_info"]["company_name"])
        c_biz = st.text_input("사업자번호", value=settings["company_info"]["biz_num"])
        c_ceo = st.text_input("대표자명", value=settings["company_info"]["ceo_name"])
    with sc2:
        c_tel = st.text_input("대표전화", value=settings["company_info"]["tel"])
        c_email = st.text_input("견적 이메일", value=settings["company_info"]["email"])
        c_addr = st.text_input("사업장 주소", value=settings["company_info"]["address"])
    with sc3:
        up_setup = st.number_input("기본 셋업비 (원)", value=int(settings.get("default_setup_fee", 50000)), step=5000)
        up_margin = st.number_input("표준 마진율 (%)", value=int(settings.get("default_margin_rate", 25)), step=5)

    st.markdown("---")
    st1, st2, st3 = st.columns(3)
    with st1:
        st.markdown("**재료비 (kg당 원)**")
        up_materials = {k: st.number_input(f"{k}", value=int(v), step=500) for k, v in settings["materials"].items()}
    with st2:
        st.markdown("**임가공비 (시간당 원)**")
        up_machines = {k: st.number_input(f"{k}", value=int(v), step=1000) for k, v in settings["machines"].items()}
    with st3:
        st.markdown("**표면처리비 (개당 원)**")
        up_surfaces = {k: st.number_input(f"{k}", value=int(v), step=500) for k, v in settings["surface_treatments"].items()}

    if st.button("💾 모든 설정 영구 저장", type="primary", use_container_width=True):
        new_conf = {
            "company_info": {"company_name": c_name, "biz_num": c_biz, "ceo_name": c_ceo, "tel": c_tel, "email": c_email, "address": c_addr},
            "materials": up_materials,
            "machines": up_machines,
            "surface_treatments": up_surfaces,
            "default_setup_fee": up_setup,
            "default_margin_rate": up_margin
        }
        save_json(SETTINGS_FILE, new_conf)
        st.success("단가 및 사업자 설정이 저장되었습니다.")