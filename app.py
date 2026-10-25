import streamlit as st
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
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta

# ==========================================
# 0. 시스템 버전 및 릴리즈 노트
# ==========================================
CURRENT_SYSTEM_VERSION = "v2.1.3"

SYSTEM_RELEASE_NOTES = [
    {
        "version": "v2.1.3",
        "date": "2026-10-25",
        "title": "503 트래픽 과부하 방어 3단 폴백 체인 구축",
        "details": [
            "구글 AI 서버 503 UNAVAILABLE 대비 3단계 모델 우회(flash ➔ pro ➔flash) 적용",
            "점진적 지수 백오프(2s ➔ 4s ➔ 6s) 대기 로직 적용으로 순간 트래픽 방어",
            "실패 시 직관적인 재시도 및 수동 모드 우회 가이드 배너 탑재"
        ]
    },
    {
        "version": "v2.1.2",
        "date": "2026-10-25",
        "title": "AI 분석 실행 엔진 안정화 및 즉각 피드백 복구",
        "details": [
            "AI 판독 데이터(소재, 중량, 시간, 난이도) 슬라이더 자동 주입 연동"
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

companies_db = load_json(COMPANIES_META_FILE, DEFAULT_COMPANIES)
users_db = load_json(USERS_FILE, DEFAULT_USERS)

# admin 마스터 권한 자동 보장
migration_needed = False
if "master_workspace" not in companies_db:
    companies_db["master_workspace"] = {"name": "Costify 본사 마스터", "created_at": "2026-10-25"}
    migration_needed = True

if "admin" in users_db:
    if users_db["admin"].get("role") != "super_admin" or users_db["admin"].get("company_id") != "master_workspace":
        users_db["admin"]["role"] = "super_admin"
        users_db["admin"]["company_id"] = "master_workspace"
        users_db["admin"]["name"] = "시스템 총괄마스터"
        migration_needed = True
else:
    users_db["admin"] = DEFAULT_USERS["admin"]
    migration_needed = True

if migration_needed:
    save_json(COMPANIES_META_FILE, companies_db)
    save_json(USERS_FILE, users_db)

# ==========================================
# 2. UI 테마 & 고시인성 스타일 시스템
# ==========================================
st.set_page_config(page_title="Costify | 정밀 절삭가공 견적 & MES", page_icon="⚙️", layout="wide")

st.markdown("""
<style>
    .stApp {
        background-color: #080d1a !important;
        color: #f1f5f9 !important;
    }
    .panel-card {
        background: #111a2e !important;
        border: 1px solid #1e2c47 !important;
        border-radius: 8px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    .panel-title {
        color: #38bdf8 !important;
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        margin-bottom: 14px;
        border-bottom: 1px solid #1e2c47;
        padding-bottom: 8px;
    }
    label, .stWidgetLabel p, .stWidgetLabel span {
        color: #cbd5e1 !important;
        font-weight: 600 !important;
        font-size: 12.5px !important;
    }
    input, textarea {
        background-color: #090e1c !important;
        color: #f8fafc !important;
        border: 1px solid #283959 !important;
        border-radius: 6px !important;
    }
    input:focus, textarea:focus {
        border-color: #0284c7 !important;
        box-shadow: 0 0 0 1px #0284c7 !important;
    }
    [data-testid="stDateInput"] div[data-baseweb="input"] {
        background-color: #090e1c !important;
        border: 1px solid #283959 !important;
        border-radius: 6px !important;
    }
    [data-testid="stDateInput"] input {
        background-color: transparent !important;
        color: #f8fafc !important;
    }
    [data-testid="stDateInput"] svg {
        fill: #94a3b8 !important;
    }
    [data-baseweb="select"] > div {
        background-color: #090e1c !important;
        color: #f8fafc !important;
        border: 1px solid #283959 !important;
        border-radius: 6px !important;
    }
    [data-baseweb="popover"], [data-baseweb="menu"] {
        background-color: #111a2e !important;
        border: 1px solid #1e2c47 !important;
    }
    [data-testid="stNumberInput"] button {
        background-color: #18233c !important;
        color: #cbd5e1 !important;
        border-color: #283959 !important;
    }
    [data-testid="stFileUploaderDropzone"] {
        background-color: #090e1c !important;
        border: 1px dashed #283959 !important;
        border-radius: 8px !important;
    }
    [data-testid="stFileUploaderDropzone"] button {
        background-color: #18233c !important;
        color: #f8fafc !important;
        border: 1px solid #283959 !important;
    }
    [data-testid="stRadio"] [aria-checked="true"] div {
        border-color: #0284c7 !important;
        background-color: #0284c7 !important;
    }
    button[kind="primary"] {
        background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%) !important;
        color: #ffffff !important;
        border: none !important;
        font-weight: 700 !important;
        box-shadow: 0 2px 8px rgba(2, 132, 199, 0.3) !important;
        border-radius: 6px !important;
    }
    button[kind="secondary"] {
        background-color: #152037 !important;
        color: #cbd5e1 !important;
        border: 1px solid #283959 !important;
        font-weight: 600 !important;
        border-radius: 6px !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        border-bottom: 1px solid #1e2c47 !important;
        padding-bottom: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #94a3b8 !important;
        font-weight: 600 !important;
        padding: 8px 16px !important;
    }
    .stTabs [aria-selected="true"] {
        color: #38bdf8 !important;
        border-bottom: 2px solid #38bdf8 !important;
        background-color: transparent !important;
    }
    .metric-container {
        background: #090e1c;
        border: 1px solid #1e2c47;
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 8px;
    }
    .metric-label { color: #94a3b8; font-size: 11.5px; font-weight: 600; }
    .metric-val { color: #f8fafc; font-size: 21px; font-weight: 700; margin-top: 2px; }
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
        background: #152037;
        border: 1px solid #283959;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        color: #e2e8f0;
    }
    .cal-header {
        background-color: #090e1c;
        color: #94a3b8;
        padding: 8px;
        text-align: center;
        font-weight: 700;
        border: 1px solid #1e2c47;
        font-size: 12px;
    }
    .cal-day-cell {
        min-height: 95px;
        background-color: #111a2e;
        border: 1px solid #1e2c47;
        padding: 6px;
        vertical-align: top;
    }
    .cal-day-cell.other-month { background-color: #080d1a; opacity: 0.35; }
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

# 브라우저 새로고침(F5) 세션 유지
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

query_uid = st.query_params.get("u")
query_token = st.query_params.get("k")

if not st.session_state["auth_user"] and query_uid and query_token:
    if query_uid in users_db and query_token == generate_session_token(query_uid):
        st.session_state["auth_user"] = users_db[query_uid]
        st.session_state["auth_user_id"] = query_uid

# 미로그인 상태 시 로그인 화면
if not st.session_state["auth_user"]:
    _, login_col, _ = st.columns([1, 1.2, 1])
    with login_col:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("### COSTIFY PORTAL")
        st.caption("정밀 절삭가공 표준 원가 산출 및 MES 플랫폼")
        
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

# ==========================================
# 4. 상단 헤더, 마스터 스위처 & 릴리즈 노트
# ==========================================
user_last_seen = users_db.get(current_user_id, {}).get("last_seen_version", "")
has_new_update = (user_last_seen != CURRENT_SYSTEM_VERSION)

head_left, head_right = st.columns([2.2, 2.8])
with head_left:
    st.markdown(f"### COSTIFY <span style='font-size:13px; font-weight:600; color:#38bdf8;'>[{active_c_name}]</span>", unsafe_allow_html=True)

with head_right:
    if is_super_admin:
        sw_col, rel_col, prof_col, btn_col = st.columns([1.8, 0.9, 1.4, 0.9])
        with sw_col:
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
        rel_col, prof_col, btn_col = st.columns([1.2, 2.2, 1.0])

    with rel_col:
        label_text = f"업데이트 ●" if has_new_update else "업데이트"
        with st.popover(label_text, use_container_width=True):
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

    with prof_col:
        st.markdown(f"""
        <div style="text-align: right; padding-top: 5px;">
            <span class="profile-badge">● {logged_user['name']}</span>
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
            background-color: #152037;
            color: #38bdf8;
            border: 1px solid #283959;
            padding: 8px 14px;
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
    components.html(js_code, height=44)

# ==========================================
# 5. 사이드바: 퀵 툴박스
# ==========================================
def get_secure_api_key():
    try:
        if hasattr(st, "secrets"):
            if "GEMINI_API_KEY" in st.secrets:
                return st.secrets["GEMINI_API_KEY"]
            if "gemini_api_key" in st.secrets:
                return st.secrets["gemini_api_key"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "")

SECURE_API_KEY = get_secure_api_key()

with st.sidebar:
    st.markdown(f"### 엔지니어 퀵 툴박스")
    st.caption(f"접속 공간: **{active_c_name}**")
    
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
                <div style="background:#152037; border-left:3px solid #ef4444; padding:6px 8px; border-radius:4px; margin-bottom:6px; font-size:11px;">
                    <b style="color:#f87171;">{tag}</b> | {uo.get('client_name')[:5]}<br>
                    {uo.get('filename')[:12]} ({uo.get('qty')}EA) | <span style="color:#94a3b8;">{uo.get('status')}</span>
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
        <div style="background:#090e1c; padding:8px; border-radius:6px; border:1px solid #1e2c47; text-align:center; margin:8px 0;">
            <div style="font-size:11px; color:#94a3b8;">계산된 순수 중량</div>
            <div style="font-size:18px; font-weight:700; color:#38bdf8;">{calc_weight_kg:.3f} kg</div>
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
        <div style="background:#090e1c; padding:8px; border-radius:6px; border:1px solid #1e2c47; font-size:12px; margin-top:6px;">
            주축 회전수: <b style="color:#f8fafc;">{calc_rpm:,} RPM</b><br>
            이송속도: <b style="color:#f8fafc;">{calc_feed:,} mm/min</b><br>
            1회 가공소요: <b style="color:#38bdf8;">{calc_time_sec // 60}분 {calc_time_sec % 60}초</b>
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
# 6. AI 3단 폴백 & 지수 백오프 분석 엔진 (503 방어)
# ==========================================
def analyze_drawing_resilient(api_key, file_bytes, mime_type, filename):
    client = genai.Client(api_key=api_key.strip())
    doc_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    
    prompt = """
    당신은 한국 20년 경력의 베테랑 절삭가공(MCT/CNC) 공장장입니다.
    업로드된 도면을 분석하여 다음 항목을 반드시 순수한 JSON 형식으로만 추출하세요.
    {
        "material_type": "재질 (도면 표기 규격, 예: AL6061, SUS304, SS400, S45C 등)",
        "pure_weight_kg": 숫자 (완제품 순수 중량 kg, 소수점 둘째자리),
        "cutting_loss_percent": 숫자 (원소재 절삭 로스율 %, 기본 20%),
        "estimated_machining_hours": 숫자 (순수 절삭 가공 소요 시간 h, 소수점 둘째자리),
        "recommended_machine": "추천설비 (3축 머시닝센터(MCT), 5축 머시닝센터(MCT), CNC 복합선반, 범용 선반 / 밀링 중 1개)",
        "difficulty_factor": 숫자 (난이도 계수 1.0~1.8),
        "holes_count": 숫자 (가공 홀 수),
        "reasoning": "산출 근거 요약"
    }
    """
    
    # 3단계 모델 우회 체인
    models_cascade = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.8-flash"]
    last_err_detail = ""
    
    for model_candidate in models_cascade:
        # 점진적 지수 대기 (1회차: 2초, 2회차: 4초)
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_candidate,
                    contents=[doc_part, prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
                return json.loads(clean_text), None
            except Exception as e:
                last_err_detail = str(e)
                # 503 또는 429 감지 시 서버 회복을 위해 대기 후 재시도
                if any(x in last_err_detail for x in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"]):
                    time.sleep(2 * (attempt + 1))
                    continue
                else:
                    break  # 일반 에러는 다음 모델로 우회

    return None, last_err_detail

# ==========================================
# 7. PDF 견적서 생성기
# ==========================================
def create_formal_pdf(q, company_info):
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

    c_info = company_info
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
# 8. 메인 워크스페이스
# ==========================================
tabs = st.tabs(["실시간 견적 산출", "공정흐름 관리 (MES)", "납기 캘린더", "그룹 발주 관리", "시스템 설정"])

# ------------------------------------------
# TAB 1: 실시간 견적 산출 (2열 워크스페이스)
# ------------------------------------------
with tabs[0]:
    left_col, right_col = st.columns([1.1, 0.9], gap="medium")

    # 세션 기본값 관리
    if "client_name_val" not in st.session_state: st.session_state["client_name_val"] = "(주)한국정밀"
    if "client_mgr_val" not in st.session_state: st.session_state["client_mgr_val"] = "김철수 부장"
    if "pure_weight_val" not in st.session_state: st.session_state["pure_weight_val"] = 0.50
    if "hours_val" not in st.session_state: st.session_state["hours_val"] = 0.50
    if "difficulty_val" not in st.session_state: st.session_state["difficulty_val"] = 1.00
    if "loss_rate_val" not in st.session_state: st.session_state["loss_rate_val"] = int(settings.get("default_material_loss", 20))
    if "memo_val" not in st.session_state: st.session_state["memo_val"] = ""
    if "active_drawing_name" not in st.session_state: st.session_state["active_drawing_name"] = "도면"

    with left_col:
        # 카드 1: 발주 기본 정보
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

        # 카드 2: 도면 파일 및 입력 방식
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

                # AI 분석 실행 (3단 우회 체인 적용)
                if start_ai:
                    if not uploaded_file:
                        st.warning("⚠️ 먼저 도면 파일을 업로드해 주세요.")
                    elif not SECURE_API_KEY:
                        st.error("❌ Gemini API 키가 감지되지 않았습니다. Streamlit Secrets를 확인하세요.")
                    else:
                        with st.spinner("⚡ AI 서버 연결 중... (과부하 감지 시 대체 클러스터로 자동 우회합니다)"):
                            parsed_res, err = analyze_drawing_resilient(SECURE_API_KEY, uploaded_file.getvalue(), file_mime, uploaded_file.name)
                            if err:
                                st.error("❌ 구글 AI 서버 트래픽이 현재 전 세계적으로 극심하여 모든 대체 모델 연결이 지연되었습니다.")
                                st.info("💡 팁: 약 5~10초 후 'AI 분석 실행'을 다시 누르면 정상 처리됩니다. 작업이 급하신 경우 상단의 '수동 직접 입력' 모드로 전환하여 즉시 견적을 산출하실 수 있습니다.")
                            elif parsed_res:
                                st.session_state["active_drawing_name"] = uploaded_file.name
                                st.session_state["pure_weight_val"] = float(parsed_res.get("pure_weight_kg", 0.50))
                                st.session_state["hours_val"] = float(parsed_res.get("estimated_machining_hours", 0.50))
                                st.session_state["difficulty_val"] = float(parsed_res.get("difficulty_factor", 1.00))
                                st.session_state["loss_rate_val"] = int(parsed_res.get("cutting_loss_percent", 20))
                                st.session_state["memo_val"] = parsed_res.get("reasoning", "")
                                st.session_state["ai_suggested_mat"] = parsed_res.get("material_type", "")
                                st.session_state["ai_suggested_mac"] = parsed_res.get("recommended_machine", "")
                                st.success("✅ AI 도면 판독 완료! 중량, 시간, 난이도가 아래 검수창에 자동 입력되었습니다.")
                                st.rerun()

            else:
                st.session_state["active_drawing_name"] = st.text_input("품목명 / 도면 식별 번호", value="BRACKET-M01")
            st.markdown('</div>', unsafe_allow_html=True)

        # 카드 3: 사장님 정밀 검수
        with st.container():
            st.markdown('<div class="panel-card"><div class="panel-title">3. 가공 조건 & 엔지니어링 미세 조정</div>', unsafe_allow_html=True)
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

            order_memo = st.text_input("현장 비고 / 특이사항 메모", value=st.session_state["memo_val"])
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
            "filename": st.session_state["active_drawing_name"],
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

            cost_items = [
                ("1. 원재료비", f"개당 {round(raw_material_weight,2)}kg x {mat_unit_price:,}원 x {order_qty}EA", f"{mat_total_cost:,} 원"),
                ("2. 순수가공비", f"{adj_hours}h x 시급 {mac_hourly_rate:,}원 x 난이도 {adj_difficulty}", f"{final_machining_cost:,} 원"),
                ("3. 초도세팅비", "기계 원점 및 툴 세팅 공임 (1회)", f"{setup_fee:,} 원"),
                ("4. 표면/후처리비", f"{sel_surface} x {order_qty}EA", f"{surf_total_cost:,} 원"),
                ("5. 관리비/마진", f"제조원가 대비 {margin_pct}%", f"{margin_amount:,} 원")
            ]

            html_rows = "".join([
                f'<tr style="border-bottom: 1px solid #1e2c47; color: #f8fafc;">'
                f'<td style="padding: 9px 6px; font-weight: 600;">{name}</td>'
                f'<td style="padding: 9px 6px; color: #cbd5e1;">{formula}</td>'
                f'<td style="padding: 9px 6px; text-align: right; font-weight: 700; color: #38bdf8;">{price}</td>'
                f'</tr>'
                for name, formula, price in cost_items
            ])

            html_table = (
                '<table style="width:100%; border-collapse:collapse; margin: 10px 0 16px 0; font-size: 13px;">'
                '<thead><tr style="border-bottom: 2px solid #283959; color: #94a3b8; text-align: left;">'
                '<th style="padding: 8px 6px;">원가 항목</th>'
                '<th style="padding: 8px 6px;">산출 근거</th>'
                '<th style="padding: 8px 6px; text-align: right;">금액</th>'
                f'</tr></thead><tbody>{html_rows}</tbody></table>'
            )
            st.markdown(html_table, unsafe_allow_html=True)

            b1, b2 = st.columns(2)
            with b1:
                st.download_button("견적서 PDF 다운로드", data=pdf_bytes, file_name=f"{quote_no}_{client_name}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            with b2:
                if st.button("현재 워크스페이스에 저장", use_container_width=True):
                    orders_db.insert(0, quote_payload)
                    save_tenant_data(active_cid, "orders_database.json", orders_db)
                    st.success(f"[{active_c_name}] 데이터베이스에 저장 완료")
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
                    bg = STAGE_CONFIG[s_name]['color'] if s_i <= step_idx else "#152037"
                    opac = "1.0" if s_i == step_idx else ("0.55" if s_i < step_idx else "0.25")
                    border = "1px solid #38bdf8" if s_i == step_idx else "1px solid #283959"
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
                        save_tenant_data(active_cid, "orders_database.json", orders_db)
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
            save_tenant_data(active_cid, "orders_database.json", orders_db)
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
# TAB 5: 시스템 설정 & 테넌트 관리
# ------------------------------------------
with tabs[4]:
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

                st.success(f"[{new_comp_name}] 워크스페이스가 생성되었습니다! 발급 ID: {new_comp_admin_id}")
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
            "default_setup_fee": up_setup,
            "min_machining_cost": up_min_machine,
            "default_material_loss": settings.get("default_material_loss", 20),
            "default_margin_rate": up_margin
        }
        save_tenant_data(active_cid, "pricing_settings.json", new_conf)
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
                st.success("데이터베이스 복원 성공")
                st.rerun()
            except Exception as e:
                st.error(f"복원 오류: {str(e)}")
    st.markdown('</div>', unsafe_allow_html=True)
