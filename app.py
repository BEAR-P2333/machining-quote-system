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
import hashlib
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta

# ==========================================
# 0. 시스템 버전 및 릴리즈 노트 데이터
# ==========================================
CURRENT_SYSTEM_VERSION = "v1.4.0"

SYSTEM_RELEASE_NOTES = [
    {
        "version": "v1.4.0",
        "date": "2026-10-25",
        "title": "보안 강화 및 릴리즈 노트 도입",
        "details": [
            "로그인 화면의 기본 계정 힌트 영구 제거 (보안 강화)",
            "우측 상단 업데이트 릴리즈 노트 팝업 및 미확인 알림 점(Red Dot) 기능 추가",
            "URL 접속 세션 안정화"
        ]
    },
    {
        "version": "v1.3.0",
        "date": "2026-10-24",
        "title": "한국 가공업 표준 산식 & 가드레일 탑재",
        "details": [
            "원소재 가공 여유분 로스율(15~25%) 산식 공식 결합",
            "최소 가공비(MIM) 보정 가드레일 엔진 탑재 (저가 견적 원천 차단)",
            "현장 사장님 전용 실시간 검수 슬라이더바(가공시간, 난이도 배율) 추가",
            "2열(Left: 입력 / Right: 실시간 원가 대시보드) 엔터프라이즈 UX 개편"
        ]
    },
    {
        "version": "v1.2.0",
        "date": "2026-10-22",
        "title": "비동기 분석 및 한국식 달력 도입",
        "details": [
            "AI 도면 분석 백그라운드 멀티스레딩 처리 (작업 중 화면 멈춤 해소)",
            "503 트래픽 과부하 대비 지수 백오프 자동 재시도 및 모델 폴백",
            "한국 표준 월간 납기 캘린더 그리드 뷰 구현"
        ]
    }
]

# ==========================================
# 1. 파일 경로 및 시스템 데이터베이스 관리
# ==========================================
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(DATA_DIR, "pricing_settings.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders_database.json")
USERS_FILE = os.path.join(DATA_DIR, "system_users.json")
AUTH_SECRET_KEY = "costify_secure_auth_salt_2026"

DEFAULT_USERS = {
    "admin": {"password": "admin1234!", "name": "총괄관리자", "role": "admin", "last_seen_version": ""},
    "factory1": {"password": "factory1234!", "name": "제1가공공장", "role": "user", "last_seen_version": ""},
    "sales": {"password": "sales1234!", "name": "영업팀장", "role": "user", "last_seen_version": ""}
}

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
        "AL6061 / 알루미늄": 5500,
        "SUS304 / 스테인리스": 8000,
        "SS400 / 일반 철": 2500,
        "S45C / 탄소강": 3500,
        "기타 / 미상": 5000
    },
    "machines": {
        "3축 머시닝센터(MCT)": 45000,
        "5축 머시닝센터(MCT)": 80000,
        "CNC 복합선반": 45000,
        "범용 선반 / 밀링": 30000
    },
    "surface_treatments": {
        "무처리 (가공원형)": 0,
        "샌딩 / 아노다이징 (백색)": 5000,
        "아노다이징 (흑색/유색)": 7000,
        "무전해 니켈도금": 8000,
        "열처리 (QT/고주파)": 10000
    },
    "default_setup_fee": 30000,
    "min_machining_cost": 35000,
    "default_material_loss": 20,
    "default_margin_rate": 20
}

STAGE_CONFIG = {
    "1. 견적제출": {"color": "#64748b", "name": "견적제출"},
    "2. 발주확정": {"color": "#0284c7", "name": "발주확정"},
    "3. 소재입고": {"color": "#d97706", "name": "소재입고"},
    "4. 가공진행(MCT/선반)": {"color": "#ea580c", "name": "가공진행"},
    "5. 열처리/후처리": {"color": "#9333ea", "name": "후처리"},
    "6. 치수검사/세척": {"color": "#0891b2", "name": "치수검사"},
    "7. 출하완료": {"color": "#059669", "name": "출하완료"}
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

def generate_session_token(uid):
    return hashlib.sha256(f"{uid}_{AUTH_SECRET_KEY}".encode()).hexdigest()[:16]

users_db = load_json(USERS_FILE, DEFAULT_USERS)
settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
orders_db = load_json(ORDERS_FILE, [])

# ==========================================
# 2. UI 테마 & 로그인 영구 세션 관리
# ==========================================
st.set_page_config(page_title="Costify | 정밀 절삭가공 견적 & MES", page_icon="⚙️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0b0f19; }
    
    .panel-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 14px;
    }
    .panel-title {
        color: #94a3b8;
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 12px;
        border-bottom: 1px solid #1f2937;
        padding-bottom: 6px;
    }

    .metric-container {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 8px;
    }
    .metric-label { color: #64748b; font-size: 12px; font-weight: 600; }
    .metric-val { color: #f8fafc; font-size: 22px; font-weight: 700; margin-top: 3px; }
    
    .guardrail-alert {
        background-color: #451a03;
        border: 1px solid #b45309;
        border-radius: 6px;
        padding: 10px 12px;
        color: #fde68a;
        font-size: 12px;
        line-height: 1.5;
        margin-bottom: 12px;
    }

    .profile-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        color: #e2e8f0;
    }

    /* 릴리즈 노트 알림 점 */
    .red-dot {
        height: 8px;
        width: 8px;
        background-color: #ef4444;
        border-radius: 50%;
        display: inline-block;
        margin-left: 4px;
        box-shadow: 0 0 6px #ef4444;
    }

    .cal-header {
        background-color: #0f172a;
        color: #64748b;
        padding: 8px;
        text-align: center;
        font-weight: 700;
        border: 1px solid #1f2937;
        font-size: 12px;
    }
    .cal-day-cell {
        min-height: 95px;
        background-color: #111827;
        border: 1px solid #1f2937;
        padding: 6px;
        vertical-align: top;
    }
    .cal-day-cell.other-month { background-color: #0b0f19; opacity: 0.35; }
    .cal-day-cell.today { border: 2px solid #0284c7 !important; }
    .cal-badge {
        font-size: 10px;
        padding: 2px 5px;
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

# URL 쿼리 파라미터를 통한 브라우저 새로고침 세션 유지
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

query_uid = st.query_params.get("u")
query_token = st.query_params.get("k")

if not st.session_state["auth_user"] and query_uid and query_token:
    if query_uid in users_db and query_token == generate_session_token(query_uid):
        st.session_state["auth_user"] = users_db[query_uid]
        st.session_state["auth_user_id"] = query_uid

# 미인증 상태 시 로그인 화면 렌더링 (보안 힌트 영구 삭제 완료)
if not st.session_state["auth_user"]:
    _, login_col, _ = st.columns([1, 1.2, 1])
    with login_col:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("### COSTIFY PORTAL")
        st.caption("정밀 절삭가공 표준 원가 산출 및 공정 관리 시스템")
        
        with st.form("login_form"):
            in_id = st.text_input("아이디 (ID)")
            in_pw = st.text_input("비밀번호", type="password")
            submit_login = st.form_submit_button("시스템 접속", use_container_width=True, type="primary")
            
            if submit_login:
                if in_id in users_db and users_db[in_id]["password"] == in_pw:
                    st.session_state["auth_user"] = users_db[in_id]
                    st.session_state["auth_user_id"] = in_id
                    st.query_params["u"] = in_id
                    st.query_params["k"] = generate_session_token(in_id)
                    st.rerun()
                else:
                    st.error("계정 정보가 일치하지 않습니다. 관리자에게 문의하세요.")
    st.stop()

# ==========================================
# 3. 우측 상단 헤더, 릴리즈 노트 & 세션 컨트롤
# ==========================================
current_user_id = st.session_state.get("auth_user_id")
user_last_seen = users_db.get(current_user_id, {}).get("last_seen_version", "")
has_new_update = (user_last_seen != CURRENT_SYSTEM_VERSION)

head_left, head_right = st.columns([3.2, 1.8])
with head_left:
    st.markdown("### COSTIFY <span style='font-size:14px; font-weight:400; color:#64748b;'>| 정밀 가공 견적 & MES</span>", unsafe_allow_html=True)

with head_right:
    rel_col, prof_col, btn_col = st.columns([1.6, 2.0, 1.1])
    
    with rel_col:
        # 미확인 업데이트 시 빨간 알림 점 표시
        label_text = f"업데이트 {CURRENT_SYSTEM_VERSION} ●" if has_new_update else f"업데이트 {CURRENT_SYSTEM_VERSION}"
        with st.popover(label_text, use_container_width=True):
            st.markdown(f"#### 시스템 릴리즈 노트")
            st.caption(f"현재 설치 버전: **{CURRENT_SYSTEM_VERSION}**")
            
            if has_new_update:
                if st.button("확인 완료 (알림 끄기)", type="primary", use_container_width=True):
                    users_db[current_user_id]["last_seen_version"] = CURRENT_SYSTEM_VERSION
                    save_json(USERS_FILE, users_db)
                    st.rerun()
                st.divider()

            for note in SYSTEM_RELEASE_NOTES:
                st.markdown(f"**{note['version']}** ({note['date']}) - {note['title']}")
                for d in note["details"]:
                    st.write(f"- {d}")
                st.markdown("---")

    with prof_col:
        st.markdown(f"""
        <div style="text-align: right; padding-top: 5px;">
            <span class="profile-badge">● {st.session_state['auth_user']['name']} ({st.session_state['auth_user']['role']})</span>
        </div>
        """, unsafe_allow_html=True)

    with btn_col:
        if st.button("로그아웃", use_container_width=True):
            st.query_params.clear()
            st.session_state["auth_user"] = None
            st.rerun()

def open_in_new_tab_button(file_bytes, mime_type, label="새 창에서 확인"):
    b64 = base64.b64encode(file_bytes).decode('utf-8')
    js_code = f"""
    <div style="margin: 4px 0;">
        <button onclick="openBlob()" style="
            background-color: #1e293b;
            color: #38bdf8;
            border: 1px solid #0284c7;
            padding: 7px 14px;
            border-radius: 6px;
            font-size: 12px;
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
    components.html(js_code, height=42)

# ==========================================
# 4. 백그라운드 AI 분석 스레드 관리
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
    
    prompt = """
    당신은 한국 20년 경력의 베테랑 절삭가공(MCT/CNC) 공장장입니다.
    업로드된 도면을 분석하여 다음 항목을 반드시 순수한 JSON 형식으로만 추출하세요.
    {
        "material_type": "재질 (도면 표기 규격)",
        "pure_weight_kg": 숫자 (완제품 순수 중량 kg),
        "cutting_loss_percent": 숫자 (원소재 절삭 로스율 %, 기본 20%),
        "estimated_machining_hours": 숫자 (순수 절삭 가공 소요 시간 h),
        "recommended_machine": "추천설비 (3축 머시닝센터(MCT), 5축 머시닝센터(MCT), CNC 복합선반, 범용 선반 / 밀링 중 1개)",
        "difficulty_factor": 숫자 (난이도 계수 1.0~1.8),
        "holes_count": 숫자 (가공 홀 수),
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

    task_store["error"] = f"AI 서버 일시적 지연으로 연결 실패. 다시 시도해 주세요. ({last_error_msg})"
    task_store["status"] = "error"

# 사이드바 설정
with st.sidebar:
    st.markdown("#### 시스템 설정")
    default_api_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key = st.text_input("Gemini API Key", value=default_api_key, type="password")
    selected_model = st.selectbox("AI 비전 모델", ["gemini-3.8-flash", "gemini-2.5-flash"], index=0)
    st.divider()
    st.markdown("#### 기준 단가 요약")
    st.caption(f"최소 공임 기준: {settings.get('min_machining_cost', 35000):,} 원")
    st.caption(f"원소재 로스율: +{settings.get('default_material_loss', 20)} %")
    st.caption(f"기준 마진율: {settings['default_margin_rate']} %")

# ==========================================
# 5. PDF 견적서 생성 유틸리티
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
    pdf.cell(0, 12, "가 공 견 적 서", ln=True, align="C")
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
    pdf.cell(0, 6, "[ 원가 세부 산출 명세 ]", ln=True)
    pdf.set_font(main_font, size=8)
    pdf.cell(0, 5, f"1. 원재료비 : {q.get('material_cost_total', 0):,} 원 (소재 {q.get('raw_weight', 0)}kg x {q.get('material_unit_price', 0):,}원 x {q.get('qty', 1)}개)", ln=True)
    pdf.cell(0, 5, f"2. 순수가공비 : {q.get('machining_cost_total', 0):,} 원 ({q.get('hours', 0)}h x 시급 {q.get('machine_hourly_rate', 0):,}원 x 난이도 {q.get('difficulty_factor', 1.0)} x {q.get('qty', 1)}개)", ln=True)
    if q.get('guardrail_applied'):
        pdf.cell(0, 4, f"   (※ 최소 기본공임 기준 {settings.get('min_machining_cost', 35000):,}원 자동 보정 적용)", ln=True)
    pdf.cell(0, 5, f"3. 초도 세팅비 : {q.get('setup_fee', 0):,} 원", ln=True)
    pdf.cell(0, 5, f"4. 표면/후처리비 : {q.get('surface_cost_total', 0):,} 원 ({q.get('surface', '무처리')})", ln=True)
    pdf.cell(0, 5, f"5. 일반관리비 및 마진 ({q.get('margin_rate', 20)}%): {q.get('margin_amount', 0):,} 원", ln=True)
    
    if q.get('memo'):
        pdf.ln(2)
        pdf.set_font(bold_font, size=8)
        pdf.cell(0, 5, f"[ 현장 엔지니어 비고 ]: {q.get('memo')}", ln=True)

    return bytes(pdf.output())

# ==========================================
# 6. 메인 워크스페이스
# ==========================================
tabs = st.tabs(["실시간 견적 산출", "공정흐름 관리 (MES)", "납기 캘린더", "그룹 발주 관리", "시스템 설정"])

# ------------------------------------------
# TAB 1: 실시간 견적 산출 (2열 워크스페이스)
# ------------------------------------------
with tabs[0]:
    left_col, right_col = st.columns([1.1, 0.9], gap="medium")

    with left_col:
        with st.container():
            st.markdown('<div class="panel-card"><div class="panel-title">1. 발주 기본 정보</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                client_name = st.text_input("고객사(발주처)", value="(주)한국정밀")
                order_qty = st.number_input("발주 수량 (EA)", min_value=1, value=10, step=1)
            with c2:
                client_manager = st.text_input("담당자 성함/직함", value="김철수 부장")
                due_date = st.date_input("납기 요청일", value=datetime.today() + timedelta(days=12))
            st.markdown('</div>', unsafe_allow_html=True)

        with st.container():
            st.markdown('<div class="panel-card"><div class="panel-title">2. 도면 파일 및 입력 방식</div>', unsafe_allow_html=True)
            quote_mode = st.radio("모드 선택", ["AI 비전 도면 자동 판독", "수동 직접 입력"], horizontal=True, label_visibility="collapsed")
            
            uploaded_file = None
            if quote_mode == "AI 비전 도면 자동 판독":
                col_f1, col_f2 = st.columns([2.5, 1.5])
                with col_f1:
                    uploaded_file = st.file_uploader("도면 파일 등록 (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])
                with col_f2:
                    st.write("")
                    st.write("")
                    start_ai = st.button("AI 분석 실행", type="primary", use_container_width=True)

                if uploaded_file:
                    file_mime = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"
                    open_in_new_tab_button(uploaded_file.getvalue(), file_mime, label="도면 새 창 열기")

                if start_ai and uploaded_file and api_key:
                    if st.session_state["bg_task"]["status"] != "running":
                        st.session_state["bg_task"]["status"] = "running"
                        st.session_state["bg_task"]["result"] = None
                        st.session_state["bg_task"]["error"] = None
                        t = threading.Thread(
                            target=bg_analysis_worker,
                            args=(api_key, selected_model, uploaded_file.getvalue(), file_mime, uploaded_file.name, st.session_state["bg_task"])
                        )
                        t.daemon = True
                        t.start()
                        st.rerun()
            else:
                st.session_state["manual_filename"] = st.text_input("품목명 / 도면 식별 번호", value="BRACKET-M01")
            st.markdown('</div>', unsafe_allow_html=True)

        active_analysis = st.session_state["bg_task"].get("result")
        current_fname = st.session_state["bg_task"].get("filename", "") if quote_mode == "AI 비전 도면 자동 판독" else st.session_state.get("manual_filename", "수동품목")

        ai_pure_weight = float(active_analysis.get("pure_weight_kg", 0.5)) if active_analysis else 0.5
        ai_loss_rate = float(active_analysis.get("cutting_loss_percent", settings.get("default_material_loss", 20))) if active_analysis else float(settings.get("default_material_loss", 20))
        ai_hours = float(active_analysis.get("estimated_machining_hours", 0.5)) if active_analysis else 0.5
        ai_difficulty_factor = float(active_analysis.get("difficulty_factor", 1.0)) if active_analysis else 1.0
        ai_reasoning = active_analysis.get("reasoning", "") if active_analysis else ""

        with st.container():
            st.markdown('<div class="panel-card"><div class="panel-title">3. 가공 조건 & 엔지니어링 미세 조정</div>', unsafe_allow_html=True)
            k1, k2 = st.columns(2)
            with k1:
                mat_keys = list(settings["materials"].keys())
                def_mat_idx = 0
                if active_analysis:
                    for idx, m_k in enumerate(mat_keys):
                        if any(x in active_analysis.get("material_type", "").upper() for x in m_k.split()[0].split("/")):
                            def_mat_idx = idx
                            break
                sel_material = st.selectbox("소재 재질", mat_keys, index=def_mat_idx)
                sel_surface = st.selectbox("표면 / 후처리", list(settings["surface_treatments"].keys()))

            with k2:
                mac_keys = list(settings["machines"].keys())
                def_mac_idx = 0
                if active_analysis:
                    for idx, m_k in enumerate(mac_keys):
                        if m_k.split()[0] in active_analysis.get("recommended_machine", ""):
                            def_mac_idx = idx
                            break
                sel_machine = st.selectbox("적용 가공 설비", mac_keys, index=def_mac_idx)
                adj_pure_weight = st.number_input("완제품 중량 (kg)", value=float(round(ai_pure_weight, 2)), step=0.05, format="%.2f")

            adj_hours = st.slider("개당 가공 소요시간 (h)", min_value=0.1, max_value=15.0, value=float(round(ai_hours, 2)), step=0.05)
            
            s1, s2 = st.columns(2)
            with s1:
                adj_difficulty = st.slider("가공 난이도 계수 (배율)", min_value=1.0, max_value=1.8, value=float(round(ai_difficulty_factor, 2)), step=0.05)
            with s2:
                adj_loss_rate = st.slider("소재 절삭 로스율 (%)", min_value=10, max_value=40, value=int(ai_loss_rate), step=5)

            order_memo = st.text_input("현장 비고 / 특이사항 메모", value=ai_reasoning)
            st.markdown('</div>', unsafe_allow_html=True)

    with right_col:
        raw_material_weight = adj_pure_weight * (1.0 + (adj_loss_rate / 100.0))
        mat_unit_price = settings["materials"][sel_material]
        mat_total_cost = int(raw_material_weight * mat_unit_price * order_qty)

        mac_hourly_rate = settings["machines"][sel_machine]
        calculated_machining_cost = int(adj_hours * mac_hourly_rate * adj_difficulty * order_qty)

        min_machining_threshold = settings.get("min_machining_cost", 35000)
        guardrail_triggered = (calculated_machining_cost < min_machining_threshold)
        final_machining_cost = min_machining_threshold if guardrail_triggered else calculated_machining_cost

        surf_unit_price = settings["surface_treatments"][sel_surface]
        surf_total_cost = int(surf_unit_price * order_qty)
        setup_fee = settings.get("default_setup_fee", 30000)
        margin_pct = settings.get("default_margin_rate", 20)

        subtotal_manufacturing = mat_total_cost + final_machining_cost + surf_total_cost + setup_fee
        margin_amount = int(subtotal_manufacturing * (margin_pct / 100.0))
        final_total_supply = subtotal_manufacturing + margin_amount
        final_unit_price = int(final_total_supply / order_qty)

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

        with st.container():
            st.markdown('<div class="panel-card"><div class="panel-title">견적 산출 브레이크다운</div>', unsafe_allow_html=True)
            
            m1, m2 = st.columns(2)
            with m1:
                st.markdown(f'<div class="metric-container"><div class="metric-label">개당 납품단가 (VAT 별도)</div><div class="metric-val">{final_unit_price:,} 원</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="metric-container"><div class="metric-label">총 견적 금액 ({order_qty} EA)</div><div class="metric-val" style="color:#38bdf8;">{final_total_supply:,} 원</div></div>', unsafe_allow_html=True)

            if guardrail_triggered:
                st.markdown(f"""
                <div class="guardrail-alert">
                    <b>최소 가공비(MIM) 보정 발동</b>: 계산 공임({calculated_machining_cost:,}원)이 기준선에 미달하여 기본공임 <b>{min_machining_threshold:,}원</b>으로 보정되었습니다.
                </div>
                """, unsafe_allow_html=True)

            cost_table = pd.DataFrame([
                {"원가 항목": "1. 원재료비", "산출 근거": f"개당 {round(raw_material_weight,2)}kg x {mat_unit_price:,}원 x {order_qty}EA", "금액(원)": f"{mat_total_cost:,} 원"},
                {"원가 항목": "2. 순수가공비", "산출 근거": f"{adj_hours}h x 시급 {mac_hourly_rate:,}원 x 난이도 {adj_difficulty}", "금액(원)": f"{final_machining_cost:,} 원"},
                {"원가 항목": "3. 초도세팅비", "산출 근거": "기계 원점 및 툴 세팅 공임 (1회)", "금액(원)": f"{setup_fee:,} 원"},
                {"원가 항목": "4. 표면/후처리비", "산출 근거": f"{sel_surface} x {order_qty}EA", "금액(원)": f"{surf_total_cost:,} 원"},
                {"원가 항목": "5. 관리비/마진", "산출 근거": f"제조원가 대비 {margin_pct}%", "금액(원)": f"{margin_amount:,} 원"}
            ])
            st.dataframe(cost_table, hide_index=True, use_container_width=True)

            b1, b2 = st.columns(2)
            with b1:
                st.download_button("견적서 PDF 다운로드", data=pdf_bytes, file_name=f"{quote_no}_{client_name}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            with b2:
                if st.button("시스템 데이터베이스 저장", use_container_width=True):
                    orders_db.insert(0, quote_payload)
                    save_json(ORDERS_FILE, orders_db)
                    st.success(f"견적 [{quote_no}] 등록 완료")
                    st.rerun()

            open_in_new_tab_button(pdf_bytes, "application/pdf", label="정식 견적서 새 창 열기 (인쇄)")
            st.markdown('</div>', unsafe_allow_html=True)

# ------------------------------------------
# TAB 2: 공정흐름 관리 (MES 파이프라인)
# ------------------------------------------
with tabs[1]:
    st.markdown('<div class="panel-card"><div class="panel-title">공정 상태별 필터</div>', unsafe_allow_html=True)
    if "stage_filter" not in st.session_state:
        st.session_state["stage_filter"] = "전체"

    cols = st.columns(len(PROCESS_STAGES) + 1)
    with cols[0]:
        is_active = (st.session_state["stage_filter"] == "전체")
        if st.button(f"전체보기\n({len(orders_db)})", use_container_width=True, type="primary" if is_active else "secondary"):
            st.session_state["stage_filter"] = "전체"
            st.rerun()

    for idx, stage in enumerate(PROCESS_STAGES):
        with cols[idx + 1]:
            cnt = sum(1 for o in orders_db if o.get("status") == stage)
            is_active = (st.session_state["stage_filter"] == stage)
            display_title = STAGE_CONFIG[stage].get("name", stage.split('.')[1].strip())
            if st.button(f"{display_title}\n({cnt})", use_container_width=True, type="primary" if is_active else "secondary"):
                st.session_state["stage_filter"] = stage
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    current_filter = st.session_state["stage_filter"]
    filtered_orders = orders_db if current_filter == "전체" else [o for o in orders_db if o.get("status") == current_filter]

    if not filtered_orders:
        st.info("해당 단계의 등록 작업 건이 없습니다.")
    else:
        for idx, o in enumerate(filtered_orders):
            stage_name = o.get("status", "1. 견적제출")
            header_title = f"[{stage_name}] {o.get('quote_no')} | {o.get('client_name')} : {o.get('filename')} ({o.get('qty')} EA) | 납기: {o.get('due_date')}"
            
            with st.expander(header_title, expanded=(current_filter != "전체")):
                step_idx = PROCESS_STAGES.index(stage_name) if stage_name in PROCESS_STAGES else 0
                
                step_html = "<div style='display: flex; gap: 4px; margin-bottom: 12px; overflow-x: auto;'>"
                for s_i, s_name in enumerate(PROCESS_STAGES):
                    bg = STAGE_CONFIG[s_name]['color'] if s_i <= step_idx else "#1e293b"
                    opac = "1.0" if s_i == step_idx else ("0.5" if s_i < step_idx else "0.2")
                    border = "1px solid #38bdf8" if s_i == step_idx else "1px solid #334155"
                    step_html += f"<div style='flex:1; min-width:65px; background-color:{bg}; opacity:{opac}; border:{border}; padding:6px 2px; text-align:center; border-radius:4px; font-size:11px; font-weight:700; color:#fff;'>{STAGE_CONFIG[s_name]['name']}</div>"
                step_html += "</div>"
                st.markdown(step_html, unsafe_allow_html=True)

                r1, r2, r3 = st.columns([1.5, 2.5, 1])
                with r1:
                    new_status = st.selectbox("단계 전환", PROCESS_STAGES, index=step_idx, key=f"status_{o['id']}")
                with r2:
                    new_memo = st.text_input("현장 공정 메모", value=o.get("memo", ""), key=f"memo_{o['id']}")
                with r3:
                    st.write("")
                    st.write("")
                    if st.button("저장", key=f"save_{o['id']}", use_container_width=True):
                        for real_idx, target in enumerate(orders_db):
                            if target["id"] == o["id"]:
                                orders_db[real_idx]["status"] = new_status
                                orders_db[real_idx]["memo"] = new_memo
                                break
                        save_json(ORDERS_FILE, orders_db)
                        st.success("저장 완료")
                        st.rerun()

# ------------------------------------------
# TAB 3: 납기 캘린더
# ------------------------------------------
with tabs[2]:
    cal_mode = st.radio("보기 모드", ["월간 달력 그리드", "상세 납기 리스트"], horizontal=True, label_visibility="collapsed")
    today = datetime.today().date()

    if cal_mode == "월간 달력 그리드":
        c_y, c_m, _ = st.columns([1.2, 1.2, 3])
        with c_y:
            cal_year = st.selectbox("연도", range(today.year - 1, today.year + 3), index=1)
        with c_m:
            cal_month = st.selectbox("월", range(1, 13), index=today.month - 1)

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
                matching_orders = [o for o in orders_db if o.get("due_date") == day_str]

                grid_html += f"<td class='{cell_class}'>"
                day_color = "#f87171" if day_date.weekday() == 6 else ("#60a5fa" if day_date.weekday() == 5 else "#f8fafc")
                grid_html += f"<div style='font-weight:700; font-size:12px; color:{day_color};'>{day_date.day}</div>"

                for mo in matching_orders:
                    st_name = mo.get("status", "1. 견적제출")
                    badge_color = STAGE_CONFIG.get(st_name, {}).get("color", "#0284c7")
                    is_overdue = (day_date < today and st_name != "7. 출하완료")
                    border_style = "border:1px solid #ef4444;" if is_overdue else ""
                    grid_html += f"<div class='cal-badge' style='background-color:{badge_color}; {border_style}' title='[{mo.get('client_name')}] {mo.get('filename')}'>{mo.get('client_name')[:4]} | {mo.get('filename')[:6]}</div>"

                grid_html += "</td>"
            grid_html += "</tr>"
        grid_html += "</tbody></table>"
        st.markdown(grid_html, unsafe_allow_html=True)
    else:
        if not orders_db:
            st.info("등록된 작업 건이 없습니다.")
        else:
            cal_list = []
            for o in orders_db:
                due_str = o.get("due_date", "")
                try:
                    diff = (datetime.strptime(due_str, "%Y-%m-%d").date() - today).days
                    d_day = f"{abs(diff)}일 지연" if diff < 0 else ("D-Day" if diff == 0 else f"D-{diff}")
                except Exception:
                    d_day = "-"
                cal_list.append({
                    "D-Day": d_day, "납기일": o.get("due_date"), "견적번호": o.get("quote_no"),
                    "고객사": o.get("client_name"), "품목명": o.get("filename"),
                    "수량": f"{o.get('qty', 1):,} EA", "공정상태": o.get("status")
                })
            st.dataframe(pd.DataFrame(cal_list).sort_values(by="납기일"), use_container_width=True)

# ------------------------------------------
# TAB 4: 그룹 발주 관리
# ------------------------------------------
with tabs[3]:
    st.markdown('<div class="panel-card"><div class="panel-title">다품종 수주 묶음 프로젝트 생성</div>', unsafe_allow_html=True)
    g_col1, g_col2 = st.columns([3, 1])
    with g_col1:
        group_title_input = st.text_input("새 묶음 프로젝트 명칭", placeholder="예: 반도체 라인 지그 4종 묶음")
    with g_col2:
        st.write("")
        st.write("")
        create_group_btn = st.button("선택 항목 묶음 생성", type="primary", use_container_width=True)

    selected_ids = []
    for o in orders_db:
        c_chk, c_txt = st.columns([0.4, 9.6])
        with c_chk:
            if st.checkbox("", key=f"chk_{o['id']}"):
                selected_ids.append(o["id"])
        with c_txt:
            tag = f"[{o['group_id']}] " if o.get("group_id") else ""
            st.write(f"**{tag}{o.get('quote_no')}** | {o.get('client_name')} : {o.get('filename')} ({o.get('qty')}EA) | 공급가: **{o.get('total_price',0):,}원** | 납기: {o.get('due_date')} | 상태: `{o.get('status')}`")

    if create_group_btn:
        if not group_title_input.strip() or not selected_ids:
            st.warning("프로젝트 명칭 입력 및 1개 이상의 항목을 체크하세요.")
        else:
            for o in orders_db:
                if o["id"] in selected_ids:
                    o["group_id"] = group_title_input.strip()
            save_json(ORDERS_FILE, orders_db)
            st.success("그룹화 완료")
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    groups = {}
    for o in orders_db:
        if o.get("group_id"):
            groups.setdefault(o["group_id"], []).append(o)

    for gname, items in groups.items():
        tot_price = sum(it.get("total_price", 0) for it in items)
        tot_qty = sum(it.get("qty", 1) for it in items)
        with st.expander(f"[프로젝트] {gname} (품목 {len(items)}종 | 총 {tot_qty:,} EA | 합계 {tot_price:,} 원)"):
            sub_rows = [{"견적번호": it.get("quote_no"), "도면명": it.get("filename"), "수량": f"{it.get('qty'):,} EA", "단가": f"{it.get('unit_price',0):,} 원", "합계": f"{it.get('total_price',0):,} 원", "상태": it.get("status")} for it in items]
            st.dataframe(pd.DataFrame(sub_rows), use_container_width=True)

# ------------------------------------------
# TAB 5: 시스템 설정 & 인가 계정 관리
# ------------------------------------------
with tabs[4]:
    st.markdown('<div class="panel-card"><div class="panel-title">사용자 계정 관리</div>', unsafe_allow_html=True)
    if st.session_state["auth_user"]["role"] != "admin":
        st.warning("계정 관리 기능은 총괄 관리자(admin) 전용입니다.")
    else:
        uc1, uc2 = st.columns([1.5, 2.5])
        with uc1:
            st.markdown("##### 신규 계정 등록")
            new_uid = st.text_input("아이디")
            new_upw = st.text_input("비밀번호", type="password")
            new_uname = st.text_input("담당자명/공장명")
            new_urole = st.selectbox("권한", ["user", "admin"])
            if st.button("계정 생성", type="primary"):
                if new_uid and new_upw:
                    users_db[new_uid] = {"password": new_upw, "name": new_uname, "role": new_urole, "last_seen_version": ""}
                    save_json(USERS_FILE, users_db)
                    st.success(f"계정 [{new_uid}] 등록 완료")
                    st.rerun()

        with uc2:
            st.markdown("##### 등록 계정 목록 및 관리")
            for uid, uinfo in list(users_db.items()):
                u_row1, u_row2, u_row3 = st.columns([2.5, 2, 1])
                with u_row1:
                    st.write(f"**{uid}** ({uinfo['name']})")
                with u_row2:
                    st.caption(f"권한: `{uinfo['role']}`")
                with u_row3:
                    if uid == "admin":
                        st.caption("시스템 마스터")
                    elif uid == st.session_state.get("auth_user_id"):
                        st.caption("접속 중")
                    else:
                        if st.button("삭제", key=f"del_{uid}"):
                            del users_db[uid]
                            save_json(USERS_FILE, users_db)
                            st.success(f"[{uid}] 계정이 삭제되었습니다.")
                            st.rerun()
                st.divider()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="panel-card"><div class="panel-title">데이터베이스 백업 & 복원</div>', unsafe_allow_html=True)
    bk1, bk2 = st.columns(2)
    with bk1:
        st.download_button(
            "전체 수주 데이터 백업 파일 다운로드",
            data=json.dumps(orders_db, ensure_ascii=False, indent=2),
            file_name=f"costify_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )
    with bk2:
        restore_file = st.file_uploader("백업 JSON 파일 업로드 복원", type=["json"])
        if restore_file and st.button("데이터 복원 실행", use_container_width=True):
            try:
                orders_db = json.load(restore_file)
                save_json(ORDERS_FILE, orders_db)
                st.success("데이터베이스 복원 성공")
                st.rerun()
            except Exception as e:
                st.error(f"복원 오류: {str(e)}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="panel-card"><div class="panel-title">공급사 정보 및 기준 단가 설정</div>', unsafe_allow_html=True)
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
        up_min_machine = st.number_input("최소 가공비(MIM) 보정선 (원)", value=int(settings.get("min_machining_cost", 35000)), step=5000)
        up_margin = st.number_input("기준 마진율 (%)", value=int(settings.get("default_margin_rate", 20)), step=5)

    st.markdown("---")
    st1, st2, st3 = st.columns(3)
    with st1:
        st.markdown("**소재 kg당 단가 (원)**")
        up_materials = {k: st.number_input(f"{k}", value=int(v), step=500) for k, v in settings["materials"].items()}
    with st2:
        st.markdown("**설비 시간당 공임 (원)**")
        up_machines = {k: st.number_input(f"{k}", value=int(v), step=1000) for k, v in settings["machines"].items()}
    with st3:
        st.markdown("**표면처리 개당 단가 (원)**")
        up_surfaces = {k: st.number_input(f"{k}", value=int(v), step=500) for k, v in settings["surface_treatments"].items()}

    if st.button("모든 단가 및 설정 저장", type="primary", use_container_width=True):
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
        st.success("설정이 저장되었습니다.")
    st.markdown('</div>', unsafe_allow_html=True)
