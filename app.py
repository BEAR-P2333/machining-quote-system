import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
import os
import json
import base64
import threading
import time
import calendar
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta

# ==========================================
# 0. 경로 및 한국 가공업 표준 데이터베이스 관리
# ==========================================
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(DATA_DIR, "pricing_settings.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders_database.json")
USERS_FILE = os.path.join(DATA_DIR, "system_users.json")

DEFAULT_USERS = {
    "admin": {"password": "admin1234!", "name": "총괄관리자", "role": "admin"},
    "factory1": {"password": "factory1234!", "name": "제1가공공장", "role": "user"},
    "sales": {"password": "sales1234!", "name": "영업팀장", "role": "user"}
}

# 한국 가공업계 현실 시세 표준 반영 기본 단가표
DEFAULT_SETTINGS = {
    "company_info": {
        "company_name": "Costify 가공 솔루션",
        "biz_num": "123-45-67890",
        "ceo_name": "홍길동",
        "tel": "031-123-4567",
        "email": "contact@costify.ai",
        "address": "경기도 시흥시 시화벤처로 123 Costify 빌딩"
    },
    "materials": {
        "AL6061 / 알루미늄": 5500,     # 실무 시세: 4,000~6,000원
        "SUS304 / 스테인리스": 8000,    # 실무 시세: 6,000~9,000원
        "SS400 / 일반 철": 2500,       # 실무 시세: 2,000~3,000원
        "S45C / 탄소강": 3500,        # 실무 시세: 3,000~4,500원
        "기타 / 미상": 5000
    },
    "machines": {
        "3축 머시닝센터(MCT)": 45000,  # 실무 시급: 35,000~50,000원
        "5축 머시닝센터(MCT)": 80000,  # 실무 시급: 60,000~90,000원 이상
        "CNC 복합선반": 45000,
        "범용 선반 / 밀링": 30000     # 실무 시급: 30,000원 선
    },
    "surface_treatments": {
        "무처리 (가공원형)": 0,
        "샌딩 / 아노다이징 (백색)": 5000,
        "아노다이징 (흑색/유색)": 7000,
        "무전해 니켈도금": 8000,
        "열처리 (QT/고주파)": 10000
    },
    "default_setup_fee": 30000,       # 초도 세팅비
    "min_machining_cost": 35000,      # ★ 가드레일: 최소 기본 공임 보정선 (3.5만원)
    "default_material_loss": 20,      # ★ 소재 절삭 여유분 로스율 (20%)
    "default_margin_rate": 20         # 표준 마진율 (20%)
}

STAGE_CONFIG = {
    "1. 견적제출": {"color": "#64748b", "icon": "📝"},
    "2. 발주확정": {"color": "#0284c7", "icon": "🔵"},
    "3. 소재입고": {"color": "#eab308", "icon": "🟡"},
    "4. 가공진행(MCT/선반)": {"color": "#f97316", "icon": "🟠"},
    "5. 열처리/후처리": {"color": "#a855f7", "icon": "🟣"},
    "6. 치수검사/세척": {"color": "#06b6d4", "icon": "🔷"},
    "7. 출하완료": {"color": "#10b981", "icon": "🟢"}
}
PROCESS_STAGES = list(STAGE_CONFIG.keys())

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
# 1. UI 환경 & 로그인 세션 관리
# ==========================================
st.set_page_config(page_title="Costify | AI 절삭가공 견적 & MES 솔루션", page_icon="⚡", layout="wide")

st.markdown("""
<style>
    .metric-card {
        background: #1e2430;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 6px;
        text-align: center;
    }
    .metric-label { color: #94a3b8; font-size: 11px; font-weight: 500; }
    .metric-value { color: #f8fafc; font-size: 20px; font-weight: 700; margin-top: 2px; }
    
    .guardrail-box {
        background-color: #451a03;
        border: 1px solid #b45309;
        border-radius: 6px;
        padding: 10px 14px;
        color: #fef3c7;
        font-size: 13px;
        margin: 10px 0;
    }

    .cal-header {
        background-color: #0f172a;
        color: #94a3b8;
        padding: 8px;
        text-align: center;
        font-weight: 700;
        border: 1px solid #334155;
    }
    .cal-day-cell {
        min-height: 105px;
        background-color: #1e293b;
        border: 1px solid #334155;
        padding: 6px;
        vertical-align: top;
    }
    .cal-day-cell.other-month {
        background-color: #0f172a;
        opacity: 0.35;
    }
    .cal-day-cell.today {
        border: 2px solid #38bdf8 !important;
    }
    .cal-badge {
        font-size: 10px;
        padding: 2px 4px;
        border-radius: 3px;
        margin-top: 3px;
        color: white;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
    }
</style>
""", unsafe_allow_html=True)

def open_in_new_tab_button(file_bytes, mime_type, label="🔍 새 창에서 전체화면 보기"):
    b64 = base64.b64encode(file_bytes).decode('utf-8')
    js_code = f"""
    <div style="margin: 6px 0;">
        <button onclick="openBlob()" style="
            background-color: #0284c7;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
        ">{label}</button>
    </div>
    <script>
    function openBlob() {{
        const b64Data = '{b64}';
        const contentType = '{mime_type}';
        const byteCharacters = atob(b64Data);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {{
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }}
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], {{type: contentType}});
        const blobUrl = URL.createObjectURL(blob);
        window.open(blobUrl, '_blank');
    }}
    </script>
    """
    components.html(js_code, height=48)

# 로그인 검증
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

if not st.session_state["auth_user"]:
    _, login_c2, _ = st.columns([1, 1.2, 1])
    with login_c2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("⚡ Costify 포털 로그인")
        st.caption("한국 정밀절삭가공 표준 견적 & MES 플랫폼")
        
        with st.form("login_form"):
            in_id = st.text_input("아이디 (ID)")
            in_pw = st.text_input("비밀번호", type="password")
            submit_login = st.form_submit_button("시스템 접속", use_container_width=True, type="primary")
            
            if submit_login:
                if in_id in users_db and users_db[in_id]["password"] == in_pw:
                    st.session_state["auth_user"] = users_db[in_id]
                    st.session_state["auth_user_id"] = in_id
                    st.rerun()
                else:
                    st.error("계정 정보가 올바르지 않습니다.")
        st.info("💡 초기 관리자 계정: `admin` / 비밀번호: `admin1234!`")
    st.stop()

# ==========================================
# 2. 503 방어 백그라운드 AI 분석 엔진
# ==========================================
if "bg_task" not in st.session_state:
    st.session_state["bg_task"] = {
        "status": "idle",
        "result": None,
        "error": None,
        "filename": ""
    }

def bg_analysis_worker(api_key, model_name, file_bytes, mime_type, filename, task_store):
    client = genai.Client(api_key=api_key.strip())
    doc_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    
    # 한국 가공업계 표준 규칙을 주입한 프롬프트 엔지니어링
    prompt = """
    당신은 한국 20년 경력의 베테랑 절삭가공(MCT/CNC) 공장장입니다.
    업로드된 도면을 분석하여 다음 항목을 반드시 순수한 JSON 형식으로만 추출하세요.
    
    [필수 분석 가이드]
    1. material_type: 도면 표제란 표기 재질 (AL6061, SUS304, SS400, S45C 등). 미기재시 형상 기반 추정.
    2. pure_weight_kg: 완제품 기준 순수 중량 (kg).
    3. cutting_loss_percent: 사각/환봉 원소재 절삭 가공 시 필요한 여유분 로스율 (%) (기본 15%~25% 범위).
    4. estimated_machining_hours: 순수 절삭 가공 소요 시간 (h) (황삭, 정삭, 홀, 탭 등 포함).
    5. recommended_machine: 3축 머시닝센터(MCT), 5축 머시닝센터(MCT), CNC 복합선반, 범용 선반 / 밀링 중 최적 장비.
    6. difficulty_factor: 난이도 계수 (1.0~1.8). (단순 평면/홀=1.0, 깊은 포켓/박판=1.2, 미세공차(±0.01) 및 탭 다수=1.3~1.5, 5축 형상=1.6~1.8)
    7. holes_count: 가공 홀 수량.
    8. reasoning: 산출 근거 (형상 특이사항 및 난이도 2줄 요약).

    JSON 출력 스키마:
    {
        "material_type": "재질 문자열",
        "pure_weight_kg": 숫자,
        "cutting_loss_percent": 숫자,
        "estimated_machining_hours": 숫자,
        "recommended_machine": "추천설비 문자열",
        "difficulty_factor": 숫자,
        "holes_count": 숫자,
        "difficulty": "상/중/하",
        "reasoning": "산출 근거 요약"
    }
    """
    
    models_to_try = [model_name]
    if "gemini-2.5-flash" not in models_to_try:
        models_to_try.append("gemini-2.5-flash")

    last_error_msg = ""
    for target_model in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=target_model,
                    contents=[doc_part, prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                clean = response.text.strip().replace("```json", "").replace("```", "").strip()
                task_store["result"] = json.loads(clean)
                task_store["filename"] = filename
                task_store["status"] = "completed"
                return
            except Exception as e:
                last_error_msg = str(e)
                if any(x in last_error_msg for x in ["503", "UNAVAILABLE", "429"]):
                    time.sleep(2 * (attempt + 1))
                    continue
                else:
                    break

    task_store["error"] = f"구글 AI 트래픽 급증(503)으로 재시도 후에도 연결되지 않았습니다. 잠시 후 다시 시도해 주세요. ({last_error_msg})"
    task_store["status"] = "error"

# 상단 헤더
head_l, head_r = st.columns([3, 1])
with head_l:
    st.title("⚡ Costify | 한국 가공업 표준 견적 & MES")
    st.caption(f"접속자: **{st.session_state['auth_user']['name']}** ({st.session_state['auth_user']['role']}) | 운영: {settings['company_info']['company_name']}")
with head_r:
    if st.button("🚪 로그아웃", use_container_width=True):
        st.session_state["auth_user"] = None
        st.rerun()

# 사이드바
with st.sidebar:
    st.markdown("### ⚡ Costify 엔진")
    default_api_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key = st.text_input("Gemini API Key", value=default_api_key, type="password", help="Vision 분석용 API Key입니다.")
    selected_model = st.selectbox("기본 AI 모델", ["gemini-3.8-flash", "gemini-2.5-flash"], index=0)
    st.divider()
    st.markdown("### 🛡️ 현장 가드레일 설정")
    st.caption(f"- 최소 가공비 보정: **{settings.get('min_machining_cost', 35000):,} 원**")
    st.caption(f"- 소재 가공 로스율: **+{settings.get('default_material_loss', 20)} %**")
    st.caption(f"- 표준 마진율: **{settings['default_margin_rate']} %**")

if st.session_state["bg_task"]["status"] == "running":
    st.info("🔄 **[백그라운드 실행 중]** 도면을 분석 중입니다... 다른 탭에서 작업을 계속 진행하셔도 됩니다.")
elif st.session_state["bg_task"]["status"] == "completed":
    st.success("✅ **[분석 완료]** 도면 판독이 완료되었습니다. 아래 검수 시뮬레이터를 확인하세요.")
elif st.session_state["bg_task"]["status"] == "error":
    st.error(f"❌ 분석 실패: {st.session_state['bg_task']['error']}")

# ==========================================
# 3. PDF 견적서 생성 유틸리티
# ==========================================
def create_formal_pdf(q):
    pdf = FPDF(format="A4")
    pdf.add_page()
    
    font_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
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
    pdf.cell(0, 12, "Costify 표준 가공 견적서", ln=True, align="C")
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
    pdf.cell(86, 5, f"진행상태: {q.get('status', '1. 견적제출')}", ln=True)

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
    pdf.cell(0, 9, f"견적 공급가 총계: 일금 {q.get('total_price', 0):,} 원정 (VAT 별도)", border=1, ln=True, align="C")
    pdf.ln(3)

    pdf.set_font(bold_font, size=8)
    pdf.cell(38, 7, "품명 및 사양", border=1, align="C")
    pdf.cell(16, 7, "수량", border=1, align="C")
    pdf.cell(34, 7, "재질 / 총중량", border=1, align="C")
    pdf.cell(36, 7, "적용설비 / 후처리", border=1, align="C")
    pdf.cell(32, 7, "개당 단가", border=1, align="C")
    pdf.cell(34, 7, "합계 공급가", border=1, align="C")
    pdf.ln()

    pdf.set_font(main_font, size=8)
    pdf.cell(38, 7, str(q.get('filename', '도면'))[:16], border=1, align="C")
    pdf.cell(16, 7, f"{q.get('qty', 1):,} EA", border=1, align="C")
    pdf.cell(34, 7, f"{str(q.get('material','')).split('/')[0]} ({q.get('raw_weight',0)}kg)", border=1, align="C")
    pdf.cell(36, 7, f"{str(q.get('machine_type','')).split()[0]} / {str(q.get('surface','')).split()[0]}", border=1, align="C")
    pdf.cell(32, 7, f"{q.get('unit_price', 0):,} 원", border=1, align="R")
    pdf.cell(34, 7, f"{q.get('total_price', 0):,} 원", border=1, align="R")
    pdf.ln(10)

    pdf.set_font(bold_font, size=9)
    pdf.cell(0, 6, "[ Costify 한국 가공 표준 원가 산출 명세 ]", ln=True)
    pdf.set_font(main_font, size=8)
    pdf.cell(0, 5, f"1. 원재료비 : {q.get('material_cost_total', 0):,} 원 (개당 소재 {q.get('raw_weight', 0)}kg[로스율 {q.get('loss_rate',20)}%포함] x {q.get('material_unit_price', 0):,}원 x {q.get('qty', 1)}개)", ln=True)
    pdf.cell(0, 5, f"2. 순수가공비 : {q.get('machining_cost_total', 0):,} 원 (시간 {q.get('hours', 0)}h x 시급 {q.get('machine_hourly_rate', 0):,}원 x 난이도 {q.get('difficulty_factor', 1.0)} x {q.get('qty', 1)}개)", ln=True)
    if q.get('guardrail_applied'):
        pdf.cell(0, 4, f"   ※ [가드레일 적용] 계산된 공임이 최소기준({settings.get('min_machining_cost', 35000):,}원) 미달하여 최소 기본공임으로 보정됨", ln=True)
    pdf.cell(0, 5, f"3. 초도 세팅비 : {q.get('setup_fee', 0):,} 원 (수량 분산: 개당 {int(q.get('setup_fee',0)/max(q.get('qty',1),1)):,}원)", ln=True)
    pdf.cell(0, 5, f"4. 표면/후처리비 : {q.get('surface_cost_total', 0):,} 원 ({q.get('surface', '무처리')})", ln=True)
    pdf.cell(0, 5, f"5. 일반관리비 및 마진 ({q.get('margin_rate', 20)}%): {q.get('margin_amount', 0):,} 원", ln=True)
    
    if q.get('memo'):
        pdf.ln(2)
        pdf.set_font(bold_font, size=8)
        pdf.cell(0, 5, f"[ 현장 엔지니어 소견 ]: {q.get('memo')}", ln=True)

    return bytes(pdf.output())

# ==========================================
# 4. 메인 탭 구성
# ==========================================
tab_quote, tab_process, tab_calendar, tab_history, tab_settings = st.tabs([
    "🚀 실시간 견적 산출",
    "🏭 공정흐름 관리 (MES)",
    "📅 납기 캘린더 (한국 표준)",
    "📦 묶음 발주 & 이력",
    "⚙️ 단가 및 시스템 관리"
])

# ------------------------------------------
# TAB 1: 실시간 견적 산출
# ------------------------------------------
with tab_quote:
    st.markdown("#### 1. 수주 기본 사양 등록")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        client_name = st.text_input("고객사(발주처)", value="(주)한국정밀")
    with c2:
        client_manager = st.text_input("담당자 성함/직함", value="김철수 부장")
    with c3:
        order_qty = st.number_input("발주 수량 (EA)", min_value=1, value=10, step=1)
    with c4:
        due_date = st.date_input("납기 요청일", value=datetime.today() + timedelta(days=12))

    quote_mode = st.radio("견적 모드 선택", ["🤖 AI 도면 비전 자동 판독", "✍️ 엔지니어 직접 수동 입력"], horizontal=True)

    uploaded_file = None
    if quote_mode == "🤖 AI 도면 비전 자동 판독":
        col_up, col_btn = st.columns([2, 1])
        with col_up:
            uploaded_file = st.file_uploader("도면 업로드 (PDF, PNG, JPG, JPEG)", type=["pdf", "png", "jpg", "jpeg"])
        
        with col_btn:
            st.write("")
            st.write("")
            start_ai = st.button("⚡ AI 분석 시작 (백그라운드)", type="primary", use_container_width=True)

        if uploaded_file:
            file_mime = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"
            open_in_new_tab_button(uploaded_file.getvalue(), file_mime, label="🔍 [새 창] 업로드 도면 전체화면 확인")

        if start_ai and uploaded_file and api_key:
            if st.session_state["bg_task"]["status"] != "running":
                st.session_state["bg_task"]["status"] = "running"
                st.session_state["bg_task"]["result"] = None
                st.session_state["bg_task"]["error"] = None
                
                t = threading.Thread(
                    target=bg_analysis_worker,
                    args=(
                        api_key,
                        selected_model,
                        uploaded_file.getvalue(),
                        file_mime,
                        uploaded_file.name,
                        st.session_state["bg_task"]
                    )
                )
                t.daemon = True
                t.start()
                st.rerun()

    else:
        st.session_state["manual_filename"] = st.text_input("품목명 / 도면 품번", value="BRACKET-M01")

    # AI 판독 결과 캐싱 로드
    active_analysis = st.session_state["bg_task"].get("result")
    current_fname = st.session_state["bg_task"].get("filename", "") if quote_mode == "🤖 AI 도면 비전 자동 판독" else st.session_state.get("manual_filename", "수동품목")

    # 기본 파라미터 도출
    ai_pure_weight = float(active_analysis.get("pure_weight_kg", active_analysis.get("estimated_weight_kg", 0.5))) if active_analysis else 0.5
    ai_loss_rate = float(active_analysis.get("cutting_loss_percent", settings.get("default_material_loss", 20))) if active_analysis else float(settings.get("default_material_loss", 20))
    ai_hours = float(active_analysis.get("estimated_machining_hours", 0.5)) if active_analysis else 0.5
    ai_difficulty_factor = float(active_analysis.get("difficulty_factor", 1.0)) if active_analysis else 1.0
    ai_reasoning = active_analysis.get("reasoning", "") if active_analysis else ""
    ai_holes = active_analysis.get("holes_count", 0) if active_analysis else 0

    st.divider()
    st.markdown("#### 2. 현장 사장님 정밀 검수 & 실시간 시뮬레이터 (Guardrail)")
    st.caption("AI의 판독값을 사장님의 현장 노하우에 맞게 슬라이더로 조절하면 실시간으로 견적이 재계산됩니다.")

    # 1행: 재질, 설비, 후처리
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        mat_keys = list(settings["materials"].keys())
        def_mat_idx = 0
        if active_analysis:
            for idx, m_k in enumerate(mat_keys):
                if any(x in active_analysis.get("material_type", "").upper() for x in m_k.split()[0].split("/")):
                    def_mat_idx = idx
                    break
        sel_material = st.selectbox("소재 재질 (단가표 기준)", mat_keys, index=def_mat_idx)

    with sc2:
        mac_keys = list(settings["machines"].keys())
        def_mac_idx = 0
        if active_analysis:
            for idx, m_k in enumerate(mac_keys):
                if m_k.split()[0] in active_analysis.get("recommended_machine", ""):
                    def_mac_idx = idx
                    break
        sel_machine = st.selectbox("가공 설비 (시간당 공임)", mac_keys, index=def_mac_idx)

    with sc3:
        surf_keys = list(settings["surface_treatments"].keys())
        sel_surface = st.selectbox("표면 / 후처리", surf_keys)

    # 2행: 사장님 정밀 조정 슬라이더바 (가공시간, 난이도 계수, 로스율)
    sl_col1, sl_col2, sl_col3 = st.columns(3)
    with sl_col1:
        # 가공 소요시간 슬라이더 (0.1h ~ 20.0h)
        adj_hours = st.slider(
            "⏱️ 개당 순수 가공시간 (시간)",
            min_value=0.1,
            max_value=15.0,
            value=float(round(ai_hours, 2)),
            step=0.05,
            help="AI가 예측한 가공 시간입니다. 현장 난이도에 맞게 슬라이더로 즉시 보정하세요."
        )
    with sl_col2:
        # 난이도 계수 슬라이더 (1.0 ~ 1.8)
        adj_difficulty = st.slider(
            "⚙️ 가공 난이도 계수 (배율)",
            min_value=1.0,
            max_value=1.8,
            value=float(round(ai_difficulty_factor, 2)),
            step=0.05,
            help="1.0(단순형상) ~ 1.2(깊은포켓/박판) ~ 1.4(미세공차/탭다수) ~ 1.8(초정밀난삭재)"
        )
    with sl_col3:
        # 소재 절삭 여유분 로스율 슬라이더 (10% ~ 40%)
        adj_loss_rate = st.slider(
            "📐 소재 절삭 로스율 (%)",
            min_value=10,
            max_value=40,
            value=int(ai_loss_rate),
            step=5,
            help="절삭 가공 시 깎여나가는 여유분입니다. 기본 20%가 적용됩니다."
        )

    # 순수 중량 및 메모 입력
    w_col1, w_col2 = st.columns([1, 2])
    with w_col1:
        adj_pure_weight = st.number_input("완제품 순수 중량 (kg)", value=float(round(ai_pure_weight, 2)), step=0.05, format="%.2f")
    with w_col2:
        order_memo = st.text_input("현장 특이사항 / 도면 비고 메모", value=ai_reasoning)

    # ==========================================
    # ★ 한국 가공 표준 산식 및 가드레일 로직
    # ==========================================
    # 1. 원재료비 산출: (제품 부피중량 + 로스율) * kg당 고시단가
    raw_material_weight = adj_pure_weight * (1.0 + (adj_loss_rate / 100.0))
    mat_unit_price = settings["materials"][sel_material]
    mat_total_cost = int(raw_material_weight * mat_unit_price * order_qty)

    # 2. 순수가공비 산출: 가동시간 * 시간당시급 * 난이도계수
    mac_hourly_rate = settings["machines"][sel_machine]
    calculated_machining_cost = int(adj_hours * mac_hourly_rate * adj_difficulty * order_qty)

    # ★ 3. 가드레일(Guardrail) 발동 검사: 최소 가공비(MIM) 보정
    min_machining_threshold = settings.get("min_machining_cost", 35000)
    guardrail_triggered = False

    if calculated_machining_cost < min_machining_threshold:
        final_machining_cost = min_machining_threshold
        guardrail_triggered = True
    else:
        final_machining_cost = calculated_machining_cost

    # 4. 기타 부대비용 및 마진 합산
    surf_unit_price = settings["surface_treatments"][sel_surface]
    surf_total_cost = int(surf_unit_price * order_qty)
    setup_fee = settings.get("default_setup_fee", 30000)
    margin_pct = settings.get("default_margin_rate", 20)

    subtotal_manufacturing = mat_total_cost + final_machining_cost + surf_total_cost + setup_fee
    margin_amount = int(subtotal_manufacturing * (margin_pct / 100.0))
    final_total_supply = subtotal_manufacturing + margin_amount
    final_unit_price = int(final_total_supply / order_qty)

    # 가드레일 알림 뱃지
    if guardrail_triggered:
        st.markdown(f"""
        <div class="guardrail-box">
            🛡️ <b>[최소 가공비(MIM) 가드레일 발동]</b><br>
            계산된 순수 가공비(<b>{calculated_machining_cost:,}원</b>)가 업계 최소 기본공임 기준(<b>{min_machining_threshold:,}원</b>)보다 낮아, 
            초도 세팅 및 기본 수공 비용 보전을 위해 <b>{min_machining_threshold:,}원</b>으로 자동 상향 보정되었습니다.
        </div>
        """, unsafe_allow_html=True)

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
        "filename": current_fname if current_fname else "도면",
        "qty": order_qty,
        "material": sel_material,
        "material_unit_price": mat_unit_price,
        "raw_weight": round(raw_material_weight, 2),
        "pure_weight": round(adj_pure_weight, 2),
        "loss_rate": adj_loss_rate,
        "material_cost_total": mat_total_cost,
        "machine_type": sel_machine,
        "machine_hourly_rate": mac_hourly_rate,
        "hours": round(adj_hours, 2),
        "difficulty_factor": round(adj_difficulty, 2),
        "machining_cost_total": final_machining_cost,
        "guardrail_applied": guardrail_triggered,
        "setup_fee": setup_fee,
        "surface": sel_surface,
        "surface_cost_total": surf_total_cost,
        "subtotal": subtotal_manufacturing,
        "margin_rate": margin_pct,
        "margin_amount": margin_amount,
        "total_price": final_total_supply,
        "unit_price": final_unit_price,
        "memo": order_memo
    }

    pdf_bytes = create_formal_pdf(quote_payload)

    # 3단계: 최종 견적 지표 및 출력
    st.divider()
    res1, res2 = st.columns([1, 1])
    with res1:
        st.markdown("#### 📊 최종 견적 브레이크다운")
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>개당 납품단가 (VAT별도)</div><div class='metric-value'>{final_unit_price:,} 원</div></div>", unsafe_allow_html=True)
        with m2:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>총 공급가액 ({order_qty}개)</div><div class='metric-value' style='color:#38bdf8;'>{final_total_supply:,} 원</div></div>", unsafe_allow_html=True)

        st.write(f"- 📦 **원소재비**: {mat_total_cost:,} 원 (개당 소재 {round(raw_material_weight,2)}kg x {mat_unit_price:,}원)")
        st.write(f"- ⚙️ **가공공임**: {final_machining_cost:,} 원 (시급 {mac_hourly_rate:,}원 x {adj_hours}h x 난이도 {adj_difficulty})")
        st.write(f"- 🔧 **초도세팅비**: {setup_fee:,} 원 | 🎨 **후처리비**: {surf_total_cost:,} 원")
        st.write(f"- 📈 **기업이윤(마진 {margin_pct}%)**: {margin_amount:,} 원")

        b1, b2 = st.columns(2)
        with b1:
            st.download_button("📥 견적서 PDF 다운로드", data=pdf_bytes, file_name=f"{quote_no}_{client_name}.pdf", mime="application/pdf", type="primary", use_container_width=True)
        with b2:
            if st.button("💾 Costify 시스템에 영구 저장", use_container_width=True):
                orders_db.insert(0, quote_payload)
                save_json(ORDERS_FILE, orders_db)
                st.success(f"견적 [{quote_no}] 건이 성공적으로 등록되었습니다.")
                st.rerun()

    with res2:
        st.markdown("#### 🖨️ 정식 견적서 새 창 미리보기")
        open_in_new_tab_button(pdf_bytes, "application/pdf", label="🔍 [새 창] Costify 견적서 전체화면 열기")

# ------------------------------------------
# TAB 2: 공정흐름 관리 (원클릭 필터링 & 시각적 파이프라인)
# ------------------------------------------
with tab_process:
    st.subheader("🏭 실시간 가공 공정흐름 관리 (MES)")
    st.caption("상단 단계 버튼을 누르면 해당 공정 항목만 필터링되어 즉시 확인 가능합니다.")

    if "stage_filter" not in st.session_state:
        st.session_state["stage_filter"] = "전체"

    if not orders_db:
        st.info("등록된 가공 수주 건이 없습니다.")
    else:
        cols = st.columns(len(PROCESS_STAGES) + 1)
        with cols[0]:
            is_active = (st.session_state["stage_filter"] == "전체")
            btn_label = f"📋 전체보기\n({len(orders_db)}건)"
            if st.button(btn_label, use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state["stage_filter"] = "전체"
                st.rerun()

        for idx, stage in enumerate(PROCESS_STAGES):
            with cols[idx + 1]:
                cnt = sum(1 for o in orders_db if o.get("status") == stage)
                cfg = STAGE_CONFIG[stage]
                is_active = (st.session_state["stage_filter"] == stage)
                btn_label = f"{cfg['icon']} {stage.split('.')[1][:4]}\n({cnt}건)"
                if st.button(btn_label, use_container_width=True, type="primary" if is_active else "secondary"):
                    st.session_state["stage_filter"] = stage
                    st.rerun()

        current_filter = st.session_state["stage_filter"]
        filtered_orders = orders_db if current_filter == "전체" else [o for o in orders_db if o.get("status") == current_filter]

        st.divider()
        st.markdown(f"##### 📌 **[{current_filter}]** 목록 (총 {len(filtered_orders)}건)")

        if not filtered_orders:
            st.info(f"현재 '{current_filter}' 단계에 있는 가공 건이 없습니다.")
        else:
            for idx, o in enumerate(filtered_orders):
                stage_name = o.get("status", "1. 견적제출")
                cfg = STAGE_CONFIG.get(stage_name, {"color": "#64748b", "icon": "📝"})
                
                header_title = f"{cfg['icon']} [{stage_name}] | {o.get('quote_no')} - {o.get('client_name')} : {o.get('filename')} ({o.get('qty')}EA) | 납기: {o.get('due_date')}"
                
                with st.expander(header_title, expanded=(current_filter != "전체")):
                    step_idx = PROCESS_STAGES.index(stage_name) if stage_name in PROCESS_STAGES else 0
                    step_html = "<div style='display: flex; gap: 4px; margin-bottom: 12px;'>"
                    for s_i, s_name in enumerate(PROCESS_STAGES):
                        bg = STAGE_CONFIG[s_name]['color'] if s_i <= step_idx else "#334155"
                        opac = "1.0" if s_i == step_idx else ("0.55" if s_i < step_idx else "0.25")
                        border = "2px solid #fff" if s_i == step_idx else "1px solid #1e293b"
                        step_html += f"<div style='flex:1; background-color:{bg}; opacity:{opac}; border:{border}; padding:6px 2px; text-align:center; border-radius:4px; font-size:11px; font-weight:700; color:#fff;'>{s_name.split('.')[1][:4]}</div>"
                    step_html += "</div>"
                    st.markdown(step_html, unsafe_allow_html=True)

                    row1, row2, row3 = st.columns([1.5, 2.5, 1])
                    with row1:
                        new_status = st.selectbox("진행 단계 변경", PROCESS_STAGES, index=step_idx, key=f"status_{o['id']}")
                    with row2:
                        new_memo = st.text_input("현장 공정 메모 (특이사항, 외주/열처리 현황 등)", value=o.get("memo", ""), key=f"memo_{o['id']}")
                    with row3:
                        st.write("")
                        st.write("")
                        if st.button("💾 상태 저장", key=f"save_{o['id']}", use_container_width=True):
                            for real_idx, target in enumerate(orders_db):
                                if target["id"] == o["id"]:
                                    orders_db[real_idx]["status"] = new_status
                                    orders_db[real_idx]["memo"] = new_memo
                                    break
                            save_json(ORDERS_FILE, orders_db)
                            st.success("공정 정보가 저장되었습니다.")
                            st.rerun()

# ------------------------------------------
# TAB 3: 납기 캘린더 (한국 표준 월간 달력)
# ------------------------------------------
with tab_calendar:
    st.subheader("📅 납기 캘린더 (한국 표준)")
    cal_mode = st.radio("보기 모드 선택", ["📆 월간 달력 그리드 (Korean Month Grid)", "📋 상세 납기 리스트"], horizontal=True)

    today = datetime.today().date()

    if cal_mode == "📆 월간 달력 그리드 (Korean Month Grid)":
        cal_col1, cal_col2, _ = st.columns([1.2, 1.2, 3])
        with cal_col1:
            cal_year = st.selectbox("연도 선택", range(today.year - 1, today.year + 3), index=1)
        with cal_col2:
            cal_month = st.selectbox("월 선택", range(1, 13), index=today.month - 1)

        cal = calendar.Calendar(firstweekday=6)
        month_days = cal.monthdatescalendar(cal_year, cal_month)

        week_headers = ["일 (Sun)", "월 (Mon)", "화 (Tue)", "수 (Wed)", "목 (Thu)", "금 (Fri)", "토 (Sat)"]
        grid_html = "<table style='width:100%; border-collapse:collapse; margin-top:8px;'><thead><tr>"
        for i, wh in enumerate(week_headers):
            color = "#f87171" if i == 0 else ("#60a5fa" if i == 6 else "#94a3b8")
            grid_html += f"<th class='cal-header' style='color:{color}; width:14.28%;'>{wh}</th>"
        grid_html += "</tr></thead><tbody>"

        for week in month_days:
            grid_html += "<tr>"
            for day_date in week:
                is_cur_month = (day_date.month == cal_month)
                is_today = (day_date == today)
                cell_class = "cal-day-cell"
                if not is_cur_month: cell_class += " other-month"
                if is_today: cell_class += " today"

                day_str = day_date.strftime("%Y-%m-%d")
                day_num = day_date.day

                matching_orders = [o for o in orders_db if o.get("due_date") == day_str]

                grid_html += f"<td class='{cell_class}'>"
                day_color = "#f87171" if day_date.weekday() == 6 else ("#60a5fa" if day_date.weekday() == 5 else "#f8fafc")
                grid_html += f"<div style='font-weight:700; font-size:12px; color:{day_color};'>{day_num}</div>"

                for mo in matching_orders:
                    st_name = mo.get("status", "1. 견적제출")
                    badge_color = STAGE_CONFIG.get(st_name, {}).get("color", "#0284c7")
                    is_overdue = (day_date < today and st_name != "7. 출하완료")
                    border_style = "border:1px solid #ef4444;" if is_overdue else ""
                    tag_prefix = "⚠️ " if is_overdue else ""
                    grid_html += f"<div class='cal-badge' style='background-color:{badge_color}; {border_style}' title='[{mo.get('client_name')}] {mo.get('filename')} ({mo.get('qty')}개) - {st_name}'>{tag_prefix}{mo.get('client_name')[:4]} | {mo.get('filename')[:6]}</div>"

                grid_html += "</td>"
            grid_html += "</tr>"
        grid_html += "</tbody></table>"

        st.markdown(grid_html, unsafe_allow_html=True)
        st.caption("※ 붉은 테두리(⚠️): 납기일이 지났으나 아직 '7. 출하완료'되지 않은 지연 건입니다.")

    else:
        if not orders_db:
            st.info("스케줄링할 수주 건이 없습니다.")
        else:
            cal_list = []
            for o in orders_db:
                due_str = o.get("due_date", "")
                try:
                    due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
                    diff = (due_dt - today).days
                    if diff < 0: d_day_str = f"⚠️ {abs(diff)}일 지연"
                    elif diff == 0: d_day_str = "🔥 오늘 납기 (D-Day)"
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
        st.info("등록된 견적 이력이 없습니다.")
    else:
        grp_c1, grp_c2 = st.columns([2, 1])
        with grp_c1:
            group_title_input = st.text_input("새 묶음 프로젝트명", placeholder="예: 2차 라인 반도체 지그 4종 묶음")
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
# TAB 5: 기준 단가 & 영구 데이터 관리
# ------------------------------------------
with tab_settings:
    st.subheader("⚙️ 단가표 및 Costify 데이터베이스 관리")
    
    st.markdown("#### 1. 데이터 영구 보관 & 백업/복원")
    b_col1, b_col2 = st.columns(2)
    with b_col1:
        st.caption("현재 시스템의 모든 수주/견적 내역을 JSON 파일로 백업합니다.")
        st.download_button(
            "💾 전체 수주 DB 백업 다운로드",
            data=json.dumps(orders_db, ensure_ascii=False, indent=2),
            file_name=f"costify_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )
    with b_col2:
        st.caption("기존 백업 파일을 업로드하여 시스템에 즉시 복원합니다.")
        restore_file = st.file_uploader("백업 파일(.json) 선택", type=["json"])
        if restore_file:
            if st.button("📂 데이터 복원 실행", use_container_width=True):
                try:
                    restored_data = json.load(restore_file)
                    save_json(ORDERS_FILE, restored_data)
                    st.success("데이터베이스가 성공적으로 복원되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"복원 실패: {str(e)}")

    st.divider()
    st.markdown("#### 2. 사용자 계정 관리 (회원가입 차단)")
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
    st.markdown("#### 3. 공급사 정보 및 한국 표준 기준 단가표")
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
        up_setup = st.number_input("기본 셋업비 (원)", value=int(settings.get("default_setup_fee", 30000)), step=5000)
        up_min_machine = st.number_input("🛡️ 최소 가공비(MIM) 보정선 (원)", value=int(settings.get("min_machining_cost", 35000)), step=5000, help="계산 공임이 이 값보다 낮으면 자동 보정됩니다.")
        up_margin = st.number_input("표준 마진율 (%)", value=int(settings.get("default_margin_rate", 20)), step=5)

    st.markdown("---")
    st1, st2, st3 = st.columns(3)
    with st1:
        st.markdown("**재료비 (kg당 원 - 실무 시세 반영)**")
        up_materials = {k: st.number_input(f"{k}", value=int(v), step=500) for k, v in settings["materials"].items()}
    with st2:
        st.markdown("**임가공비 (시간당 원 - 실무 시급 반영)**")
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
            "min_machining_cost": up_min_machine,
            "default_material_loss": settings.get("default_material_loss", 20),
            "default_margin_rate": up_margin
        }
        save_json(SETTINGS_FILE, new_conf)
        st.success("단가 및 가드레일 설정이 저장되었습니다.")
