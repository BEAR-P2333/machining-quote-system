import streamlit as st

# ==========================================
# [중요] 최상단 와이드 레이아웃 강제 지정
# ==========================================
st.set_page_config(
    page_title="Costify | 정밀 절삭가공 견적 AI 시스템",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

import streamlit.components.v1 as components
from google import genai
from google.genai import types
import os
import json
import base64
import time
import math
import calendar
import hashlib
import shutil
import io
import re
import urllib.request
import pandas as pd
from datetime import datetime, timedelta

# fpdf2 안전 임포트
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

# PDF 변환 라이브러리 안전 임포트
try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except ImportError:
    HAS_PDFIUM = False

# PIL 안전 임포트
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ==========================================
# 0. 시스템 버전 및 릴리즈 노트
# ==========================================
CURRENT_SYSTEM_VERSION = "v2.5.8"

SYSTEM_RELEASE_NOTES = [
    {
        "version": "v2.5.8",
        "date": "2026-10-27",
        "title": "실제 도면 캡처 썸네일, 상세뷰 및 공정 편집 기능 탑재",
        "details": [
            "가상 SVG 템플릿 제거 및 업로드된 실제 도면(PDF/이미지) 100% 일치 썸네일 연동",
            "대시보드/캘린더 안건 클릭 시 20년차 공장장 맞춤형 견적 상세 검수 화면 전환",
            "공정흐름 관리 단계 사용자 추가/삭제/이름 변경 편집기 탑재 및 기본 아코디언 접힘 적용",
            "상단 업데이트/로그아웃 버튼 50% 컴팩트 축소 및 견적 카드-PDF 버튼 간격 밀착",
            "납기 캘린더 드래그 앤 드롭 이동 및 즉시 상세 보기 연동"
        ]
    }
]

# ==========================================
# 1. 파일 경로 및 멀티테넌트 데이터베이스 관리
# ==========================================
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_BASE_DIR = os.path.join(DATA_DIR, "companies")
os.makedirs(COMPANIES_BASE_DIR, exist_ok=True)

COMPANIES_META_FILE = os.path.join(DATA_DIR, "companies_registry.json")
USERS_FILE = os.path.join(DATA_DIR, "system_users.json")
AUTH_SECRET_KEY = "costify_multi_tenant_secret_2026"

DEFAULT_STAGE_CONFIG = {
    "1. 견적제출": {"bg": "#E9F4FF", "color": "#1667B8", "name": "견적제출"},
    "2. 발주확정": {"bg": "#BFD9F2", "color": "#176FC5", "name": "발주확정"},
    "3. 소재입고": {"bg": "#FFF3E0", "color": "#A65018", "name": "소재입고"},
    "4. 가공진행(MCT/선반)": {"bg": "#F6D3CE", "color": "#BF4333", "name": "가공진행"},
    "5. 열처리/후처리": {"bg": "#F3E8FF", "color": "#7E22CE", "name": "후처리"},
    "6. 치수검사/세척": {"bg": "#E0F2FE", "color": "#0369A1", "name": "치수검사"},
    "7. 출하완료": {"bg": "#E8F5E9", "color": "#236542", "name": "출하완료"}
}

DEFAULT_SETTINGS = {
    "company_info": {
        "company_name": "Costify 본사 마스터 공장",
        "biz_num": "123-45-67890",
        "ceo_name": "홍길동",
        "tel": "031-123-4567",
        "email": "contact@costify.ai",
        "address": "경기도 시흥시 시화벤처로 123"
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
    "process_stages": DEFAULT_STAGE_CONFIG,
    "default_setup_fee": 30000,
    "min_machining_cost": 35000,
    "default_material_loss": 20,
    "default_margin_rate": 20
}

DEFAULT_COMPANIES = {
    "master_workspace": {
        "name": "Costify 본사 마스터",
        "created_at": "2026-10-25"
    }
}

DEFAULT_USERS = {
    "admin": {
        "password": "admin1234!",
        "name": "시스템 총괄마스터",
        "role": "super_admin",
        "company_id": "master_workspace",
        "last_seen_version": ""
    }
}

DENSITY_TABLE = {
    "알루미늄 (AL6061)": 2.70,
    "스테인리스 (SUS304)": 7.93,
    "일반철/탄소강 (SS400/S45C)": 7.85,
    "황동/동 (Brass/Copper)": 8.50,
    "엔지니어링 플라스틱 (POM/MC나일론)": 1.42
}

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

def get_tenant_dir(company_id):
    p = os.path.join(COMPANIES_BASE_DIR, company_id)
    os.makedirs(p, exist_ok=True)
    return p

def load_tenant_data(company_id, filename, default_val):
    path = os.path.join(get_tenant_dir(company_id), filename)
    return load_json(path, default_val)

def save_tenant_data(company_id, filename, data):
    path = os.path.join(get_tenant_dir(company_id), filename)
    save_json(path, data)

def log_audit(company_id, user_name, action, target, details=""):
    logs = load_tenant_data(company_id, "system_audit_logs.json", [])
    logs.insert(0, {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user_name,
        "action": action,
        "target": target,
        "details": details
    })
    save_tenant_data(company_id, "system_audit_logs.json", logs[:300])

companies_db = load_json(COMPANIES_META_FILE, DEFAULT_COMPANIES)
users_db = load_json(USERS_FILE, DEFAULT_USERS)

if "master_workspace" not in companies_db:
    companies_db["master_workspace"] = {"name": "Costify 본사 마스터", "created_at": "2026-10-25"}
    save_json(COMPANIES_META_FILE, companies_db)

if "admin" in users_db:
    if users_db["admin"].get("role") != "super_admin" or users_db["admin"].get("company_id") != "master_workspace":
        users_db["admin"]["role"] = "super_admin"
        users_db["admin"]["company_id"] = "master_workspace"
        users_db["admin"]["name"] = "시스템 총괄마스터"
        save_json(USERS_FILE, users_db)

# ==========================================
# 2. UI 테마 & 상용화 브랜딩 (Streamlit 기본 툴바 및 Manage App 완전 은닉)
# ==========================================
st.markdown("""
<style>
    /* 상용 서비스용: Streamlit 워터마크, 툴바, Manage app 배지 완전 은닉 */
    #MainMenu { visibility: hidden !important; }
    header[data-testid="stHeader"] { visibility: hidden !important; height: 0% !important; }
    footer { visibility: hidden !important; height: 0% !important; }
    .viewerBadge_container__1QSob, [data-testid="manage-app-button"], .stAppDeployButton, [data-testid="stToolbar"] {
        display: none !important;
        visibility: hidden !important;
    }

    .block-container {
        padding-top: 1.8rem !important;
        padding-bottom: 2.5rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }

    :root, html, body, [data-theme="light"], [data-theme="dark"], [data-testid="stAppViewContainer"], .stApp {
        color-scheme: light !important;
        background-color: #f6f6f6 !important;
        color: #111111 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Noto Sans KR", Roboto, sans-serif !important;
    }

    /* 상단 미니멀 유틸리티 버튼 (업데이트/로그아웃 50% 축소) */
    .mini-util-btn button {
        padding: 2px 6px !important;
        font-size: 11px !important;
        height: 28px !important;
        min-height: 28px !important;
        border-radius: 4px !important;
        font-weight: 600 !important;
    }

    [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid #e0e0e0 !important;
    }
    [data-testid="stSidebar"] * {
        color: #1e293b !important;
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: #0f172a !important;
        font-weight: 700 !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] details summary p {
        color: #0f172a !important;
        font-weight: 700 !important;
        font-size: 13px !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: #f8fafc !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 6px !important;
        margin-bottom: 8px !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 16px;
        background-color: #ffffff !important;
        border-bottom: 1px solid #dcdcdc !important;
        padding: 0 12px;
        border-radius: 6px 6px 0 0;
    }
    .stTabs [data-baseweb="tab"] {
        color: #475569 !important;
        font-weight: 600 !important;
        font-size: 13.5px !important;
        padding: 10px 14px !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: #1976D2 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #1976D2 !important;
        border-bottom: 2px solid #1976D2 !important;
        font-weight: 700 !important;
    }

    .panel-card {
        background: #ffffff !important;
        border: 1px solid #dcdcdc !important;
        border-radius: 6px !important;
        padding: 16px 18px !important;
        margin-bottom: 14px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
    }
    .panel-title {
        color: #1976D2 !important;
        font-size: 14px !important;
        font-weight: 700 !important;
        margin-bottom: 12px !important;
        border-bottom: 1px solid #e6e6e6 !important;
        padding-bottom: 8px !important;
    }
    .filter-rail-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 13px;
        font-weight: 700;
        color: #111111;
        margin-bottom: 10px;
        border-bottom: 1px solid #e6e6e6;
        padding-bottom: 6px;
    }

    /* 카드와 PDF 다운로드 버튼 간격 밀착 */
    .quote-card-container {
        margin-bottom: 16px !important;
    }
    .quote-card {
        background: #ffffff;
        border: 1px solid #dcdcdc;
        border-radius: 6px 6px 0 0;
        padding: 0 0 14px 0;
        margin-bottom: 0px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        overflow: hidden;
        border-bottom: none;
    }
    .quote-card-btn-wrap {
        border: 1px solid #dcdcdc;
        border-top: 1px dashed #e2e8f0;
        border-radius: 0 0 6px 6px;
        background: #ffffff;
        padding: 8px 12px;
        margin-top: 0px !important;
    }
    .quote-card-body {
        padding: 14px 16px 0 16px;
    }
    .quote-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }
    .quote-card-title {
        font-size: 16px;
        font-weight: 700;
        color: #111111;
    }
    .quote-card-client {
        font-size: 13px;
        color: #565656;
        margin-bottom: 8px;
    }
    .quote-card-price {
        font-size: 19px;
        font-weight: 800;
        color: #1976D2;
        margin-bottom: 6px;
    }
    .quote-card-specs {
        font-size: 12px;
        color: #64748b;
        line-height: 1.5;
        border-top: 1px dashed #e6e6e6;
        padding-top: 8px;
        margin-top: 8px;
    }

    label, .stWidgetLabel p, .stWidgetLabel span {
        color: #1e293b !important;
        font-weight: 600 !important;
        font-size: 12px !important;
    }
    input, textarea {
        background-color: #ffffff !important;
        color: #111111 !important;
        border: 1px solid #cccccc !important;
        border-radius: 4px !important;
        font-size: 13px !important;
    }
    input:focus, textarea:focus {
        border-color: #1976D2 !important;
        box-shadow: 0 0 0 1px #1976D2 !important;
    }
    [data-testid="stDateInput"] div[data-baseweb="input"], [data-baseweb="select"] > div {
        background-color: #ffffff !important;
        border: 1px solid #cccccc !important;
        border-radius: 4px !important;
        color: #111111 !important;
    }

    button[kind="primary"] {
        background-color: #1976D2 !important;
        color: #ffffff !important;
        border: 1px solid #1976D2 !important;
        font-weight: 700 !important;
        border-radius: 4px !important;
    }
    button[kind="secondary"] {
        background-color: #ffffff !important;
        color: #333333 !important;
        border: 1px solid #cccccc !important;
        font-weight: 600 !important;
        border-radius: 4px !important;
    }

    .metric-container {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 12px 14px;
        margin-bottom: 10px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .metric-label { color: #64748b; font-size: 11.5px; font-weight: 600; }
    .metric-val { color: #0f172a; font-size: 20px; font-weight: 700; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# 브라우저 새로고침(F5) 세션 유지
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

query_uid = st.query_params.get("u")
query_token = st.query_params.get("k")

if not st.session_state["auth_user"] and query_uid and query_token:
    if query_uid in users_db and query_token == generate_session_token(query_uid):
        st.session_state["auth_user"] = users_db[query_uid]
        st.session_state["auth_user_id"] = query_uid

# 미로그인 상태 시 포털 로그인 화면
if not st.session_state["auth_user"]:
    _, login_col, _ = st.columns([1, 1.2, 1])
    with login_col:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center; margin-bottom:20px;">
            <div style="font-size:26px; font-weight:800; color:#1976D2; letter-spacing:0.5px;">COSTIFY PORTAL</div>
            <div style="font-size:13px; color:#565656; margin-top:4px;">정밀 절삭가공 표준 원가 산출 AI 시스템</div>
        </div>
        """, unsafe_allow_html=True)
        
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
        
        with st.popover("비밀번호 분실 안내"):
            st.caption("사내 최고 관리자 또는 Costify 본사를 통해 초기화가 지원됩니다.")
            st.write("- 본사 지원팀: contact@costify.ai")
    st.stop()

# ==========================================
# 3. 테넌트(업체 워크스페이스) 활성화
# ==========================================
current_user_id = st.session_state.get("auth_user_id", "")
logged_user = users_db.get(current_user_id, st.session_state["auth_user"])
st.session_state["auth_user"] = logged_user

is_super_admin = (
    current_user_id == "admin" or
    logged_user.get("role") in ["super_admin", "admin"]
)

if "active_company_id" not in st.session_state or not is_super_admin:
    st.session_state["active_company_id"] = logged_user.get("company_id", "master_workspace")

active_cid = st.session_state["active_company_id"]
active_c_name = companies_db.get(active_cid, {}).get("name", "지정 워크스페이스")

settings = load_tenant_data(active_cid, "pricing_settings.json", DEFAULT_SETTINGS)
orders_db = load_tenant_data(active_cid, "orders_database.json", [])
clients_db = load_tenant_data(active_cid, "clients_directory.json", [
    {"name": "(주)한국정밀", "manager": "김철수 부장", "tel": "010-1234-5678"},
    {"name": "대한메카트로닉스", "manager": "이영희 차장", "tel": "010-9876-5432"}
])

STAGE_CONFIG = settings.get("process_stages", DEFAULT_STAGE_CONFIG)
PROCESS_STAGES = list(STAGE_CONFIG.keys())

# 캘린더 이동 및 상세 보기 쿼리 파라미터 수신 처리
move_id = st.query_params.get("move_id")
to_date = st.query_params.get("to_date")
if move_id and to_date:
    for o in orders_db:
        if str(o.get("id")) == str(move_id):
            old_date = o.get("due_date")
            o["due_date"] = to_date
            log_audit(active_cid, logged_user["name"], "납기 일정 드래그 이동", f"[{o.get('quote_no')}] {o.get('filename')}", f"{old_date} ➔ {to_date}")
            break
    save_tenant_data(active_cid, "orders_database.json", orders_db)
    del st.query_params["move_id"]
    del st.query_params["to_date"]
    st.toast(f"납기일이 {to_date}로 변경되었습니다.")
    st.rerun()

view_detail_param = st.query_params.get("view_detail")
if view_detail_param:
    st.session_state["selected_quote_detail_id"] = view_detail_param
    del st.query_params["view_detail"]
    st.rerun()

# ==========================================
# 4. 상단 TopNav & 컴팩트 유틸 버튼
# ==========================================
user_last_seen = users_db.get(current_user_id, {}).get("last_seen_version", "")
has_new_update = (user_last_seen != CURRENT_SYSTEM_VERSION)

if "global_search_keyword" not in st.session_state:
    st.session_state["global_search_keyword"] = ""
if "selected_quote_detail_id" not in st.session_state:
    st.session_state["selected_quote_detail_id"] = None

st.markdown(f"""
<div style="background-color:#1976D2; height:46px; display:flex; align-items:center; padding:0 20px; border-radius:6px; margin-bottom:12px; color:#ffffff; box-shadow:0 1px 3px rgba(0,0,0,0.12);">
    <div style="font-size:18px; font-weight:800; letter-spacing:0.02em; margin-right:24px; display:flex; align-items:center; gap:8px;">
        <span>⚙️</span> COSTIFY
    </div>
    <div style="font-size:12.5px; font-weight:600; background:rgba(255,255,255,0.22); padding:3px 10px; border-radius:4px;">
        🏢 {active_c_name}
    </div>
    <div style="margin-left:auto; display:flex; align-items:center; gap:16px; font-size:12.5px;">
        <span>👤 <b>{logged_user['name']}</b></span>
    </div>
</div>
""", unsafe_allow_html=True)

u_col1, u_col2 = st.columns([2.8, 2.2])
with u_col1:
    search_input = st.text_input(
        "자유어 검색",
        value=st.session_state["global_search_keyword"],
        placeholder="🔍 자유어 검색 (견적번호, 품명, 고객사, 소재, 비고 메모 등)",
        label_visibility="collapsed"
    )
    if search_input != st.session_state["global_search_keyword"]:
        st.session_state["global_search_keyword"] = search_input
        st.rerun()

with u_col2:
    if is_super_admin:
        sw_c, rel_c, btn_c = st.columns([2.5, 0.8, 0.7])
        with sw_c:
            c_options = list(companies_db.keys())
            c_idx = c_options.index(active_cid) if active_cid in c_options else 0
            new_selected_cid = st.selectbox(
                "업체 전환",
                c_options,
                index=c_idx,
                format_func=lambda x: f"🏢 {companies_db.get(x, {}).get('name', x)}",
                label_visibility="collapsed"
            )
            if new_selected_cid != active_cid:
                st.session_state["active_company_id"] = new_selected_cid
                st.rerun()
    else:
        rel_c, btn_c = st.columns([1.1, 0.9])

    with rel_c:
        lbl = "새 소식 🔴" if has_new_update else "소식"
        st.markdown('<div class="mini-util-btn">', unsafe_allow_html=True)
        with st.popover(lbl, use_container_width=True):
            st.markdown(f"#### 시스템 릴리즈 노트 ({CURRENT_SYSTEM_VERSION})")
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
        st.markdown('</div>', unsafe_allow_html=True)

    with btn_c:
        st.markdown('<div class="mini-util-btn">', unsafe_allow_html=True)
        if st.button("로그아웃", use_container_width=True):
            st.query_params.clear()
            st.session_state["auth_user"] = None
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

def open_in_new_tab_button(file_bytes, mime_type, label="새 창에서 확인"):
    b64 = base64.b64encode(file_bytes).decode('utf-8')
    js_code = f"""
    <div style="margin: 4px 0;">
        <button onclick="openBlob()" style="
            background-color: #ffffff;
            color: #1976D2;
            border: 1px solid #1976D2;
            padding: 7px 14px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            width: 100%;
            transition: background 150ms ease-out;
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
    components.html(js_code, height=44)

def highlight_kw(text, kw):
    if not kw or not text:
        return str(text)
    pattern = re.compile(f"({re.escape(kw)})", re.IGNORECASE)
    return pattern.sub(r'<mark style="background-color:#FEF08A; color:#854D0E; padding:1px 4px; border-radius:3px; font-weight:700;">\1</mark>', str(text))

# ==========================================
# 5. 사이드바: 퀵 툴박스
# ==========================================
def get_gemini_api_key():
    try:
        if hasattr(st, "secrets"):
            if "GEMINI_API_KEY" in st.secrets: return st.secrets["GEMINI_API_KEY"]
            if "gemini_api_key" in st.secrets: return st.secrets["gemini_api_key"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "")

SECURE_GEMINI_KEY = get_gemini_api_key()

with st.sidebar:
    st.markdown(f"### 엔지니어 퀵 툴박스")
    st.caption(f"활성 공장: **{active_c_name}**")
    
    with st.expander("🚨 긴급 납기 / 지연 건", expanded=True):
        today = datetime.today().date()
        urgent_orders = []
        for o in orders_db:
            if o.get("status") != "7. 출하완료":
                try:
                    d_dt = datetime.strptime(o.get("due_date", ""), "%Y-%m-%d").date()
                    diff = (d_dt - today).days
                    if diff < 0:
                        urgent_orders.append((diff, f"⚠️ {abs(diff)}일 지연", o))
                    elif diff <= 3:
                        urgent_orders.append((diff, f"🔥 D-{diff}", o))
                except Exception:
                    pass
        
        urgent_orders.sort(key=lambda x: x[0])
        if not urgent_orders:
            st.caption("현재 납기 지연 및 임박 건이 없습니다.")
        else:
            for diff, tag, uo in urgent_orders[:5]:
                st.markdown(f"""
                <div style="background:#FFF3E0; border-left:3px solid #DD6B20; padding:6px 10px; border-radius:4px; margin-bottom:6px; font-size:11.5px;">
                    <b style="color:#A65018;">{tag}</b> | {uo.get('client_name')[:6]}<br>
                    {uo.get('filename')[:12]} ({uo.get('qty')}EA) | <span style="color:#475569;">{uo.get('status')}</span>
                </div>
                """, unsafe_allow_html=True)

    with st.expander("⚖️ 소재 중량 & 비중 계산기"):
        shape_type = st.selectbox("형상 선택", ["사각 판재 (Plate)", "원형 환봉 (Round Bar)", "원형 파이프 (Pipe)"], index=0)
        selected_mat_dens = st.selectbox("소재 종류 (비중)", list(DENSITY_TABLE.keys()), index=0)
        dens_val = DENSITY_TABLE[selected_mat_dens]
        
        calc_weight_kg = 0.0
        if shape_type == "사각 판재 (Plate)":
            p_w = st.number_input("가로 W (mm)", value=100.0, step=10.0)
            p_l = st.number_input("세로 L (mm)", value=150.0, step=10.0)
            p_t = st.number_input("두께 T (mm)", value=20.0, step=5.0)
            vol_cm3 = (p_w * p_l * p_t) / 1000.0
            calc_weight_kg = (vol_cm3 * dens_val) / 1000.0
        elif shape_type == "원형 환봉 (Round Bar)":
            r_d = st.number_input("외경 OD (mm)", value=50.0, step=5.0)
            r_l = st.number_input("길이 L (mm)", value=100.0, step=10.0)
            vol_cm3 = (math.pi * ((r_d / 2.0) ** 2) * r_l) / 1000.0
            calc_weight_kg = (vol_cm3 * dens_val) / 1000.0
        else:
            pi_od = st.number_input("외경 OD (mm)", value=60.0, step=5.0)
            pi_id = st.number_input("내경 ID (mm)", value=40.0, step=5.0)
            pi_l = st.number_input("길이 L (mm)", value=100.0, step=10.0)
            vol_cm3 = (math.pi * (((pi_od / 2.0) ** 2) - ((pi_id / 2.0) ** 2)) * pi_l) / 1000.0
            calc_weight_kg = max(0.0, (vol_cm3 * dens_val) / 1000.0)

        st.markdown(f"""
        <div style="background:#f1f5f9; padding:8px; border-radius:4px; border:1px solid #cbd5e1; text-align:center; margin:8px 0;">
            <div style="font-size:11px; color:#64748b;">계산된 순수 중량</div>
            <div style="font-size:18px; font-weight:700; color:#1976D2;">{calc_weight_kg:.3f} kg</div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("견적에 중량 즉시 반영", use_container_width=True):
            st.session_state["pure_weight_val"] = round(calc_weight_kg, 2)
            st.success(f"{calc_weight_kg:.2f} kg이 견적 중량으로 설정되었습니다.")
            st.rerun()

    with st.expander("⚙️ 절삭 조건 (RPM/피드) 계산기"):
        tool_d = st.number_input("공구 직경 D (mm)", value=10.0, step=1.0)
        cut_vc = st.number_input("절삭속도 Vc (m/min)", value=120.0, step=10.0)
        feed_fz = st.number_input("날당 이송 fz (mm/t)", value=0.08, step=0.01, format="%.3f")
        tool_z = st.number_input("공구 날 수 Z", value=4, step=1)
        cut_len = st.number_input("가공 거리 L (mm)", value=300.0, step=50.0)

        calc_rpm = int((cut_vc * 1000.0) / (math.pi * tool_d)) if tool_d > 0 else 0
        calc_feed = int(calc_rpm * feed_fz * tool_z)
        calc_time_sec = int((cut_len / calc_feed) * 60) if calc_feed > 0 else 0

        st.markdown(f"""
        <div style="background:#f1f5f9; padding:8px 10px; border-radius:4px; border:1px solid #cbd5e1; font-size:12px; margin-top:6px; line-height:1.6;">
            주축 회전수: <b style="color:#0f172a;">{calc_rpm:,} RPM</b><br>
            이송속도: <b style="color:#0f172a;">{calc_feed:,} mm/min</b><br>
            1회 가공소요: <b style="color:#1976D2;">{calc_time_sec // 60}분 {calc_time_sec % 60}초</b>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("📇 거래처 주소록 & 자동 완성"):
        client_names = [c["name"] for c in clients_db]
        if client_names:
            sel_c_name = st.selectbox("단골 거래처 선택", client_names)
            found_client = next((c for c in clients_db if c["name"] == sel_c_name), None)
            
            if found_client:
                st.caption(f"담당: {found_client['manager']} ({found_client['tel']})")
                if st.button("견적서에 즉시 반영", use_container_width=True):
                    st.session_state["client_name_val"] = found_client["name"]
                    st.session_state["client_mgr_val"] = found_client["manager"]
                    st.success(f"{found_client['name']} 정보가 입력되었습니다.")
                    st.rerun()

        st.markdown("---")
        with st.popover("➕ 새 거래처 주소 등록"):
            new_c_name = st.text_input("새 거래처 상호")
            new_c_mgr = st.text_input("담당자명/직함")
            new_c_tel = st.text_input("연락처")
            if st.button("주소록에 저장", type="primary"):
                if new_c_name:
                    clients_db.append({"name": new_c_name, "manager": new_c_mgr, "tel": new_c_tel})
                    save_tenant_data(active_cid, "clients_directory.json", clients_db)
                    st.success("거래처가 저장되었습니다.")
                    st.rerun()

# ==========================================
# 6. 초고속 Gemini 2.5 Flash 도면 분석 & 100% 실도면 캡처 썸네일 생성
# ==========================================
def generate_real_drawing_thumbnail_b64(file_bytes, mime_type):
    """업로드된 실제 도면(PDF/이미지)의 1페이지를 320x160 썸네일로 캡처하여 Base64 반환"""
    try:
        if "pdf" in mime_type.lower() and HAS_PDFIUM:
            pdf = pdfium.PdfDocument(file_bytes)
            page = pdf[0]
            bitmap = page.render(scale=1.2)
            pil_img = bitmap.to_pil()
        elif HAS_PIL:
            pil_img = Image.open(io.BytesIO(file_bytes))
            if pil_img.mode in ("RGBA", "P"):
                pil_img = pil_img.convert("RGB")
        else:
            return ""

        pil_img.thumbnail((320, 160))
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""

def analyze_drawing_gemini(api_key, file_bytes, mime_type, filename, engineer_prompt=""):
    if not api_key:
        return None, "GEMINI_API_KEY가 등록되지 않았습니다. Streamlit Secrets를 확인하세요."

    client = genai.Client(api_key=api_key.strip())
    doc_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

    prompt = f"""
    당신은 한국 20년 경력의 베테랑 절삭가공(MCT/CNC) 공장장입니다.
    업로드된 도면 파일({filename})의 표제란, 치수, 형상을 정밀 분석하여 아래 JSON 항목만 추출하세요. 마크다운 태그(```json 등)는 절대 붙이지 마세요.

    [현장 엔지니어 특이사항/지침]:
    "{engineer_prompt if engineer_prompt.strip() else '특이사항 없음 (표준 공정 적용)'}"

    JSON 출력 스키마:
    {{
        "material_type": "재질 (도면 표기 규격, 예: AL6061, SUS304, SS400, S45C 등)",
        "pure_weight_kg": 완제품 순수 중량(숫자 kg, 부피와 소재 비중으로 합리적 추산),
        "cutting_loss_percent": 원소재 절삭 로스율(숫자 %, 기본 20),
        "estimated_machining_hours": 순수 절삭 소요 시간(숫자 시간 h, 0.2~5.0 사이로 정밀 추정),
        "recommended_machine": "추천설비 (3축 머시닝센터(MCT), 5축 머시닝센터(MCT), CNC 복합선반, 범용 선반 / 밀링 중 1개)",
        "difficulty_factor": 난이도 계수(숫자 1.0~1.8),
        "holes_count": 가공 홀 수(숫자),
        "reasoning": "도면 표제란과 가공 형상에 기반한 산출 근거 1줄 요약"
    }}
    """

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[doc_part, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text), None
        except Exception as e:
            if attempt == 0:
                time.sleep(0.8)
                continue
            return None, str(e)

# ==========================================
# 7. 한글 폰트 로드 및 무결점 PDF 생성기
# ==========================================
FONT_PATH = os.path.join(DATA_DIR, "NanumGothic.ttf")
FONT_URLS = [
    "[https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Regular.ttf](https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Regular.ttf)",
    "[https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf](https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf)"
]

def ensure_korean_font():
    font_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\gulim.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        FONT_PATH
    ]
    for p in font_candidates:
        if os.path.exists(p) and os.path.getsize(p) > 10000:
            return p
            
    for url in FONT_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                content = resp.read()
                if len(content) > 100000:
                    with open(FONT_PATH, "wb") as f:
                        f.write(content)
                    return FONT_PATH
        except Exception:
            continue
    return None

def create_formal_pdf(q, company_info):
    if FPDF is None:
        return b""
    try:
        pdf = FPDF(format="A4")
        pdf.add_page()
        
        font_file = ensure_korean_font()
        has_korean = False
        if font_file:
            try:
                pdf.add_font("NanumGothic", style="", fname=font_file)
                font_name = "NanumGothic"
                has_korean = True
            except Exception:
                font_name = "Helvetica"
        else:
            font_name = "Helvetica"

        def safe_text(txt):
            if has_korean:
                return str(txt)
            return "".join([c if ord(c) < 128 else "" for c in str(txt)]) or "-"

        pdf.set_font(font_name, size=18)
        title_txt = "가 공 견 적 서" if has_korean else "MACHINING QUOTATION"
        try:
            pdf.cell(0, 12, title_txt, new_x="LMARGIN", new_y="NEXT", align="C")
        except TypeError:
            pdf.cell(0, 12, title_txt, ln=1, align="C")
        pdf.ln(3)

        pdf.set_font(font_name, size=9)
        pdf.cell(95, 6, f"Quote No: {q.get('quote_no', 'QT-NEW')}")
        try:
            pdf.cell(95, 6, f"Date: {q.get('date', '-')}", new_x="LMARGIN", new_y="NEXT", align="R")
        except TypeError:
            pdf.cell(95, 6, f"Date: {q.get('date', '-')}", ln=1, align="R")
            
        pdf.cell(95, 6, "Validity: 15 days")
        try:
            pdf.cell(95, 6, f"Due Date: {q.get('due_date', '-')}", new_x="LMARGIN", new_y="NEXT", align="R")
        except TypeError:
            pdf.cell(95, 6, f"Due Date: {q.get('due_date', '-')}", ln=1, align="R")
        pdf.ln(2)

        y_pos = pdf.get_y()
        pdf.rect(10, y_pos, 90, 30)
        pdf.set_xy(12, y_pos + 2)
        pdf.set_font(font_name, size=10)
        pdf.cell(86, 6, f"Client: {safe_text(q.get('client_name', 'Client'))}")
        pdf.set_font(font_name, size=8)
        pdf.set_xy(12, y_pos + 8)
        pdf.cell(86, 5, f"Manager: {safe_text(q.get('client_manager', 'Manager'))}")
        pdf.set_xy(12, y_pos + 14)
        pdf.cell(86, 5, f"Part Name: {safe_text(q.get('filename', 'Part'))}")
        pdf.set_xy(12, y_pos + 20)
        pdf.cell(86, 5, f"Status: {safe_text(q.get('status', 'Submitted'))}")

        c_info = company_info
        pdf.rect(105, y_pos, 95, 30)
        pdf.set_xy(107, y_pos + 2)
        pdf.set_font(font_name, size=9)
        pdf.cell(91, 5, f"Supplier: {safe_text(c_info.get('company_name','Costify'))}")
        pdf.set_font(font_name, size=8)
        pdf.set_xy(107, y_pos + 8)
        pdf.cell(91, 5, f"Biz No: {c_info.get('biz_num','')}")
        pdf.set_xy(107, y_pos + 14)
        pdf.cell(91, 5, f"Address: {safe_text(c_info.get('address',''))}")
        pdf.set_xy(107, y_pos + 20)
        pdf.cell(91, 5, f"Contact: {c_info.get('tel','')} / {c_info.get('email','')}")

        pdf.set_y(y_pos + 34)
        pdf.set_font(font_name, size=11)
        tot_msg = f"견적 공급가 총계: 일금 {q.get('total_price', 0):,} 원정 (VAT 별도)" if has_korean else f"Total Supply Price: KRW {q.get('total_price', 0):,} (VAT Excluded)"
        try:
            pdf.cell(0, 9, tot_msg, border=1, new_x="LMARGIN", new_y="NEXT", align="C")
        except TypeError:
            pdf.cell(0, 9, tot_msg, border=1, ln=1, align="C")
        pdf.ln(3)

        pdf.set_font(font_name, size=8)
        pdf.cell(38, 7, "Part Spec" if not has_korean else "품명 및 사양", border=1, align="C")
        pdf.cell(16, 7, "Qty" if not has_korean else "수량", border=1, align="C")
        pdf.cell(34, 7, "Material" if not has_korean else "재질 / 총중량", border=1, align="C")
        pdf.cell(36, 7, "Machine" if not has_korean else "적용설비 / 후처리", border=1, align="C")
        pdf.cell(32, 7, "Unit Price" if not has_korean else "개당 단가", border=1, align="C")
        pdf.cell(34, 7, "Total" if not has_korean else "합계 공급가", border=1, align="C")
        pdf.ln()

        pdf.cell(38, 7, safe_text(str(q.get('filename', 'Part'))[:16]), border=1, align="C")
        pdf.cell(16, 7, f"{q.get('qty', 1):,} EA", border=1, align="C")
        pdf.cell(34, 7, safe_text(f"{str(q.get('material','')).split('/')[0]} ({q.get('raw_weight',0)}kg)"), border=1, align="C")
        pdf.cell(36, 7, safe_text(f"{str(q.get('machine_type','')).split()[0]} / {str(q.get('surface','')).split()[0]}"), border=1, align="C")
        pdf.cell(32, 7, f"{q.get('unit_price', 0):,} KRW", border=1, align="R")
        pdf.cell(34, 7, f"{q.get('total_price', 0):,} KRW", border=1, align="R")
        pdf.ln(10)

        pdf.set_font(font_name, size=9)
        breakdown_title = "[ 원가 세부 산출 명세 ]" if has_korean else "[ Cost Calculation Details ]"
        try:
            pdf.cell(0, 6, breakdown_title, new_x="LMARGIN", new_y="NEXT")
        except TypeError:
            pdf.cell(0, 6, breakdown_title, ln=1)

        pdf.set_font(font_name, size=8)
        if has_korean:
            cost_lines = [
                f"1. 원재료비 : {q.get('material_cost_total', 0):,} 원 (소재 {q.get('raw_weight', 0)}kg x {q.get('material_unit_price', 0):,}원 x {q.get('qty', 1)}개)",
                f"2. 순수가공비 : {q.get('machining_cost_total', 0):,} 원 ({q.get('hours', 0)}h x 시급 {q.get('machine_hourly_rate', 0):,}원 x 난이도 {q.get('difficulty_factor', 1.0)} x {q.get('qty', 1)}개)",
                f"3. 초도 세팅비 : {q.get('setup_fee', 0):,} 원",
                f"4. 표면/후처리비 : {q.get('surface_cost_total', 0):,} 원 ({q.get('surface', '무처리')})",
                f"5. 일반관리비 및 마진 ({q.get('margin_rate', 20)}%): {q.get('margin_amount', 0):,} 원"
            ]
        else:
            cost_lines = [
                f"1. Raw Material Cost : KRW {q.get('material_cost_total', 0):,}",
                f"2. Pure Machining Cost : KRW {q.get('machining_cost_total', 0):,}",
                f"3. Setup Cost : KRW {q.get('setup_fee', 0):,}",
                f"4. Surface Treatment : KRW {q.get('surface_cost_total', 0):,}",
                f"5. Margin & Overhead : KRW {q.get('margin_amount', 0):,}"
            ]

        for cl in cost_lines:
            try:
                pdf.cell(0, 5, cl, new_x="LMARGIN", new_y="NEXT")
            except TypeError:
                pdf.cell(0, 5, cl, ln=1)

        try:
            return bytes(pdf.output())
        except TypeError:
            return pdf.output(dest='S').encode('latin1')
    except Exception:
        return b""

# ==========================================
# 8. 20년차 베테랑 공장장 현장 견적 상세 검수 화면
# ==========================================
def render_veteran_detail_view(quote_id):
    order = next((o for o in orders_db if str(o.get("id")) == str(quote_id)), None)
    if not order:
        st.error("해당 견적 건을 찾을 수 없습니다.")
        if st.button("← 목록으로 돌아가기"):
            st.session_state["selected_quote_detail_id"] = None
            st.rerun()
        return

    today_date = datetime.today().date()
    try:
        d_dt = datetime.strptime(order.get("due_date", ""), "%Y-%m-%d").date()
        diff = (d_dt - today_date).days
        d_day_tag = f"⚠️ {abs(diff)}일 지연" if diff < 0 else (f"🔥 D-{diff}" if diff <= 3 else f"D-{diff}")
    except Exception:
        d_day_tag = "D-Day"

    st_name = order.get("status", "1. 견적제출")
    conf = STAGE_CONFIG.get(st_name, {"bg": "#E9F4FF", "color": "#1667B8", "name": st_name})

    top_c1, top_c2 = st.columns([1.5, 4.5])
    with top_c1:
        if st.button("← 견적 대시보드로 복귀", use_container_width=True):
            st.session_state["selected_quote_detail_id"] = None
            st.rerun()
    with top_c2:
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px; margin-top:2px;">
            <span style="font-size:20px; font-weight:800; color:#111111;">[{order.get('quote_no')}] {order.get('filename')}</span>
            <span style="background:{conf['bg']}; color:{conf['color']}; padding:4px 10px; border-radius:4px; font-weight:700; font-size:12px;">{conf['name']}</span>
            <span style="background:#FFF3E0; color:#DD6B20; padding:4px 10px; border-radius:4px; font-weight:700; font-size:12px;">{d_day_tag}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    det_l, det_r = st.columns([1.2, 1.0], gap="large")

    with det_l:
        st.markdown('<div class="panel-card"><div class="panel-title">1. 공장장 현장 가공 지시서 (Shop Traveler)</div>', unsafe_allow_html=True)
        
        # 100% 실제 도면 캡처 이미지 표시
        if order.get("thumbnail_b64"):
            st.markdown(f"""
            <div style="width:100%; height:240px; background:#ffffff; border:1px solid #cbd5e1; border-radius:4px; margin-bottom:14px; display:flex; align-items:center; justify-content:center; overflow:hidden;">
                <img src="data:image/jpeg;base64,{order['thumbnail_b64']}" style="max-width:100%; max-height:100%; object-fit:contain;"/>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background:#f1f5f9; padding:20px; border-radius:4px; text-align:center; color:#64748b; font-size:13px; margin-bottom:14px;">
                📄 등록된 도면 식별자: <b>{order.get('filename')}</b>
            </div>
            """, unsafe_allow_html=True)

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.metric("가공 설비", str(order.get("machine_type", "")).split()[0])
            st.metric("소재 규격", str(order.get("material", "")).split("/")[0])
        with sc2:
            st.metric("완제품 중량", f"{order.get('pure_weight', 0)} kg")
            st.metric("원소재 투입중량", f"{order.get('raw_weight', 0)} kg", delta=f"+{order.get('loss_rate', 20)}% 로스")
        with sc3:
            st.metric("순수 가공시간", f"{order.get('hours', 0)} h")
            st.metric("난이도 계수", f"x {order.get('difficulty_factor', 1.0)}")

        st.markdown("##### 현장 가공 특이사항 및 AI 분석 근거")
        st.info(order.get("memo") or "현장 특이사항 없음 (표준 공정 준수)")

        new_field_memo = st.text_input("현장 지시 메모 수정", value=order.get("memo", ""))
        if st.button("현장 지시 메모 즉시 저장", use_container_width=True):
            order["memo"] = new_field_memo
            save_tenant_data(active_cid, "orders_database.json", orders_db)
            log_audit(active_cid, logged_user["name"], "현장 지시 메모 수정", f"[{order.get('quote_no')}] {order.get('filename')}", new_field_memo)
            st.success("메모가 저장되었습니다.")
            st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    with det_r:
        st.markdown('<div class="panel-card"><div class="panel-title">2. 원가 마진 분석 및 공정/발행 관리</div>', unsafe_allow_html=True)
        
        pr1, pr2 = st.columns(2)
        with pr1:
            st.markdown(f'<div class="metric-container"><div class="metric-label">개당 납품단가</div><div class="metric-val">{order.get("unit_price", 0):,} 원</div></div>', unsafe_allow_html=True)
        with pr2:
            st.markdown(f'<div class="metric-container"><div class="metric-label">총 견적 금액 ({order.get("qty", 1)} EA)</div><div class="metric-val" style="color:#1976D2;">{order.get("total_price", 0):,} 원</div></div>', unsafe_allow_html=True)

        st.markdown("##### 원가 세부 브레이크다운")
        cost_rows = [
            ("1. 원재료비", f"{order.get('material_cost_total', 0):,} 원"),
            ("2. 순수가공비", f"{order.get('machining_cost_total', 0):,} 원"),
            ("3. 초도 세팅비", f"{order.get('setup_fee', 30000):,} 원"),
            ("4. 후처리비", f"{order.get('surface_cost_total', 0):,} 원"),
            ("5. 관리비/마진", f"{order.get('margin_amount', 0):,} 원 ({order.get('margin_rate', 20)}%)")
        ]
        html_t = "".join([f"<tr style='border-bottom:1px solid #e2e8f0;'><td style='padding:8px 6px;'>{k}</td><td style='padding:8px 6px; text-align:right; font-weight:700; color:#1976D2;'>{v}</td></tr>" for k, v in cost_rows])
        st.markdown(f"<table style='width:100%; border-collapse:collapse; font-size:13px; margin-bottom:14px;'>{html_t}</table>", unsafe_allow_html=True)

        st.markdown("##### 공정 진행 상태 원클릭 변경")
        cur_step_idx = PROCESS_STAGES.index(st_name) if st_name in PROCESS_STAGES else 0
        new_det_status = st.selectbox("진행 단계 변경", PROCESS_STAGES, index=cur_step_idx)
        if st.button("공정 상태 변경 저장", use_container_width=True):
            order["status"] = new_det_status
            save_tenant_data(active_cid, "orders_database.json", orders_db)
            log_audit(active_cid, logged_user["name"], "공정 상태 변경", f"[{order.get('quote_no')}] {order.get('filename')}", f"{st_name} ➔ {new_det_status}")
            st.success("공정 상태가 변경되었습니다.")
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        pdf_bytes = create_formal_pdf(order, settings["company_info"])
        if pdf_bytes:
            st.download_button(
                f"📄 정식 견적서 PDF 다운로드",
                data=pdf_bytes,
                file_name=f"{order.get('quote_no')}_{order.get('filename')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
            open_in_new_tab_button(pdf_bytes, "application/pdf", label="정식 견적서 새 창 인쇄")
        st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 9. 메인 워크스페이스 분기
# ==========================================
if st.session_state["selected_quote_detail_id"] is not None:
    render_veteran_detail_view(st.session_state["selected_quote_detail_id"])
else:
    tabs = st.tabs(["견적 대시보드 (목록)", "신규 견적 산출", "가공 공정 관리", "납기 캘린더", "시스템 설정"])

    # ------------------------------------------
    # TAB 1: 견적 대시보드 (컴팩트 필터 레일 & 25건 페이징)
    # ------------------------------------------
    with tabs[0]:
        if "filter_urgent_only" not in st.session_state:
            st.session_state["filter_urgent_only"] = False
        if "current_page_idx" not in st.session_state:
            st.session_state["current_page_idx"] = 1

        # 필터 레일 폭을 절반(0.65 : 3.35)으로 대폭 축소
        rail_col, main_col = st.columns([0.65, 3.35], gap="medium")

        with rail_col:
            st.markdown("""
            <div class="filter-rail-header">
                <span>⚙️ 견적 필터</span>
            </div>
            """, unsafe_allow_html=True)

            if st.button("모두 지우기", use_container_width=True):
                st.session_state["global_search_keyword"] = ""
                st.session_state["f_client"] = "전체"
                st.session_state["f_material"] = "전체"
                st.session_state["f_machine"] = "전체"
                st.session_state["f_stage"] = "전체"
                st.session_state["f_sort"] = "최신 등록순"
                st.session_state["filter_urgent_only"] = False
                st.session_state["current_page_idx"] = 1
                st.rerun()

            all_clients = ["전체"] + sorted(list({o.get("client_name") for o in orders_db if o.get("client_name")}))
            f_client = st.selectbox("고객사", all_clients, key="f_client")

            all_materials = ["전체"] + list(settings["materials"].keys())
            f_material = st.selectbox("소재 재질", all_materials, key="f_material")

            all_machines = ["전체"] + list(settings["machines"].keys())
            f_machine = st.selectbox("가공 설비", all_machines, key="f_machine")

            all_stages = ["전체"] + PROCESS_STAGES
            f_stage = st.selectbox("공정 상태", all_stages, key="f_stage")

            f_sort = st.selectbox(
                "정렬 기준",
                ["최신순", "과거순", "금액높은순", "납기순"],
                key="f_sort"
            )

        with main_col:
            filtered_orders = orders_db.copy()

            kw = st.session_state["global_search_keyword"].strip().lower()
            if kw:
                filtered_orders = [
                    o for o in filtered_orders
                    if kw in str(o.get("quote_no", "")).lower()
                    or kw in str(o.get("filename", "")).lower()
                    or kw in str(o.get("client_name", "")).lower()
                    or kw in str(o.get("material", "")).lower()
                    or kw in str(o.get("machine_type", "")).lower()
                    or kw in str(o.get("memo", "")).lower()
                ]

            if f_client != "전체":
                filtered_orders = [o for o in filtered_orders if o.get("client_name") == f_client]
            if f_material != "전체":
                filtered_orders = [o for o in filtered_orders if o.get("material") == f_material]
            if f_machine != "전체":
                filtered_orders = [o for o in filtered_orders if o.get("machine_type") == f_machine]
            if f_stage != "전체":
                filtered_orders = [o for o in filtered_orders if o.get("status") == f_stage]

            today_date = datetime.today().date()
            if st.session_state["filter_urgent_only"]:
                filtered_orders = [
                    o for o in filtered_orders
                    if o.get("status") != "7. 출하완료" and o.get("due_date") and (datetime.strptime(o.get("due_date"), "%Y-%m-%d").date() - today_date).days <= 3
                ]

            if f_sort == "최신순":
                filtered_orders.sort(key=lambda x: str(x.get("id", "")), reverse=True)
            elif f_sort == "과거순":
                filtered_orders.sort(key=lambda x: str(x.get("id", "")))
            elif f_sort == "금액높은순":
                filtered_orders.sort(key=lambda x: x.get("total_price", 0), reverse=True)
            elif f_sort == "납기순":
                filtered_orders.sort(key=lambda x: str(x.get("due_date", "9999-99-99")))

            # 25건 페이징(Pagination) 연산
            PAGE_SIZE = 25
            total_items = len(filtered_orders)
            total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
            
            if st.session_state["current_page_idx"] > total_pages:
                st.session_state["current_page_idx"] = total_pages
            current_page = st.session_state["current_page_idx"]

            start_idx = (current_page - 1) * PAGE_SIZE
            end_idx = min(start_idx + PAGE_SIZE, total_items)
            paged_orders = filtered_orders[start_idx:end_idx]

            h_left, h_right = st.columns([3, 1.5])
            with h_left:
                st.markdown(f"#### 견적 관리 <span style='font-size:13.5px; font-weight:400; color:#565656;'>(전체 {total_items}건 중 {start_idx+1 if total_items>0 else 0}~{end_idx}건 | {current_page}/{total_pages} 페이지)</span>", unsafe_allow_html=True)
            with h_right:
                view_mode = st.radio("보기 모드", ["카드형 (미리보기)", "목록형 (테이블)"], horizontal=True, label_visibility="collapsed", key="v_toggle")

            tot_sum = sum(o.get("total_price", 0) for o in filtered_orders)
            tot_qty = sum(o.get("qty", 1) for o in filtered_orders)
            
            urgent_late_count = 0
            has_strictly_overdue = False
            for o in orders_db:
                if o.get("status") != "7. 출하완료" and o.get("due_date"):
                    try:
                        d_dt = datetime.strptime(o.get("due_date"), "%Y-%m-%d").date()
                        diff = (d_dt - today_date).days
                        if diff < 0:
                            urgent_late_count += 1
                            has_strictly_overdue = True
                        elif diff <= 3:
                            urgent_late_count += 1
                    except Exception:
                        pass

            m1, m2, m3 = st.columns(3)
            with m1:
                st.markdown(f'<div class="metric-container"><div class="metric-label">조회 견적 총액 (공급가)</div><div class="metric-val" style="color:#1976D2;">{tot_sum:,} 원</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="metric-container"><div class="metric-label">총 발주 물량 (수량)</div><div class="metric-val">{tot_qty:,} EA</div></div>', unsafe_allow_html=True)
            with m3:
                color_late = "#DA4D3A" if has_strictly_overdue else ("#DD6B20" if urgent_late_count > 0 else "#236542")
                st.markdown(f'<div class="metric-container"><div class="metric-label">납기 지연 / 위험 건수 (D-3 이내)</div><div class="metric-val" style="color:{color_late};">{urgent_late_count} 건</div></div>', unsafe_allow_html=True)
                if urgent_late_count > 0 and not st.session_state["filter_urgent_only"]:
                    if st.button(f"🚨 위험/지연 {urgent_late_count}건 바로 모아보기", use_container_width=True):
                        st.session_state["filter_urgent_only"] = True
                        st.session_state["current_page_idx"] = 1
                        st.rerun()

            if st.session_state["filter_urgent_only"]:
                st.info("🚨 현재 **납기 지연 및 임박(D-3) 건만 집중 필터링**되어 표시 중입니다.")
                if st.button("✕ 집중 모드 해제 (전체 견적 보기)"):
                    st.session_state["filter_urgent_only"] = False
                    st.session_state["current_page_idx"] = 1
                    st.rerun()

            if not paged_orders:
                st.info("검색 및 필터 조건에 일치하는 등록 견적이 없습니다.")
            else:
                if view_mode == "카드형 (미리보기)":
                    card_cols = st.columns(2)
                    for idx, o in enumerate(paged_orders):
                        c_target = card_cols[idx % 2]
                        st_name = o.get("status", "1. 견적제출")
                        conf = STAGE_CONFIG.get(st_name, {"bg": "#E9F4FF", "color": "#1667B8", "name": st_name})
                        
                        with c_target:
                            # 100% 실제 도면 캡처 썸네일 노출
                            if o.get("thumbnail_b64"):
                                thumb_html = f'<div style="width:100%; height:140px; background:#f8fafc; border-bottom:1px solid #e2e8f0; display:flex; align-items:center; justify-content:center; overflow:hidden;"><img src="data:image/jpeg;base64,{o["thumbnail_b64"]}" style="width:100%; height:100%; object-fit:contain;"/></div>'
                            else:
                                thumb_html = '<div style="width:100%; height:90px; background:#f0f7ff; border-bottom:1px solid #e2e8f0; display:flex; align-items:center; justify-content:center; color:#1976D2; font-size:12px; font-weight:700;">📐 CAD 도면 원본 연결됨</div>'

                            # 마크다운 들여쓰기 변환 방지 (단일 문자열 처리)
                            card_html = (
                                f'<div class="quote-card-container">'
                                f'<div class="quote-card">'
                                f'{thumb_html}'
                                f'<div class="quote-card-body">'
                                f'<div class="quote-card-header">'
                                f'<span class="quote-card-title">{highlight_kw(o.get("filename"), kw)}</span>'
                                f'<span style="background:{conf["bg"]}; color:{conf["color"]}; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:700;">{conf["name"]}</span>'
                                f'</div>'
                                f'<div class="quote-card-client">🏢 {highlight_kw(o.get("client_name"), kw)} (견적번호: <b>{highlight_kw(o.get("quote_no"), kw)}</b>)</div>'
                                f'<div class="quote-card-price">{o.get("total_price", 0):,} 원 <span style="font-size:13px; font-weight:400; color:#565656;">(개당 {o.get("unit_price", 0):,}원 x {o.get("qty", 1):,}EA)</span></div>'
                                f'<div class="quote-card-specs">'
                                f'⚙️ <b>설비</b>: {highlight_kw(str(o.get("machine_type","")).split()[0], kw)} | <b>재질</b>: {highlight_kw(str(o.get("material","")).split("/")[0], kw)} ({o.get("raw_weight",0)}kg)<br>'
                                f'📅 <b>납기일</b>: {o.get("due_date", "-")} | <b>시간</b>: {o.get("hours",0)}h<br>'
                                f'📝 <b>비고</b>: {highlight_kw(o.get("memo", "특이사항 없음"), kw)}'
                                f'</div></div></div>'
                            )
                            st.markdown(card_html, unsafe_allow_html=True)
                            
                            # 카드에 딱 밀착된 푸터 액션 바 (상세 검수 + PDF 다운로드)
                            st.markdown('<div class="quote-card-btn-wrap">', unsafe_allow_html=True)
                            b_c1, b_c2 = st.columns(2)
                            with b_c1:
                                if st.button(f"🔍 현장 상세 검수", key=f"det_{o['id']}_{idx}", use_container_width=True):
                                    st.session_state["selected_quote_detail_id"] = o["id"]
                                    st.rerun()
                            with b_c2:
                                pdf_d = create_formal_pdf(o, settings["company_info"])
                                if pdf_d:
                                    st.download_button(
                                        f"📄 PDF 견적서",
                                        data=pdf_d,
                                        file_name=f"{o.get('quote_no')}_{o.get('filename')}.pdf",
                                        mime="application/pdf",
                                        key=f"card_pdf_{o['id']}_{idx}",
                                        use_container_width=True
                                    )
                                else:
                                    st.button("PDF 준비 중...", disabled=True, key=f"dis_{o['id']}_{idx}", use_container_width=True)
                            st.markdown('</div></div>', unsafe_allow_html=True)
                else:
                    table_rows = []
                    for o in paged_orders:
                        table_rows.append({
                            "견적번호": o.get("quote_no"),
                            "품명/도면": o.get("filename"),
                            "고객사": o.get("client_name"),
                            "상태": o.get("status"),
                            "수량": f"{o.get('qty', 1):,} EA",
                            "개당단가": f"{o.get('unit_price', 0):,} 원",
                            "총 견적가": f"{o.get('total_price', 0):,} 원",
                            "적용소재": str(o.get("material", "")).split("/")[0],
                            "가공설비": str(o.get("machine_type", "")).split()[0],
                            "납기일": o.get("due_date", "-")
                        })
                    st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)

                # 하단 25건 단위 페이징 컨트롤러
                if total_pages > 1:
                    st.markdown("<br>", unsafe_allow_html=True)
                    p_c1, p_c2, p_c3 = st.columns([1, 2, 1])
                    with p_c1:
                        if st.button("◀ 이전 페이지", disabled=(current_page == 1), use_container_width=True):
                            st.session_state["current_page_idx"] = max(1, current_page - 1)
                            st.rerun()
                    with p_c2:
                        st.markdown(f"<div style='text-align:center; padding-top:6px; font-weight:700; color:#1976D2;'>{current_page} / {total_pages} 페이지</div>", unsafe_allow_html=True)
                    with p_c3:
                        if st.button("다음 페이지 ▶", disabled=(current_page == total_pages), use_container_width=True):
                            st.session_state["current_page_idx"] = min(total_pages, current_page + 1)
                            st.rerun()

    # ------------------------------------------
    # TAB 2: 신규 견적 산출 (Google Gemini 2.5 Flash 엔진)
    # ------------------------------------------
    with tabs[1]:
        if "client_name_val" not in st.session_state: st.session_state["client_name_val"] = "(주)한국정밀"
        if "client_mgr_val" not in st.session_state: st.session_state["client_mgr_val"] = "김철수 부장"
        if "custom_part_name" not in st.session_state: st.session_state["custom_part_name"] = "BRACKET-M01"
        if "pure_weight_val" not in st.session_state: st.session_state["pure_weight_val"] = 0.50
        if "hours_val" not in st.session_state: st.session_state["hours_val"] = 0.50
        if "difficulty_val" not in st.session_state: st.session_state["difficulty_val"] = 1.00
        if "loss_rate_val" not in st.session_state: st.session_state["loss_rate_val"] = int(settings.get("default_material_loss", 20))
        if "memo_val" not in st.session_state: st.session_state["memo_val"] = ""
        if "last_uploaded_thumb" not in st.session_state: st.session_state["last_uploaded_thumb"] = ""
        if "ai_analysis_done" not in st.session_state: st.session_state["ai_analysis_done"] = False

        left_col, right_col = st.columns([1.2, 1.0], gap="large")

        with left_col:
            with st.container():
                st.markdown('<div class="panel-card"><div class="panel-title">1. 발주 기본 정보</div>', unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                with c1:
                    client_name = st.text_input("고객사(발주처)", value=st.session_state["client_name_val"])
                    order_qty = st.number_input("발주 수량 (EA)", min_value=1, value=10, step=1)
                with c2:
                    client_manager = st.text_input("담당자 성함/직함", value=st.session_state["client_mgr_val"])
                    due_date = st.date_input("납기 요청일", value=datetime.today() + timedelta(days=12))
                st.markdown('</div>', unsafe_allow_html=True)

            with st.container():
                st.markdown('<div class="panel-card"><div class="panel-title">2. 도면 파일 및 가공 지침 (프롬프트)</div>', unsafe_allow_html=True)
                quote_mode = st.radio("모드 선택", ["AI 비전 도면 자동 판독", "수동 직접 입력"], horizontal=True, label_visibility="collapsed")
                
                uploaded_file = None
                if quote_mode == "AI 비전 도면 자동 판독":
                    uploaded_file = st.file_uploader(
                        "도면 파일 등록 (PDF, PNG, JPG)",
                        type=["pdf", "png", "jpg", "jpeg"]
                    )

                    engineer_prompt = st.text_area(
                        "현장 가공 특이사항 / AI 프롬프트 지침 (선택)",
                        placeholder="예: 공차 ±0.01 엄수 요망, 와이어 방전 외주 제외 3축 MCT 순수가공 등",
                        height=65
                    )

                    col_b1, col_b2 = st.columns([2.2, 1.8])
                    with col_b1:
                        if uploaded_file:
                            file_mime = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"
                            open_in_new_tab_button(uploaded_file.getvalue(), file_mime, label="도면 새 창 열기")
                    with col_b2:
                        start_ai = st.button("⚡ AI 분석 실행 (Gemini Flash)", type="primary", use_container_width=True)

                    if start_ai:
                        if not uploaded_file:
                            st.warning("⚠️ 먼저 도면 파일을 업로드해 주세요.")
                        elif not SECURE_GEMINI_KEY:
                            st.error("❌ GEMINI_API_KEY가 감지되지 않았습니다. Streamlit Secrets를 확인하세요.")
                        else:
                            clean_name = os.path.splitext(uploaded_file.name)[0]
                            st.session_state["custom_part_name"] = clean_name
                            
                            with st.spinner("⚡ Gemini 2.5 Flash 도면 정밀 분석 중... (약 2초)"):
                                file_mime = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"
                                file_bytes = uploaded_file.getvalue()
                                
                                # 실제 업로드된 도면 1페이지 썸네일 캡처
                                thumb_b64 = generate_real_drawing_thumbnail_b64(file_bytes, file_mime)
                                st.session_state["last_uploaded_thumb"] = thumb_b64

                                parsed_res, err = analyze_drawing_gemini(
                                    SECURE_GEMINI_KEY, file_bytes, file_mime, uploaded_file.name, engineer_prompt
                                )
                                if err:
                                    st.error(f"❌ 분석 오류: {err}")
                                elif parsed_res:
                                    st.session_state["pure_weight_val"] = float(parsed_res.get("pure_weight_kg", 0.50))
                                    st.session_state["hours_val"] = float(parsed_res.get("estimated_machining_hours", 0.50))
                                    st.session_state["difficulty_val"] = float(parsed_res.get("difficulty_factor", 1.00))
                                    st.session_state["loss_rate_val"] = int(parsed_res.get("cutting_loss_percent", 20))
                                    st.session_state["memo_val"] = parsed_res.get("reasoning", "")
                                    st.session_state["ai_suggested_mat"] = parsed_res.get("material_type", "")
                                    st.session_state["ai_suggested_mac"] = parsed_res.get("recommended_machine", "")
                                    st.session_state["ai_analysis_done"] = True
                                    log_audit(active_cid, logged_user["name"], "AI 도면 자동 판독", f"[{clean_name}]", f"{st.session_state['hours_val']}h / {st.session_state['pure_weight_val']}kg")
                                    st.balloons()
                                    st.success(f"✅ [{clean_name}] 분석 성공! 우측에 견적이 자동 계산되었습니다.")
                                    st.rerun()
                else:
                    st.session_state["custom_part_name"] = st.text_input("품명 / 도면 식별 번호", value=st.session_state["custom_part_name"])
                st.markdown('</div>', unsafe_allow_html=True)

            with st.container():
                st.markdown('<div class="panel-card"><div class="panel-title">3. 품명 지정 & 엔지니어링 검수</div>', unsafe_allow_html=True)
                
                custom_name_input = st.text_input("품명 / 도면 식별명 (견적서 정식 표기)", value=st.session_state["custom_part_name"])
                st.session_state["custom_part_name"] = custom_name_input

                # 과거 산출 견적 중복 감지 경고
                dups = [o for o in orders_db if o.get("filename", "").strip().lower() == custom_name_input.strip().lower()]
                if dups:
                    dup_item = dups[0]
                    st.markdown(f"""
                    <div style="background:#FFF3E0; border:1.5px solid #DD6B20; border-radius:4px; padding:10px 14px; margin-bottom:12px; font-size:12.5px; color:#A65018;">
                        <b>⚠️ 과거 산출 견적 중복 감지</b><br>
                        과거에 동일한 품명으로 산출된 견적이 존재합니다: <b>[{dup_item.get('quote_no')}] {dup_item.get('filename')}</b><br>
                        (고객사: {dup_item.get('client_name')}, 공급가: {dup_item.get('total_price', 0):,}원, 등록일: {dup_item.get('date')})<br>
                        동일 건이 아닌 경우 품명 뒤에 <b>'_REV2'</b> 등을 붙여 식별할 수 있습니다.
                    </div>
                    """, unsafe_allow_html=True)

                k1, k2 = st.columns(2)
                mat_keys = list(settings["materials"].keys())
                def_mat_idx = 0
                sugg_mat = st.session_state.get("ai_suggested_mat", "").upper()
                if sugg_mat:
                    for idx, m_k in enumerate(mat_keys):
                        if any(x in sugg_mat for x in m_k.split()[0].split("/")):
                            def_mat_idx = idx
                            break

                mac_keys = list(settings["machines"].keys())
                def_mac_idx = 0
                sugg_mac = st.session_state.get("ai_suggested_mac", "")
                if sugg_mac:
                    for idx, m_k in enumerate(mac_keys):
                        if m_k.split()[0] in sugg_mac:
                            def_mac_idx = idx
                            break

                with k1:
                    sel_material = st.selectbox("소재 재질", mat_keys, index=def_mat_idx)
                    sel_surface = st.selectbox("표면 / 후처리", list(settings["surface_treatments"].keys()))

                with k2:
                    sel_machine = st.selectbox("적용 가공 설비", mac_keys, index=def_mac_idx)
                    adj_pure_weight = st.number_input("완제품 중량 (kg)", value=float(st.session_state["pure_weight_val"]), step=0.05, format="%.2f")

                adj_hours = st.slider("개당 가공 소요시간 (h)", min_value=0.1, max_value=15.0, value=float(st.session_state["hours_val"]), step=0.05)
                
                s1, s2 = st.columns(2)
                with s1:
                    adj_difficulty = st.slider("가공 난이도 계수 (배율)", min_value=1.0, max_value=1.8, value=float(st.session_state["difficulty_val"]), step=0.05)
                with s2:
                    adj_loss_rate = st.slider("소재 절삭 로스율 (%)", min_value=10, max_value=40, value=int(st.session_state["loss_rate_val"]), step=5)

                order_memo = st.text_input("현장 비고 / AI 분석 산출 근거", value=st.session_state["memo_val"])
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

            final_part_name = st.session_state["custom_part_name"]

            quote_payload = {
                "id": now_id,
                "quote_no": quote_no,
                "group_id": "",
                "status": "1. 견적제출",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "due_date": due_date.strftime("%Y-%m-%d"),
                "client_name": client_name,
                "client_manager": client_manager,
                "filename": final_part_name,
                "thumbnail_b64": st.session_state.get("last_uploaded_thumb", ""),
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
            
            pdf_bytes = create_formal_pdf(quote_payload, settings["company_info"])

            with st.container():
                st.markdown('<div class="panel-card"><div class="panel-title">견적 산출 브레이크다운</div>', unsafe_allow_html=True)
                
                # AI 분석 완료 시 시각적 확인 배너
                if st.session_state.get("ai_analysis_done", False):
                    st.markdown("""
                    <div style="background:#E8F5E9; border:1px solid #38A169; border-radius:4px; padding:10px 14px; margin-bottom:12px; font-size:12.5px; color:#236542; display:flex; align-items:center; gap:8px;">
                        <span style="font-size:16px;">🎉</span> <b>AI 도면 분석 및 견적 산출 완료!</b> 도면 표제란과 치수를 읽어 공임 및 중량이 자동 계산되었습니다.
                    </div>
                    """, unsafe_allow_html=True)

                m1, m2 = st.columns(2)
                with m1:
                    st.markdown(f'<div class="metric-container"><div class="metric-label">개당 납품단가 (VAT 별도)</div><div class="metric-val">{final_unit_price:,} 원</div></div>', unsafe_allow_html=True)
                with m2:
                    st.markdown(f'<div class="metric-container"><div class="metric-label">총 견적 금액 ({order_qty} EA)</div><div class="metric-val" style="color:#1976D2;">{final_total_supply:,} 원</div></div>', unsafe_allow_html=True)

                if guardrail_triggered:
                    st.markdown(f"""
                    <div class="guardrail-alert" style="background:#FFF3E0; border:1px solid #DD6B20; color:#A65018; padding:8px 12px; border-radius:4px; font-size:12px; margin-bottom:10px;">
                        <b>최소 가공비(MIM) 보정 발동</b>: 계산 공임({calculated_machining_cost:,}원)이 기준선에 미달하여 기본공임 <b>{min_machining_threshold:,}원</b>으로 보정되었습니다.
                    </div>
                    """, unsafe_allow_html=True)

                cost_items = [
                    ("1. 원재료비", f"개당 {round(raw_material_weight,2)}kg x {mat_unit_price:,}원 x {order_qty}EA", f"{mat_total_cost:,} 원"),
                    ("2. 순수가공비", f"{adj_hours}h x 시급 {mac_hourly_rate:,}원 x 난이도 {adj_difficulty}", f"{final_machining_cost:,} 원"),
                    ("3. 초도세팅비", "기계 원점 및 툴 세팅 공임 (1회)", f"{setup_fee:,} 원"),
                    ("4. 표면/후처리비", f"{sel_surface} x {order_qty}EA", f"{surf_total_cost:,} 원"),
                    ("5. 관리비/마진", f"제조원가 대비 {margin_pct}%", f"{margin_amount:,} 원")
                ]

                html_rows = "".join([
                    f'<tr style="border-bottom: 1px solid #e6e6e6; color: #111111;">'
                    f'<td style="padding: 9px 8px; font-weight: 600;">{name}</td>'
                    f'<td style="padding: 9px 8px; color: #565656;">{formula}</td>'
                    f'<td style="padding: 9px 8px; text-align: right; font-weight: 700; color: #1976D2;">{price}</td>'
                    f'</tr>'
                    for name, formula, price in cost_items
                ])

                html_table = (
                    '<table style="width:100%; border-collapse:collapse; margin: 10px 0 16px 0; font-size: 13px;">'
                    '<thead><tr style="background-color: #eeeeee; border-bottom: 1px solid #cccccc; color: #333333; text-align: left;">'
                    '<th style="padding: 8px 8px;">원가 항목</th>'
                    '<th style="padding: 8px 8px;">산출 근거</th>'
                    '<th style="padding: 8px 8px; text-align: right;">금액</th>'
                    f'</tr></thead><tbody>{html_rows}</tbody></table>'
                )
                st.markdown(html_table, unsafe_allow_html=True)

                b1, b2 = st.columns(2)
                with b1:
                    if pdf_bytes:
                        st.download_button(
                            f"📄 [{final_part_name[:12]}] PDF 다운로드",
                            data=pdf_bytes,
                            file_name=f"{quote_no}_{final_part_name}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                    else:
                        st.button("PDF 준비 중...", disabled=True, use_container_width=True)
                with b2:
                    if st.button("현재 워크스페이스에 저장", use_container_width=True):
                        orders_db.insert(0, quote_payload)
                        save_tenant_data(active_cid, "orders_database.json", orders_db)
                        log_audit(active_cid, logged_user["name"], "견적서 발행 및 저장", f"[{quote_no}] {final_part_name}", f"공급가: {final_total_supply:,}원, 고객사: {client_name}")
                        st.session_state["ai_analysis_done"] = False
                        st.success(f"[{final_part_name}] 데이터베이스 저장 및 감사 로그 기록 완료")
                        st.rerun()

                if pdf_bytes:
                    open_in_new_tab_button(pdf_bytes, "application/pdf", label="정식 견적서 새 창 열기 (인쇄)")
                st.markdown('</div>', unsafe_allow_html=True)

    # ------------------------------------------
    # TAB 3: 공정흐름 관리 (MES 파이프라인 & 단계 편집기)
    # ------------------------------------------
    with tabs[2]:
        st.markdown('<div class="panel-card"><div class="panel-title" style="display:flex; justify-content:space-between; align-items:center;"><span>공정 진행 상태별 필터</span>', unsafe_allow_html=True)
        with st.popover("⚙️ 공정 단계 항목 편집 (추가/삭제/이름 변경)"):
            st.markdown("##### 등록된 공정 단계 편집")
            edited_stages = {}
            for s_key in list(STAGE_CONFIG.keys()):
                col_n1, col_n2 = st.columns([3, 1])
                with col_n1:
                    new_s_name = st.text_input(f"단계명", value=STAGE_CONFIG[s_key]["name"], key=f"st_edit_{s_key}")
                with col_n2:
                    st.write("")
                    st.write("")
                    del_stage = st.button("삭제", key=f"st_del_{s_key}")
                if not del_stage:
                    conf = STAGE_CONFIG[s_key].copy()
                    conf["name"] = new_s_name
                    edited_stages[s_key] = conf
            
            st.divider()
            new_stage_code = st.text_input("새 공정 식별자 (예: 5. 와이어가공)")
            new_stage_title = st.text_input("새 공정 표시명 (예: 와이어가공)")
            if st.button("+ 새 공정 단계 추가"):
                if new_stage_code and new_stage_title:
                    edited_stages[new_stage_code] = {"bg": "#E9F4FF", "color": "#1976D2", "name": new_stage_title}
                    settings["process_stages"] = edited_stages
                    save_tenant_data(active_cid, "pricing_settings.json", settings)
                    log_audit(active_cid, logged_user["name"], "공정 단계 추가", new_stage_code, new_stage_title)
                    st.success("새 공정이 추가되었습니다.")
                    st.rerun()

            if st.button("공정 단계 설정 영구 저장", type="primary", use_container_width=True):
                settings["process_stages"] = edited_stages
                save_tenant_data(active_cid, "pricing_settings.json", settings)
                log_audit(active_cid, logged_user["name"], "공정 단계 편집 저장", f"{len(edited_stages)}개 공정", "")
                st.success("공정 단계가 저장되었습니다.")
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

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
                display_title = STAGE_CONFIG[stage].get("name", stage.split('.')[1].strip() if '.' in stage else stage)
                if st.button(f"{display_title}\n({cnt})", use_container_width=True, type="primary" if is_active else "secondary"):
                    st.session_state["stage_filter"] = stage
                    st.rerun()

        current_filter = st.session_state["stage_filter"]
        mes_filtered = orders_db if current_filter == "전체" else [o for o in orders_db if o.get("status") == current_filter]

        if not mes_filtered:
            st.info("해당 단계의 등록 작업 건이 없습니다.")
        else:
            for idx, o in enumerate(mes_filtered):
                stage_name = o.get("status", "1. 견적제출")
                header_title = f"[{stage_name}] {o.get('quote_no')} | {o.get('client_name')} : {o.get('filename')} ({o.get('qty')} EA) | 납기: {o.get('due_date')}"
                
                with st.expander(header_title, expanded=False):
                    step_idx = PROCESS_STAGES.index(stage_name) if stage_name in PROCESS_STAGES else 0
                    
                    step_html = "<div style='display: flex; gap: 6px; margin-bottom: 12px; overflow-x: auto;'>"
                    for s_i, s_name in enumerate(PROCESS_STAGES):
                        conf = STAGE_CONFIG[s_name]
                        is_cur = (s_i == step_idx)
                        bg = conf['bg'] if s_i <= step_idx else "#f6f6f6"
                        color = conf['color'] if s_i <= step_idx else "#999999"
                        border = f"2px solid {conf['color']}" if is_cur else "1px solid #dcdcdc"
                        font_w = "700" if is_cur else "500"
                        step_html += f"<div style='flex:1; min-width:70px; background-color:{bg}; color:{color}; border:{border}; padding:6px 2px; text-align:center; border-radius:4px; font-size:11px; font-weight:{font_w};'>{conf['name']}</div>"
                    step_html += "</div>"
                    st.markdown(step_html, unsafe_allow_html=True)

                    r1, r2, r3 = st.columns([1.5, 2.0, 1.2])
                    with r1:
                        new_status = st.selectbox("단계 전환", PROCESS_STAGES, index=step_idx, key=f"status_{o['id']}")
                    with r2:
                        new_memo = st.text_input("현장 공정 메모", value=o.get("memo", ""), key=f"memo_{o['id']}")
                    with r3:
                        st.write("")
                        st.write("")
                        b_sv, b_dt = st.columns(2)
                        with b_sv:
                            if st.button("저장", key=f"save_{o['id']}", use_container_width=True):
                                for real_idx, target in enumerate(orders_db):
                                    if target["id"] == o["id"]:
                                        old_st = orders_db[real_idx]["status"]
                                        orders_db[real_idx]["status"] = new_status
                                        orders_db[real_idx]["memo"] = new_memo
                                        log_audit(active_cid, logged_user["name"], "공정 변경", f"[{o.get('quote_no')}] {o.get('filename')}", f"{old_st} ➔ {new_status}")
                                        break
                                save_tenant_data(active_cid, "orders_database.json", orders_db)
                                st.success("저장 완료")
                                st.rerun()
                        with b_dt:
                            if st.button("🔍 상세", key=f"mes_det_{o['id']}", use_container_width=True):
                                st.session_state["selected_quote_detail_id"] = o["id"]
                                st.rerun()

    # ------------------------------------------
    # TAB 4: 납기 캘린더 (드래그앤드롭 & 클릭 시 상세 검수 이동)
    # ------------------------------------------
    with tabs[3]:
        cal_mode = st.radio("보기 모드", ["월간 달력 그리드", "상세 납기 리스트"], horizontal=True, label_visibility="collapsed")
        today = datetime.today().date()

        if cal_mode == "월간 달력 그리드":
            with st.container():
                st.markdown('<div class="panel-card" style="padding:12px 16px; margin-bottom:12px;"><div class="panel-title" style="margin-bottom:8px; border-bottom:none;">⚡ 납기 일정 신속 변경 바 (클릭 이동 또는 아래 캘린더에서 드래그앤드롭 / 안건 클릭 시 상세 검수 화면 진입)</div>', unsafe_allow_html=True)
                sc1, sc2, sc3 = st.columns([2.5, 1.5, 1])
                with sc1:
                    valid_orders = [o for o in orders_db if o.get("status") != "7. 출하완료"]
                    if valid_orders:
                        target_order_label = st.selectbox(
                            "변경할 작업 선택",
                            options=[f"[{o.get('quote_no')}] {o.get('filename')} (현재: {o.get('due_date')})" for o in valid_orders],
                            label_visibility="collapsed"
                        )
                        selected_order_idx = [f"[{o.get('quote_no')}] {o.get('filename')} (현재: {o.get('due_date')})" for o in valid_orders].index(target_order_label)
                        chosen_order = valid_orders[selected_order_idx]
                    else:
                        chosen_order = None
                        st.caption("진행 중인 작업 건이 없습니다.")
                with sc2:
                    new_cal_due = st.date_input("이동할 새 납기일", value=today + timedelta(days=7), label_visibility="collapsed")
                with sc3:
                    if chosen_order and st.button("납기일 즉시 변경", type="primary", use_container_width=True):
                        old_d = chosen_order.get("due_date")
                        chosen_order["due_date"] = new_cal_due.strftime("%Y-%m-%d")
                        save_tenant_data(active_cid, "orders_database.json", orders_db)
                        log_audit(active_cid, logged_user["name"], "납기일 조정", f"[{chosen_order.get('quote_no')}] {chosen_order.get('filename')}", f"{old_d} ➔ {chosen_order['due_date']}")
                        st.success("일정이 업데이트되었습니다.")
                        st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

            c_y, c_m, _ = st.columns([1.2, 1.2, 3])
            with c_y:
                cal_year = st.selectbox("연도", range(today.year - 1, today.year + 3), index=1)
            with c_m:
                cal_month = st.selectbox("월", range(1, 13), index=today.month - 1)

            cal = calendar.Calendar(firstweekday=6)
            month_days = cal.monthdatescalendar(cal_year, cal_month)
            week_headers = ["일 (Sun)", "월 (Mon)", "화 (Tue)", "수 (Wed)", "목 (Thu)", "금 (Fri)", "토 (Sat)"]

            table_html = "<table style='width:100%; border-collapse:collapse; font-family:-apple-system, sans-serif;'><thead><tr>"
            for i, wh in enumerate(week_headers):
                color = "#DA4D3A" if i == 0 else ("#1976D2" if i == 6 else "#334155")
                table_html += f"<th style='background:#f1f5f9; color:{color}; padding:10px 0; text-align:center; font-weight:700; border:1px solid #cbd5e1; font-size:13.5px; width:14.28%;'>{wh}</th>"
            table_html += "</tr></thead><tbody>"

            for week in month_days:
                table_html += "<tr>"
                for day_date in week:
                    is_cur_month = (day_date.month == cal_month)
                    is_today = (day_date == today)
                    bg_color = "#f0f7ff" if is_today else ("#ffffff" if is_cur_month else "#f8fafc")
                    border_color = "2px solid #1976D2" if is_today else "1px solid #cbd5e1"
                    opacity = "1.0" if is_cur_month else "0.45"
                    day_str = day_date.strftime("%Y-%m-%d")

                    matching_orders = [o for o in orders_db if o.get("due_date") == day_str]
                    day_color = "#DA4D3A" if day_date.weekday() == 6 else ("#1976D2" if day_date.weekday() == 5 else "#0f172a")

                    badges_html = ""
                    for mo in matching_orders:
                        st_name = mo.get("status", "1. 견적제출")
                        conf = STAGE_CONFIG.get(st_name, {"bg": "#E9F4FF", "color": "#1667B8"})
                        is_overdue = (day_date < today and st_name != "7. 출하완료")
                        border_b = "1.5px solid #DA4D3A" if is_overdue else f"1px solid {conf['color']}"
                        oid = mo.get("id")
                        title_attr = f"[{mo.get('client_name')}] {mo.get('filename')} (클릭 시 견적 상세 검수 / 드래그 시 날짜 이동)"
                        badges_html += f"<div class='drag-item' draggable='true' data-id='{oid}' onclick='openDetail(\"{oid}\")' style='background:{conf['bg']}; color:{conf['color']}; border:{border_b}; padding:4px 6px; border-radius:4px; margin-top:5px; font-size:11.5px; font-weight:600; cursor:grab; box-shadow:0 1px 2px rgba(0,0,0,0.06); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;' title='{title_attr}'>● {mo.get('client_name')[:4]} | {mo.get('filename')[:7]}</div>"

                    table_html += f"<td class='cal-cell' data-date='{day_str}' style='min-height:240px; height:240px; background:{bg_color}; border:{border_color}; opacity:{opacity}; padding:8px 6px; vertical-align:top; overflow-y:auto;'><div style='font-weight:800; font-size:14px; margin-bottom:6px; color:{day_color};'>{day_date.day}</div>{badges_html}</td>"

                table_html += "</tr>"
            table_html += "</tbody></table>"

            cal_component_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
            <meta charset="utf-8">
            <style>
                .cal-cell.dragover {{
                    background-color: #E9F4FF !important;
                    outline: 2px dashed #1976D2 !important;
                    outline-offset: -2px;
                }}
                .drag-item:active {{
                    cursor: grabbing !important;
                    opacity: 0.5;
                }}
            </style>
            </head>
            <body style="margin:0; background:transparent;">
            {table_html}
            <script>
                let draggedId = null;

                function openDetail(orderId) {{
                    const targetUrl = './?view_detail=' + encodeURIComponent(orderId);
                    const a = document.createElement('a');
                    a.href = targetUrl;
                    a.target = '_top';
                    document.body.appendChild(a);
                    a.click();
                }}

                document.querySelectorAll('.drag-item').forEach(el => {{
                    el.addEventListener('dragstart', (e) => {{
                        draggedId = el.getAttribute('data-id');
                        e.dataTransfer.setData('text/plain', draggedId);
                        e.dataTransfer.effectAllowed = 'move';
                    }});
                }});

                document.querySelectorAll('.cal-cell').forEach(cell => {{
                    cell.addEventListener('dragover', (e) => {{
                        e.preventDefault();
                        cell.classList.add('dragover');
                    }});
                    cell.addEventListener('dragleave', () => {{
                        cell.classList.remove('dragover');
                    }});
                    cell.addEventListener('drop', (e) => {{
                        e.preventDefault();
                        cell.classList.remove('dragover');
                        const targetDate = cell.getAttribute('data-date');
                        if (draggedId && targetDate) {{
                            const targetUrl = './?move_id=' + encodeURIComponent(draggedId) + '&to_date=' + encodeURIComponent(targetDate);
                            const a = document.createElement('a');
                            a.href = targetUrl;
                            a.target = '_top';
                            document.body.appendChild(a);
                            a.click();
                        }}
                    }});
                }});
            </script>
            </body>
            </html>
            """
            calc_height = len(month_days) * 255 + 40
            components.html(cal_component_html, height=calc_height, scrolling=True)
        else:
            if not orders_db:
                st.info("등록된 작업 건이 없습니다.")
            else:
                for o in sorted(orders_db, key=lambda x: str(x.get("due_date", ""))):
                    due_str = o.get("due_date", "")
                    try:
                        diff = (datetime.strptime(due_str, "%Y-%m-%d").date() - today).days
                        d_day = f"{abs(diff)}일 지연" if diff < 0 else ("D-Day" if diff == 0 else f"D-{diff}")
                    except Exception:
                        d_day = "-"

                    st_name = o.get("status", "1. 견적제출")
                    conf = STAGE_CONFIG.get(st_name, {"bg": "#E9F4FF", "color": "#1667B8"})
                    
                    row_c1, row_c2, row_c3 = st.columns([1.2, 4.0, 1.0])
                    with row_c1:
                        st.markdown(f"**{d_day}** ({due_str})")
                    with row_c2:
                        st.markdown(f"**[{o.get('quote_no')}]** {o.get('filename')} ({o.get('client_name')}) | 공급가: **{o.get('total_price', 0):,}원** | <span style='background:{conf['bg']}; color:{conf['color']}; padding:2px 8px; border-radius:4px; font-weight:700;'>{st_name}</span>", unsafe_allow_html=True)
                    with row_c3:
                        if st.button("🔍 상세 검수", key=f"cal_list_det_{o['id']}", use_container_width=True):
                            st.session_state["selected_quote_detail_id"] = o["id"]
                            st.rerun()
                    st.divider()

    # ------------------------------------------
    # TAB 5: 시스템 설정 & 작업 감사 로그
    # ------------------------------------------
    with tabs[4]:
        st.markdown('<div class="panel-card"><div class="panel-title">📋 시스템 작업 및 견적 산출 감사 로그 (Audit Log)</div>', unsafe_allow_html=True)
        audit_logs = load_tenant_data(active_cid, "system_audit_logs.json", [])
        if not audit_logs:
            st.caption("아직 기록된 시스템 작업 내역이 없습니다.")
        else:
            log_df = pd.DataFrame(audit_logs)
            log_df.columns = ["작업 일시", "작업자", "작업 유형", "대상 품목/견적", "세부 내역"]
            st.dataframe(log_df, use_container_width=True, hide_index=True)
            
            csv_data = log_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "📥 감사 로그 CSV 다운로드",
                data=csv_data,
                file_name=f"costify_{active_cid}_audit_logs_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=False
            )
        st.markdown('</div>', unsafe_allow_html=True)

        if is_super_admin:
            st.markdown('<div class="panel-card"><div class="panel-title">고객사 워크스페이스 신규 발급 & 관리 (총괄 마스터 전용)</div>', unsafe_allow_html=True)
            nc1, nc2, nc3, nc4 = st.columns(4)
            with nc1:
                new_comp_name = st.text_input("고객사(공장) 상호명", placeholder="예: (주)삼우정밀")
            with nc2:
                new_comp_code = st.text_input("업체 식별 코드(영문소문자)", placeholder="예: samwoo")
            with nc3:
                new_comp_admin_id = st.text_input("업체 대표 계정 ID", placeholder="예: samwoo_admin")
            with nc4:
                new_comp_admin_pw = st.text_input("초기 비밀번호", type="password")

            if st.button("신규 고객사 워크스페이스 생성 및 발급", type="primary"):
                clean_code = new_comp_code.strip().lower()
                if not clean_code or not new_comp_name or not new_comp_admin_id or not new_comp_admin_pw:
                    st.error("모든 항목을 입력하세요.")
                elif clean_code in companies_db:
                    st.error("이미 존재하는 업체 식별 코드입니다.")
                elif new_comp_admin_id in users_db:
                    st.error("이미 사용 중인 계정 아이디입니다.")
                else:
                    companies_db[clean_code] = {
                        "name": new_comp_name.strip(),
                        "created_at": datetime.now().strftime("%Y-%m-%d")
                    }
                    save_json(COMPANIES_META_FILE, companies_db)

                    users_db[new_comp_admin_id] = {
                        "password": new_comp_admin_pw,
                        "name": f"{new_comp_name} 관리자",
                        "role": "company_admin",
                        "company_id": clean_code,
                        "last_seen_version": ""
                    }
                    save_json(USERS_FILE, users_db)

                    comp_dir = get_tenant_dir(clean_code)
                    init_settings = DEFAULT_SETTINGS.copy()
                    init_settings["company_info"]["company_name"] = new_comp_name.strip()
                    save_tenant_data(clean_code, "pricing_settings.json", init_settings)
                    save_tenant_data(clean_code, "orders_database.json", [])
                    save_tenant_data(clean_code, "clients_directory.json", [])
                    log_audit(active_cid, logged_user["name"], "신규 워크스페이스 발급", f"[{new_comp_name}]", f"ID: {new_comp_admin_id}")

                    st.success(f"[{new_comp_name}] 워크스페이스 생성 완료! 발급 ID: {new_comp_admin_id}")
                    st.rerun()

            st.markdown("##### 등록된 고객사 워크스페이스 목록")
            for cid, cinfo in list(companies_db.items()):
                row_c1, row_c2, row_c3 = st.columns([2.5, 2, 1])
                with row_c1:
                    st.write(f"🏢 **{cinfo['name']}** (`{cid}`)")
                with row_c2:
                    st.caption(f"생성일자: {cinfo.get('created_at', '-')}")
                with row_c3:
                    if cid == "master_workspace":
                        st.caption("시스템 마스터")
                    else:
                        if st.button("워크스페이스 삭제", key=f"del_comp_{cid}"):
                            del companies_db[cid]
                            save_json(COMPANIES_META_FILE, companies_db)
                            users_to_del = [u for u, dat in users_db.items() if dat.get("company_id") == cid]
                            for u in users_to_del:
                                del users_db[u]
                            save_json(USERS_FILE, users_db)
                            shutil.rmtree(os.path.join(COMPANIES_BASE_DIR, cid), ignore_errors=True)
                            st.success(f"[{cid}] 워크스페이스가 삭제되었습니다.")
                            st.rerun()
                st.divider()
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown(f'<div class="panel-card"><div class="panel-title">[{active_c_name}] 공급사 정보 및 기준 단가 설정</div>', unsafe_allow_html=True)
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

        if st.button("현재 워크스페이스 단가 및 공급사 정보 저장", type="primary", use_container_width=True):
            new_conf = {
                "company_info": {"company_name": c_name, "biz_num": c_biz, "ceo_name": c_ceo, "tel": c_tel, "email": c_email, "address": c_addr},
                "materials": up_materials,
                "machines": up_machines,
                "surface_treatments": up_surfaces,
                "process_stages": settings.get("process_stages", DEFAULT_STAGE_CONFIG),
                "default_setup_fee": up_setup,
                "min_machining_cost": up_min_machine,
                "default_material_loss": settings.get("default_material_loss", 20),
                "default_margin_rate": up_margin
            }
            save_tenant_data(active_cid, "pricing_settings.json", new_conf)
            log_audit(active_cid, logged_user["name"], "단가표 및 공급사 정보 수정", f"[{active_c_name}]", "기준 단가 및 가공 공임 변경")
            st.success(f"[{active_c_name}] 전용 단가표 및 공급사 정보가 저장되었습니다.")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown(f'<div class="panel-card"><div class="panel-title">[{active_c_name}] 전용 데이터 백업 & 복원</div>', unsafe_allow_html=True)
        bk1, bk2 = st.columns(2)
        with bk1:
            st.download_button(
                f"[{active_c_name}] 수주 데이터 백업 다운로드",
                data=json.dumps(orders_db, ensure_ascii=False, indent=2),
                file_name=f"costify_{active_cid}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )
        with bk2:
            restore_file = st.file_uploader(f"[{active_c_name}] 백업 JSON 업로드 복원", type=["json"])
            if restore_file and st.button("데이터 복원 실행", use_container_width=True):
                try:
                    restored = json.load(restore_file)
                    save_tenant_data(active_cid, "orders_database.json", restored)
                    log_audit(active_cid, logged_user["name"], "데이터베이스 복원", f"[{active_c_name}]", f"{len(restored)}건 데이터 복원")
                    st.success("데이터베이스 복원 성공")
                    st.rerun()
                except Exception as e:
                    st.error(f"복원 오류: {str(e)}")
        st.markdown('</div>', unsafe_allow_html=True)
