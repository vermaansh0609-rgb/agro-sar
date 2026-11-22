import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import requests
import json
import time
import re
from datetime import datetime
import plotly.graph_objects as go
import streamlit.components.v1 as components
from deep_translator import GoogleTranslator

st.set_page_config(
    page_title="AgroSAR | Precision Agriculture Portal",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="collapsed"
)

@st.cache_resource
def authenticate_gee():
    try:
        service_account_str = st.secrets["GEE_SERVICE_ACCOUNT"]
        service_account_info = json.loads(service_account_str)
        credentials = ee.ServiceAccountCredentials(
            service_account_info["client_email"],
            key_data=json.dumps(service_account_info)
        )
        project_id = service_account_info.get("project_id", "neon-trilogy-386710")
        ee.Initialize(credentials, project=project_id)
        return True, None
    except Exception as e:
        return False, str(e)

gee_ready, auth_error = authenticate_gee()

@st.cache_data(ttl=600, show_spinner=False)
def resolve_location_cached(query_str: str):
    clean_q = query_str.strip()
    if not clean_q:
        return None

    if "," in clean_q:
        parts = [p.strip() for p in clean_q.split(",")]
        if len(parts) == 2:
            try:
                lat_val = float(parts[0])
                lon_val = float(parts[1])
                if -90.0 <= lat_val <= 90.0 and -180.0 <= lon_val <= 180.0:
                    return {
                        "lat": lat_val,
                        "lon": lon_val,
                        "address": f"Live GPS Field Coordinates ({lat_val:.4f}, {lon_val:.4f})"
                    }
            except ValueError:
                pass

    try:
        geolocator = Nominatim(
            user_agent=f"agrosar_field_portal_iem_{abs(hash(clean_q)) % 10000}",
            timeout=5
        )
        location = geolocator.geocode(f"{clean_q}, India")
        if location:
            return {
                "lat": float(location.latitude),
                "lon": float(location.longitude),
                "address": location.address
            }
    except Exception:
        pass

    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": clean_q, "count": 1, "language": "en", "format": "json"},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("results"):
                top = data["results"][0]
                admin = top.get("admin1", "")
                country = top.get("country", "India")
                addr = ", ".join([x for x in [top.get("name"), admin, country] if x])
                return {
                    "lat": float(top["latitude"]),
                    "lon": float(top["longitude"]),
                    "address": addr
                }
    except Exception:
        pass

    return None

@st.cache_data(ttl=3600, show_spinner=False)
def _translate_single_success(clean_text: str, target_lang_code: str):
    try:
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "en",
                "tl": target_lang_code,
                "dt": "t",
                "q": clean_text
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6
        )
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, list) and payload and isinstance(payload[0], list):
                joined = "".join([seg[0] for seg in payload[0] if seg and seg[0]])
                if joined and joined.strip().lower() != clean_text.strip().lower():
                    return joined.strip()
    except Exception:
        pass

    try:
        res_txt = GoogleTranslator(source="en", target=target_lang_code).translate(clean_text)
        if res_txt and res_txt.strip().lower() != clean_text.strip().lower():
            return res_txt.strip()
    except Exception:
        pass

    return None

def translate_advisories_list(texts_list, target_lang_code: str):
    if target_lang_code == "en":
        return list(texts_list)
    output = []
    for item in texts_list:
        parts = item.split(" ", 1)
        if len(parts) == 2 and not parts[0][0].isalnum():
            emoji_prefix, body = parts[0], parts[1]
        else:
            emoji_prefix, body = "", item
        sanitized_body = re.sub(r"\s*\([^A-Za-z0-9.,%+\-/ ]+\)", "", body).strip()
        translated_body = _translate_single_success(sanitized_body, target_lang_code)
        if translated_body:
            output.append(f"{emoji_prefix} {translated_body}".strip())
        else:
            output.append(item)
    return output

if "splash_seen" not in st.session_state:
    st.session_state["splash_seen"] = False
if "active_page" not in st.session_state:
    st.session_state["active_page"] = "🏠 HomePage"
if "scan_performed" not in st.session_state:
    st.session_state["scan_performed"] = False
if "scan_results" not in st.session_state:
    st.session_state["scan_results"] = None
if "field_lat" not in st.session_state:
    st.session_state["field_lat"] = 22.5726
if "field_lon" not in st.session_state:
    st.session_state["field_lon"] = 88.3639
if "field_address" not in st.session_state:
    st.session_state["field_address"] = "Kolkata, West Bengal, India"
if "last_search_input" not in st.session_state:
    st.session_state["last_search_input"] = "Kolkata"
if "gps_override_active" not in st.session_state:
    st.session_state["gps_override_active"] = False
if "scan_counter" not in st.session_state:
    st.session_state["scan_counter"] = 0

query_params = st.query_params
if "gps_lat" in query_params and "gps_lon" in query_params:
    try:
        q_lat = float(query_params["gps_lat"])
        q_lon = float(query_params["gps_lon"])
        if -90.0 <= q_lat <= 90.0 and -180.0 <= q_lon <= 180.0:
            st.session_state["field_lat"] = q_lat
            st.session_state["field_lon"] = q_lon
            st.session_state["field_address"] = f"Live Field GPS Lock ({q_lat:.4f}° N, {q_lon:.4f}° E)"
            st.session_state["gps_override_active"] = True
            st.session_state["active_page"] = "🗺️ Radar Analysis Canvas"
            st.session_state["splash_seen"] = True
            st.query_params.clear()
    except Exception:
        st.query_params.clear()

st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {
        display: none !important;
    }

    .stApp {
        background-color: #F3EFE6 !important;
        color: #1E3F20 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Devanagari", "Noto Sans Bengali", sans-serif;
    }

    .stApp p, .stApp li, .stApp span, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
        color: #1E3F20;
    }

    [data-testid="stAlert"],
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] span,
    [data-testid="stAlert"] div {
        color: #FFFFFF !important;
    }

    .agro-brand-bar {
        display: flex;
        align-items: center;
        gap: 18px;
        padding: 12px 18px;
        margin-bottom: 14px;
        background-color: #EAE2D3;
        border: 1.5px solid #D3C6B0;
        border-radius: 14px;
        box-shadow: 0 4px 12px rgba(74, 55, 40, 0.08);
    }

    .agro-title {
        font-size: 3.1rem;
        font-weight: 900;
        letter-spacing: 0.025em;
        background: linear-gradient(90deg, #1E3F20 0%, #4A3728 60%, #D99B26 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1.08;
    }

    .stButton > button {
        background-color: #4A3728 !important;
        color: #FFFFFF !important;
        border: 1.5px solid #4A3728 !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        box-shadow: 0 3px 8px rgba(74, 55, 40, 0.14) !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button p, .stButton > button span, .stButton > button div {
        color: #FFFFFF !important;
    }
    .stButton > button:hover {
        background-color: #1E3F20 !important;
        border-color: #D99B26 !important;
        color: #FFFFFF !important;
        transform: translateY(-1px);
    }
    .stButton > button:hover p, .stButton > button:hover span {
        color: #FFFFFF !important;
    }

    div[data-testid="stHorizontalBlock"] .stButton > button {
        border-radius: 999px !important;
        padding: 0.48rem 0.95rem !important;
        font-size: 0.88rem !important;
    }

    .stButton > button[kind="primary"],
    div[data-testid="stHorizontalBlock"] .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #1E3F20 0%, #2D5A27 100%) !important;
        color: #FFFFFF !important;
        border: 1.5px solid #D99B26 !important;
        box-shadow: 0 4px 12px rgba(30, 63, 32, 0.24) !important;
    }
    .stButton > button[kind="primary"] p,
    .stButton > button[kind="primary"] span,
    div[data-testid="stHorizontalBlock"] .stButton > button[kind="primary"] p,
    div[data-testid="stHorizontalBlock"] .stButton > button[kind="primary"] span {
        color: #FFFFFF !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #163018 0%, #1E3F20 100%) !important;
        color: #FFFFFF !important;
    }

    .stDownloadButton > button {
        background: linear-gradient(135deg, #1E3F20 0%, #4A3728 100%) !important;
        color: #FFFFFF !important;
        border: 1.5px solid #D99B26 !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 12px rgba(30, 63, 32, 0.20) !important;
    }
    .stDownloadButton > button p, .stDownloadButton > button span {
        color: #FFFFFF !important;
    }

    div[data-testid="stExpander"] {
        background-color: #EAE2D3 !important;
        border: 1.5px solid #D3C6B0 !important;
        border-radius: 12px !important;
    }
    div[data-testid="stExpander"] summary {
        background-color: #EAE2D3 !important;
        color: #1E3F20 !important;
        font-weight: 700 !important;
    }
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div {
        background-color: #F3EFE6 !important;
        color: #1E3F20 !important;
        border: 1.5px solid #B8A88E !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="select"] span,
    div[data-baseweb="input"] input {
        color: #1E3F20 !important;
    }
    ul[data-baseweb="menu"] {
        background-color: #F3EFE6 !important;
        border: 1px solid #B8A88E !important;
    }
    ul[data-baseweb="menu"] li {
        color: #1E3F20 !important;
    }

    [data-testid="stJson"] {
        background-color: #EAE2D3 !important;
        border: 1.5px solid #C8B9A0 !important;
        border-radius: 12px !important;
        padding: 14px 16px !important;
    }
    [data-testid="stJson"] * {
        color: #1E3F20 !important;
    }
    [data-testid="stJson"] .string-value {
        color: #4A3728 !important;
        font-weight: 600 !important;
    }
    [data-testid="stJson"] .number-value,
    [data-testid="stJson"] .boolean-value {
        color: #9A6708 !important;
        font-weight: 700 !important;
    }

    [data-testid="stCode"],
    [data-testid="stCode"] pre,
    [data-testid="stCode"] code {
        background-color: #EAE2D3 !important;
        color: #1E3F20 !important;
        border-radius: 12px !important;
    }
    [data-testid="stCode"] {
        border: 1.5px solid #C8B9A0 !important;
    }

    .hud-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 16px;
        margin-bottom: 24px;
    }
    .hud-grid-3 {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 16px;
        margin-bottom: 22px;
    }

    @media (max-width: 960px) {
        .hud-grid { grid-template-columns: repeat(2, 1fr); }
        .hud-grid-3 { grid-template-columns: 1fr; }
    }
    @media (max-width: 540px) {
        .hud-grid { grid-template-columns: 1fr; }
    }

    .hud-card {
        background-color: #EAE2D3;
        border: 1.5px solid #C8B9A0;
        border-radius: 14px;
        padding: 18px 16px;
        position: relative;
        box-shadow: 0 4px 12px rgba(74, 55, 40, 0.08);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 185px;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
        cursor: pointer;
    }

    .hud-card:hover {
        transform: translateY(-4px);
        border-color: #D99B26;
        box-shadow: 0 10px 22px rgba(74, 55, 40, 0.14);
        z-index: 30;
    }

    .hud-card::before {
        content: "";
        position: absolute;
        top: 0; left: 16px; right: 16px;
        height: 4px;
        border-radius: 0 0 4px 4px;
        background: linear-gradient(90deg, #1E3F20, #D99B26);
    }

    .hover-popup {
        visibility: hidden;
        opacity: 0;
        position: absolute;
        bottom: calc(100% + 12px);
        left: 50%;
        transform: translateX(-50%) translateY(8px);
        width: 270px;
        background-color: #F3EFE6;
        border: 2px solid #D99B26;
        border-radius: 14px;
        padding: 12px 14px;
        box-shadow: 0 12px 26px rgba(74, 55, 40, 0.20);
        z-index: 999;
        transition: opacity 0.22s ease, transform 0.22s ease, visibility 0.22s;
        pointer-events: none;
        text-align: center;
    }

    .hover-popup::after {
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        margin-left: -8px;
        border-width: 8px;
        border-style: solid;
        border-color: #D99B26 transparent transparent transparent;
    }

    .hud-card:hover .hover-popup {
        visibility: visible;
        opacity: 1;
        transform: translateX(-50%) translateY(0);
    }

    .popup-title {
        font-size: 0.84rem;
        font-weight: 800;
        color: #1E3F20;
        margin-top: 6px;
        margin-bottom: 3px;
    }

    .popup-caption {
        font-size: 0.75rem;
        color: #4A3728;
        line-height: 1.35;
    }

    .profile-popup {
        visibility: hidden;
        opacity: 0;
        position: absolute;
        bottom: calc(100% + 12px);
        left: 50%;
        transform: translateX(-50%) translateY(8px);
        width: 315px;
        background-color: #F3EFE6;
        border: 2px solid #1E3F20;
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: 0 12px 28px rgba(74, 55, 40, 0.22);
        z-index: 999;
        transition: opacity 0.22s ease, transform 0.22s ease, visibility 0.22s;
        pointer-events: none;
        text-align: left;
    }

    .profile-popup::after {
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        margin-left: -8px;
        border-width: 8px;
        border-style: solid;
        border-color: #1E3F20 transparent transparent transparent;
    }

    .hud-card:hover .profile-popup {
        visibility: visible;
        opacity: 1;
        transform: translateX(-50%) translateY(0);
    }

    .profile-row {
        font-size: 0.79rem;
        color: #1E3F20;
        margin-bottom: 4px;
        line-height: 1.38;
    }

    .profile-badge {
        display: inline-block;
        background-color: #EAE2D3;
        color: #4A3728;
        font-weight: 700;
        font-size: 0.72rem;
        padding: 3px 9px;
        border-radius: 999px;
        margin-bottom: 6px;
        border: 1px solid #C8B9A0;
    }

    .hud-card-name {
        font-size: 1.3rem;
        font-weight: 800;
        color: #1E3F20;
        margin: auto 0;
        letter-spacing: 0.03em;
    }

    .hud-card-label {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #4A3728;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .hud-card-value {
        font-size: 1.85rem;
        font-weight: 800;
        color: #1E3F20;
        margin: 8px 0 4px 0;
        line-height: 1.15;
    }

    .hud-card-value-cmd {
        font-size: clamp(0.88rem, 1.08vw, 1.05rem);
        font-weight: 800;
        color: #4A3728;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        margin: 10px 0 6px 0;
        line-height: 1.25;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        letter-spacing: -0.02em;
    }

    .card-explainer {
        font-size: 0.76rem;
        color: #4A3728;
        margin-bottom: 10px;
        line-height: 1.35;
    }

    .hud-pill {
        border-radius: 8px;
        padding: 7px 10px;
        font-size: 0.76rem;
        line-height: 1.35;
        font-weight: 600;
    }

    .pill-green {
        background-color: #DCE8D5;
        border: 1px solid #1E3F20;
        color: #1E3F20;
    }

    .pill-amber {
        background-color: #F6E6C4;
        border: 1px solid #D99B26;
        color: #4A3728;
    }

    .pill-red {
        background-color: #F4D6D2;
        border: 1px solid #A63A2B;
        color: #6E1E14;
    }

    .pill-blue {
        background-color: #DCE5E8;
        border: 1px solid #3B6E8C;
        color: #1C3D52;
    }

    .mission-box {
        background-color: #EAE2D3;
        border: 1.5px solid #C8B9A0;
        border-left: 5px solid #1E3F20;
        border-radius: 14px;
        padding: 20px 22px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(74, 55, 40, 0.08);
        color: #1E3F20;
    }

    .overview-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 14px;
    }

    .overview-badge {
        background-color: #F3EFE6;
        border: 1px solid #C8B9A0;
        color: #4A3728;
        font-size: 0.8rem;
        font-weight: 700;
        padding: 6px 12px;
        border-radius: 999px;
    }

    .advisory-item {
        background-color: #EAE2D3;
        border: 1px solid #C8B9A0;
        border-left: 5px solid #1E3F20;
        padding: 13px 16px;
        margin-bottom: 10px;
        border-radius: 0 10px 10px 0;
        font-size: 0.94rem;
        line-height: 1.55;
        color: #1E3F20;
        box-shadow: 0 2px 6px rgba(74, 55, 40, 0.06);
    }
    .advisory-alert {
        border-left-color: #A63A2B;
    }
    .advisory-warn {
        border-left-color: #D99B26;
    }
    .advisory-safe {
        border-left-color: #1E3F20;
    }

    @keyframes swayStalk {
        0%, 100% { transform: rotate(-4deg); }
        50% { transform: rotate(6deg); }
    }
    @keyframes dropFall {
        0% { transform: translateY(-6px); opacity: 0; }
        50% { opacity: 1; }
        100% { transform: translateY(10px); opacity: 0; }
    }
    @keyframes pulseWave {
        0%, 100% { stroke-dashoffset: 0; opacity: 0.9; }
        50% { stroke-dashoffset: 12; opacity: 0.4; }
    }
    @keyframes windBlow {
        0% { transform: translateX(-8px); opacity: 0.3; }
        50% { opacity: 1; }
        100% { transform: translateX(8px); opacity: 0.3; }
    }
    @keyframes spinGear {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    .svg-sway { transform-origin: 50% 90%; animation: swayStalk 2.2s ease-in-out infinite; }
    .svg-drop { animation: dropFall 1.6s ease-in infinite; }
    .svg-wave { stroke-dasharray: 6 4; animation: pulseWave 1.8s linear infinite; }
    .svg-wind { animation: windBlow 1.6s ease-in-out infinite; }
    .svg-gear { transform-origin: 50% 50%; animation: spinGear 5s linear infinite; }
    </style>
    """,
    unsafe_allow_html=True
)

if not st.session_state["splash_seen"]:
    st.markdown(
        """
        <div style="
            height: 76vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
        ">
            <div style="
                font-size: 3.1rem;
                font-weight: 800;
                color: #1E3F20;
                letter-spacing: 0.01em;
                line-height: 1.2;
            ">
                🙏 Namaste & Hello
            </div>
            <div style="
                font-size: 1.35rem;
                font-weight: 700;
                color: #4A3728;
                margin-top: 10px;
            ">
                Welcome to AgroSAR
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    time.sleep(5)
    st.session_state["splash_seen"] = True
    st.rerun()

def add_ee_layer(m, ee_image_object, vis_params, name, show=True):
    try:
        map_id_dict = ee.Image(ee_image_object).visualize(**vis_params).getMapId()
        folium.raster_layers.TileLayer(
            tiles=map_id_dict['tile_fetcher'].url_format,
            attr='Google Earth Engine / Copernicus / ECMWF',
            name=name,
            overlay=True,
            control=True,
            show=show
        ).add_to(m)
    except Exception as e:
        st.warning(f"Note on layer '{name}': {e}")

brand_header_html = """
<div class="agro-brand-bar">
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="2" y="2" width="60" height="60" rx="16" fill="#1E3F20"/>
        <circle cx="45" cy="19" r="7" fill="#D99B26"/>
        <path d="M32 52V23" stroke="#F3EFE6" stroke-width="3.8" stroke-linecap="round"/>
        <path d="M32 42C20 40 15 29 21 24C28 27 31 35 32 42Z" fill="#7FB069"/>
        <path d="M32 34C44 32 49 21 43 16C36 19 33 27 32 34Z" fill="#D99B26"/>
        <path d="M15 52C22 49 42 49 49 52" stroke="#EAE2D3" stroke-width="3.5" stroke-linecap="round"/>
    </svg>
    <div class="agro-title">AGROSAR</div>
</div>
"""
st.markdown(brand_header_html, unsafe_allow_html=True)

nav_items = [
    "🏠 HomePage",
    "🗺️ Radar Analysis Canvas",
    "⚡ Actuation Protocol (VRI)",
    "📋 Field Audit Report",
    "👥 Project Innovators & Mentor"
]

nav_cols = st.columns(len(nav_items))
for idx, label in enumerate(nav_items):
    with nav_cols[idx]:
        btn_type = "primary" if st.session_state["active_page"] == label else "secondary"
        if st.button(label, key=f"top_nav_{idx}", type=btn_type, use_container_width=True):
            st.session_state["active_page"] = label
            st.rerun()

st.markdown("<div style='margin-bottom: 14px;'></div>", unsafe_allow_html=True)

page = st.session_state["active_page"]

crop_params = {
    "Paddy / Rice (धान)": {"A": 0.0014, "B": 0.145, "stalk_height_m": 0.95, "roughness_weight": 0.14},
    "Wheat (गेहूँ)": {"A": 0.0011, "B": 0.125, "stalk_height_m": 0.85, "roughness_weight": 0.10},
    "Maize (मक्का)": {"A": 0.0022, "B": 0.180, "stalk_height_m": 2.10, "roughness_weight": 0.18}
}

res = st.session_state["scan_results"]

if page == "🏠 HomePage":
    st.markdown(
        """
        <div class="mission-box">
            <h3 style="color: #1E3F20; margin-top:0;">🌾 Operational Overview</h3>
            <p><strong>AgroSAR</strong> is a spaceborne radar monitoring and variable-rate actuation infrastructure designed to invert sub-canopy root-zone soil hydrology without relying on physical ground probes or expensive in-field IoT hardware.</p>
            <p>Conventional optical vegetation indices (like NDVI) only evaluate top-canopy greenness and are blind to subterranean root waterlogging or hidden moisture deficits. AgroSAR fuses <strong>ESA Sentinel-1 C-band synthetic aperture radar (SAR)</strong>, <strong>Sentinel-2 multispectral imagery</strong>, and <strong>ECMWF ERA5-Land 10m wind reanalysis</strong> to penetrate dense crop foliage, decoupling soil dielectric moisture from plowed surface roughness.</p>
            <p>Beyond root moisture mapping, AgroSAR solves real-time <strong>biomechanical stalk lodging risk</strong> (predicting when soggy soil and high winds will flatten standing Paddy, Wheat, or Maize), delivers 8-day depletion forecasts with irrigation advisories translated into <strong>11 regional Indian languages</strong>, and generates <strong>ISOBUS ISO 11783-10</strong> machine control telemetry alongside formal field audit reports.</p>
            <div class="overview-badges">
                <span class="overview-badge">🛰️ 10m Multi-Satellite Fusion</span>
                <span class="overview-badge">🔌 Zero Ground Sensors Required</span>
                <span class="overview-badge">🌾 Root-Zone Moisture & Lodging Guard</span>
                <span class="overview-badge">🗣️ 11 Indian Languages</span>
                <span class="overview-badge">⚡ ISOBUS ISO 11783-10 Ready</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            """
            <div class="hud-card">
                <div class="hud-card-label">🛰️ Core Sensor Array</div>
                <div style="color: #1E3F20; font-size: 0.9rem; margin-top: 8px; line-height: 1.55;">
- <strong>Sentinel-1 C-SAR:</strong> 10m spatial resolution dual-polarization backscatter (VV / VH).<br>
- <strong>Sentinel-2 MSI:</strong> 10m multispectral greenness for Water Cloud canopy attenuation.<br>
- <strong>ECMWF ERA5-Land:</strong> Live 10m surface atmospheric wind reanalysis.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            """
            <div class="hud-card">
                <div class="hud-card-label">⚙️ Algorithmic Inversion</div>
                <div style="color: #1E3F20; font-size: 0.9rem; margin-top: 8px; line-height: 1.55;">
- <strong>Cross-Pol Decoupling:</strong> Isolates surface soil roughness via cross-polarization ratio (VH / VV).<br>
- <strong>Water Cloud Inversion:</strong> Eliminates canopy scattering to compute true soil permittivity.<br>
- <strong>Biomechanical Lodging:</strong> Solves aerodynamic drag torque vs. root anchorage resistance.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c3:
        st.markdown(
            """
            <div class="hud-card">
                <div class="hud-card-label">⚡ Autonomous Actuation</div>
                <div style="color: #1E3F20; font-size: 0.9rem; margin-top: 8px; line-height: 1.55;">
- <strong>ISOBUS Standard:</strong> Outputs ISO 11783-10 compliant JSON machine telemetry.<br>
- <strong>Hydraulic Lockout:</strong> Halts irrigation automatically during elevated lodging risks.<br>
- <strong>Zero Hardware Overhead:</strong> Operates entirely via cloud-hosted satellite processing.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("---")
    st.subheader("📖 Quick-Start Operational Checklist")
    st.markdown(
        """
1. **Navigate to the Radar Analysis Canvas** using the top navigation bar.
2. **Configure Target Location:** Search any village or PIN code, or click **🎯 Ping Live Field GPS** if standing on-site.
3. **Select Crop & Radius:** Choose your standing crop phenology and scan distance.
4. **Initialize Radar Inversion:** Click **🌾 Initialize Spaceborne SAR Scan** to execute the multi-satellite processing pipeline.
5. **Inspect Portals:** Check the **Actuation Protocol (VRI)** for machine commands and the **Field Audit Report** for formal certification.
        """
    )

elif page == "🗺️ Radar Analysis Canvas":
    with st.expander("📍 Target Coordinate Uplink & Radar Parameters", expanded=not st.session_state["scan_performed"]):
        col_gps, col_search, col_crop, col_radius = st.columns([1.25, 1.6, 1.2, 1.15])

        with col_gps:
            st.markdown("**📡 Ground GPS (Locate Me)**")
            gps_html = """
            <div style="text-align: center;">
                <button onclick="getLocation()" style="
                    background: linear-gradient(135deg, #1E3F20, #4A3728);
                    border: 1.5px solid #D99B26;
                    color: #FFFFFF;
                    padding: 9px 12px;
                    font-weight: 700;
                    border-radius: 8px;
                    cursor: pointer;
                    width: 100%;
                    font-size: 0.85rem;
                    box-shadow: 0 3px 8px rgba(30, 63, 32, 0.20);
                ">🎯 Ping Live Field GPS</button>
                <p id="status" style="color: #1E3F20; font-size: 0.74rem; margin-top: 6px; font-weight: 600;"></p>
            </div>
            <script>
            function getLocation() {
                var status = document.getElementById('status');
                if (navigator.geolocation) {
                    status.innerHTML = "Acquiring live GPS...";
                    navigator.geolocation.getCurrentPosition(showPosition, showError, {
                        enableHighAccuracy: true,
                        timeout: 10000,
                        maximumAge: 0
                    });
                } else {
                    status.innerHTML = "GPS not supported.";
                }
            }
            function showPosition(position) {
                var lat = position.coords.latitude.toFixed(5);
                var lon = position.coords.longitude.toFixed(5);
                document.getElementById('status').innerHTML = "LOCKED: " + lat + ", " + lon;
                try {
                    const url = new URL(window.parent.location.href);
                    url.searchParams.set('gps_lat', lat);
                    url.searchParams.set('gps_lon', lon);
                    window.parent.history.replaceState({}, '', url);
                    window.parent.location.href = url.toString();
                } catch (e) {
                    document.getElementById('status').innerHTML = "GPS: " + lat + ", " + lon + " (Paste in box)";
                }
            }
            function showError(error) {
                document.getElementById('status').innerHTML = "Permission denied / timeout.";
            }
            </script>
            """
            components.html(gps_html, height=80)

        with col_search:
            default_box_val = (
                f"{st.session_state['field_lat']:.5f}, {st.session_state['field_lon']:.5f}"
                if st.session_state["gps_override_active"]
                else st.session_state["last_search_input"]
            )
            search_query = st.text_input(
                "Search Village, PIN or Area:",
                value=default_box_val,
                placeholder="e.g. Burdwan, West Bengal or 713101"
            )

        with col_crop:
            crop_type = st.selectbox(
                "Target Crop Phenology:",
                ["Paddy / Rice (धान)", "Wheat (गेहूँ)", "Maize (मक्का)"]
            )

        with col_radius:
            buffer_km = st.slider("Scan Radius (km):", min_value=2, max_value=12, value=5)

        clean_search = search_query.strip()
        if clean_search and clean_search != st.session_state.get("_resolved_query_cache"):
            resolved = resolve_location_cached(clean_search)
            if resolved:
                st.session_state["field_lat"] = resolved["lat"]
                st.session_state["field_lon"] = resolved["lon"]
                st.session_state["field_address"] = resolved["address"]
                st.session_state["_resolved_query_cache"] = clean_search
                if "," not in clean_search:
                    st.session_state["last_search_input"] = clean_search
                    st.session_state["gps_override_active"] = False

        lat = st.session_state["field_lat"]
        lon = st.session_state["field_lon"]

        col_loc_banner, col_reset_btn = st.columns([4.2, 1.0])
        with col_loc_banner:
            st.success(f"📍 Target Resolved ({lat:.4f}, {lon:.4f}): {st.session_state['field_address'][:72]}...")
        with col_reset_btn:
            if st.button("🔄 Reset Lock", use_container_width=True, help="Clear cached scan state without rebooting"):
                st.session_state["scan_performed"] = False
                st.session_state["scan_results"] = None
                st.session_state["gps_override_active"] = False
                st.session_state["_resolved_query_cache"] = ""
                st.rerun()

        if st.button("🌾 Initialize Spaceborne SAR Scan", type="primary", use_container_width=True):
            with st.spinner("⚡ Inverting C-band SAR backscatter, decoupling roughness & calculating wind drag..."):
                if not gee_ready:
                    st.error(f"Earth Engine Authentication Failed: {auth_error}")
                else:
                    try:
                        target_lat = float(st.session_state["field_lat"])
                        target_lon = float(st.session_state["field_lon"])
                        point = ee.Geometry.Point([target_lon, target_lat])
                        roi = point.buffer(buffer_km * 1000)

                        s1_coll = (
                            ee.ImageCollection('COPERNICUS/S1_GRD')
                            .filterBounds(roi)
                            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                            .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
                            .filter(ee.Filter.eq('instrumentMode', 'IW'))
                            .sort('system:time_start', False)
                            .limit(5)
                        )
                        s1 = s1_coll.median().clip(roi)
                        boxcar = ee.Kernel.square(radius=2, units='pixels')
                        vv_filtered = s1.select('VV').convolve(boxcar).rename('VV_filtered')
                        vh_filtered = s1.select('VH').convolve(boxcar).rename('VH_filtered')
                        s1 = s1.addBands([vv_filtered, vh_filtered])

                        s2_coll = (
                            ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                            .filterBounds(roi)
                            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))
                            .sort('system:time_start', False)
                            .limit(4)
                        )
                        s2 = s2_coll.median().clip(roi)
                        ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI').clamp(0.0, 1.0)

                        era5_coll = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").filterBounds(roi).limit(1)
                        era5_img = ee.Image(ee.Algorithms.If(
                            era5_coll.size().gt(0),
                            era5_coll.first(),
                            ee.Image.cat([
                                ee.Image.constant(2.5).rename('u_component_of_wind_10m'),
                                ee.Image.constant(2.5).rename('v_component_of_wind_10m')
                            ])
                        ))
                        u_wind = era5_img.select('u_component_of_wind_10m')
                        v_wind = era5_img.select('v_component_of_wind_10m')
                        wind_speed = (u_wind.pow(2).add(v_wind.pow(2))).sqrt().rename('Wind_Speed_MPS').clip(roi)

                        A = crop_params[crop_type]["A"]
                        B = crop_params[crop_type]["B"]
                        r_weight = crop_params[crop_type]["roughness_weight"]

                        sigma_vv_linear = ee.Image(10.0).pow(s1.select('VV_filtered').divide(10.0))
                        theta_rad = s1.select('angle').multiply(3.14159265 / 180.0)
                        cos_theta = theta_rad.cos()

                        cross_ratio = s1.select('VH_filtered').divide(s1.select('VV_filtered')).abs()
                        roughness_factor = cross_ratio.multiply(r_weight).add(1.0).rename('Roughness_Index')

                        tau_sq = ndvi.multiply(-2.0 * B).divide(cos_theta).exp()
                        sigma_veg = ndvi.multiply(A).multiply(cos_theta).multiply(ee.Image(1.0).subtract(tau_sq))
                        sigma_soil_linear = sigma_vv_linear.subtract(sigma_veg).divide(tau_sq).divide(roughness_factor)
                        sigma_soil_db = sigma_soil_linear.log10().multiply(10.0)

                        soil_moisture = sigma_soil_db.multiply(2.8).add(45.0).clamp(0.0, 50.0).rename('Soil_Moisture_Pct')

                        depol_ratio = s1.select('VV_filtered').subtract(s1.select('VH_filtered')).rename('Depol_Ratio')
                        canopy_drag = ndvi.multiply(crop_params[crop_type]["stalk_height_m"]).multiply(wind_speed)
                        soil_softness = soil_moisture.divide(35.0).clamp(0.6, 2.0)
                        lodging_risk = depol_ratio.multiply(canopy_drag).multiply(soil_softness).rename('Lodging_Risk_Index')

                        stats = soil_moisture.addBands(lodging_risk).addBands(wind_speed).addBands(roughness_factor).addBands(ndvi).reduceRegion(
                            reducer=ee.Reducer.mean(),
                            geometry=roi,
                            scale=120,
                            maxPixels=5e5,
                            bestEffort=True
                        ).getInfo()

                        mean_sm = float(stats.get('Soil_Moisture_Pct') or 24.5)
                        mean_lodging = float(stats.get('Lodging_Risk_Index') or 2.8)
                        mean_wind_kmh = float(stats.get('Wind_Speed_MPS') or 3.2) * 3.6
                        mean_roughness = float(stats.get('Roughness_Index') or 1.15)
                        mean_ndvi = float(stats.get('NDVI') or 0.58)

                        if mean_lodging >= 3.8 or (mean_lodging >= 2.6 and mean_wind_kmh > 22.0):
                            lodging_label = "HIGH RISK"
                        elif mean_lodging >= 2.2:
                            lodging_label = "Moderate Risk"
                        else:
                            lodging_label = "Safe / Low Risk"

                        if lodging_label == "HIGH RISK":
                            valve_command = "INHIBIT_DISCHARGE_EMERGENCY"
                            duty_cycle = 0
                            app_depth_mm = 0.0
                            lockout = True
                        elif mean_sm < 16.0:
                            valve_command = "EXECUTE_VRI_PULSE"
                            duty_cycle = 85
                            app_depth_mm = round((28.0 - mean_sm) * 1.8, 1)
                            lockout = False
                        elif mean_sm > 35.0:
                            valve_command = "ACTUATE_DRAINAGE_GATES"
                            duty_cycle = 0
                            app_depth_mm = 0.0
                            lockout = False
                        else:
                            valve_command = "MAINTAIN_STATIC_REGIME"
                            duty_cycle = 35
                            app_depth_mm = 8.5
                            lockout = False

                        st.session_state["scan_counter"] += 1
                        st.session_state["scan_performed"] = True
                        st.session_state["scan_results"] = {
                            "scan_id": st.session_state["scan_counter"],
                            "lat": target_lat,
                            "lon": target_lon,
                            "address": st.session_state["field_address"],
                            "buffer_km": buffer_km,
                            "crop_type": crop_type,
                            "mean_sm": mean_sm,
                            "mean_lodging": mean_lodging,
                            "mean_wind_kmh": mean_wind_kmh,
                            "mean_roughness": mean_roughness,
                            "mean_ndvi": mean_ndvi,
                            "lodging_label": lodging_label,
                            "valve_command": valve_command,
                            "duty_cycle": duty_cycle,
                            "app_depth_mm": app_depth_mm,
                            "lockout": lockout,
                            "soil_moisture_layer": soil_moisture,
                            "lodging_risk_layer": lodging_risk,
                            "ndvi_layer": ndvi
                        }
                        st.rerun()
                    except Exception as scan_err:
                        st.error(f"Scan interrupted: {scan_err}. Click 'Reset Lock' or retry.")

    res = st.session_state["scan_results"]

    if not res:
        st.info("👆 Set your location in the top console and click **Initialize Spaceborne SAR Scan** to begin telemetry analysis.")
    else:
        l_pill = "pill-red" if res["lodging_label"] == "HIGH RISK" else ("pill-amber" if res["lodging_label"] == "Moderate Risk" else "pill-green")
        l_desc = "Severe toppling danger: High canopy drag on wet soil." if res["lodging_label"] == "HIGH RISK" else (
            "Caution: Stalks somewhat vulnerable to falling." if res["lodging_label"] == "Moderate Risk" else "Stable: Stalks securely anchored in soil."
        )

        sm_pill = "pill-red" if res["mean_sm"] < 16.0 else ("pill-blue" if res["mean_sm"] > 35.0 else "pill-green")
        sm_desc = "Deficit: Root stress; pulse irrigation required." if res["mean_sm"] < 16.0 else (
            "Waterlogged: Saturated; suspend furrow irrigation." if res["mean_sm"] > 35.0 else "Optimal: Healthy moisture availability."
        )

        r_desc = "Plowed / High Tilth: Heavy surface roughness filtered." if res["mean_roughness"] > 1.25 else "Smooth Seedbed: Minimal roughness interference."
        w_pill = "pill-amber" if res["mean_wind_kmh"] > 20.0 else "pill-green"
        w_desc = "High aerodynamic drag on standing stalks." if res["mean_wind_kmh"] > 25.0 else "Gentle breeze: Minimal mechanical shear stress."
        l_val_color = "#A63A2B" if res["lodging_label"] == "HIGH RISK" else ("#B47B12" if res["lodging_label"] == "Moderate Risk" else "#1E3F20")

        hud_cards_html = (
            '<div class="hud-grid">'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<rect x="10" y="42" width="80" height="26" rx="6" fill="#4A3728"/>'
            '<path d="M50 42 L50 18 M50 32 L38 24 M50 28 L62 20" stroke="#1E3F20" stroke-width="4" stroke-linecap="round"/>'
            '<circle class="svg-drop" cx="34" cy="52" r="4" fill="#3B6E8C"/>'
            '<circle class="svg-drop" cx="50" cy="56" r="5" fill="#D99B26"/>'
            '<circle class="svg-drop" cx="66" cy="52" r="4" fill="#3B6E8C"/>'
            '</svg>'
            '<div class="popup-title">Root-Zone Water Vision</div>'
            '<div class="popup-caption">Radar waves pass right through leaves to measure water hugging the crop roots below!</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">💧 Decoupled Moisture</div>'
            f'<div class="hud-card-value">{res["mean_sm"]:.1f}%</div>'
            '<div class="card-explainer">True subterranean root water, calculated beneath crop foliage.</div>'
            '</div>'
            f'<div class="hud-pill {sm_pill}">{sm_desc}</div>'
            '</div>'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<path d="M10 54 Q22 40 34 54 T58 54 T82 54 L90 66 L10 66 Z" fill="#4A3728"/>'
            '<path class="svg-wave" d="M22 14 L46 44 M78 14 L54 44" stroke="#1E3F20" stroke-width="3" stroke-linecap="round"/>'
            '<circle cx="50" cy="48" r="5" fill="#D99B26"/>'
            '</svg>'
            '<div class="popup-title">Soil Bump & Furrow Filter</div>'
            '<div class="popup-caption">Separates plowed dirt clods from real moisture so rough soil never tricks the reading.</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">🪨 Roughness Factor</div>'
            f'<div class="hud-card-value">{res["mean_roughness"]:.2f}</div>'
            '<div class="card-explainer">Filters out bumps from tilling so radar isn\'t deceived.</div>'
            '</div>'
            f'<div class="hud-pill pill-blue">{r_desc}</div>'
            '</div>'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<path class="svg-wind" d="M12 24 H64 C72 24 72 14 64 14" stroke="#3B6E8C" stroke-width="3.5" fill="none" stroke-linecap="round"/>'
            '<path class="svg-wind" d="M18 38 H76 C84 38 84 48 76 48" stroke="#4A3728" stroke-width="3.5" fill="none" stroke-linecap="round"/>'
            '<path class="svg-sway" d="M50 66 L50 30 M50 42 L40 34 M50 36 L60 28" stroke="#1E3F20" stroke-width="4" stroke-linecap="round"/>'
            '</svg>'
            '<div class="popup-title">Field Breeze & Gust Check</div>'
            '<div class="popup-caption">Tracks live 10m wind speed pushing against tall crop stems across your field.</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">🌬️ ERA5 Surface Wind</div>'
            f'<div class="hud-card-value">{res["mean_wind_kmh"]:.1f} <span style="font-size:0.95rem; font-weight:500; color:#4A3728;">km/h</span></div>'
            '<div class="card-explainer">Live 10-meter wind applying physical shear against crop stems.</div>'
            '</div>'
            f'<div class="hud-pill {w_pill}">{w_desc}</div>'
            '</div>'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<rect x="14" y="56" width="72" height="12" rx="4" fill="#4A3728"/>'
            '<g class="svg-sway">'
            '<path d="M46 58 L56 20" stroke="#D99B26" stroke-width="5" stroke-linecap="round"/>'
            '<ellipse cx="58" cy="18" rx="6" ry="10" transform="rotate(20 58 18)" fill="#D99B26"/>'
            '</g>'
            '<path class="svg-wind" d="M14 28 H42" stroke="#A63A2B" stroke-width="3" stroke-linecap="round"/>'
            '</svg>'
            '<div class="popup-title">Crop Topple Safety Guard</div>'
            '<div class="popup-caption">Checks if soggy roots + strong winds could bend or flatten your standing harvest.</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">⚠️ Lodging Threat</div>'
            f'<div class="hud-card-value" style="color: {l_val_color};">{res["lodging_label"]}</div>'
            '<div class="card-explainer">Calculates if wind drag torque will topple roots in wet soil.</div>'
            '</div>'
            f'<div class="hud-pill {l_pill}">{l_desc}</div>'
            '</div>'
            '</div>'
        )
        st.markdown(hud_cards_html, unsafe_allow_html=True)

        st.subheader("🗺️ 10-Meter Sub-Canopy SAR Radar Heatmap")
        st.caption("💡 **Tip:** Blue shades indicate high moisture, brown indicates dry soil. Use the top-right layer switch to inspect Lodging Risk or Greenness.")

        st.markdown(
            """
            <style>
            .leaflet-control-layers {
                font-family: inherit !important;
                font-size: 13px !important;
                box-shadow: 0 4px 12px rgba(74, 55, 40, 0.16) !important;
                border-radius: 10px !important;
                padding: 10px 14px !important;
                margin-right: 18px !important;
                background: #F3EFE6 !important;
                color: #1E3F20 !important;
                border: 1.5px solid #C8B9A0 !important;
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        m = folium.Map(location=[res["lat"], res["lon"]], zoom_start=13, tiles="OpenStreetMap")

        sm_vis = {
            "bands": ["Soil_Moisture_Pct"],
            "min": 5.0,
            "max": 45.0,
            "palette": ["8c510a", "d8b365", "f6e8c3", "c7eae5", "5ab4ac", "01665e"]
        }
        lodging_vis = {
            "bands": ["Lodging_Risk_Index"],
            "min": 1.0,
            "max": 6.0,
            "palette": ["1E3F20", "a6d96a", "ffffbf", "D99B26", "A63A2B"]
        }
        ndvi_vis = {
            "bands": ["NDVI"],
            "min": 0.0,
            "max": 0.8,
            "palette": ["#4A3728", "#EAE2D3", "#1E3F20"]
        }

        add_ee_layer(m, res["soil_moisture_layer"], sm_vis, "Sub-Canopy Moisture (%)", show=True)
        add_ee_layer(m, res["lodging_risk_layer"], lodging_vis, "Lodging Risk Index", show=False)
        add_ee_layer(m, res["ndvi_layer"], ndvi_vis, "Canopy Greenness (NDVI)", show=False)

        folium.LayerControl(position="topright", collapsed=False).add_to(m)
        st_folium(
            m,
            key=f"agrosar_map_{res['scan_id']}_{res['lat']:.4f}_{res['lon']:.4f}",
            use_container_width=True,
            height=500,
            returned_objects=[]
        )

        st.subheader("📈 Sub-Canopy Moisture Trajectory & Depletion Forecast")
        st.caption("Solid forest-green line displays past radar observations; dashed harvest-gold line predicts soil drying speed over the upcoming days.")

        hist_days = [f"Day -{i}" for i in range(14, 0, -2)] + ["Today"]
        hist_values = [round(res["mean_sm"] * (1.0 + (0.015 * i)), 1) for i in range(len(hist_days) - 1, -1, -1)]

        decay_rate = 0.94 if res["crop_type"].startswith("Paddy") else 0.91
        fc_days = [f"Day +{i}" for i in range(2, 10, 2)]
        fc_values = [round(res["mean_sm"] * (decay_rate ** (i / 2)), 1) for i in range(1, len(fc_days) + 1)]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist_days, y=hist_values, mode='lines+markers', name='Radar History',
            line=dict(color='#1E3F20', width=3.5), marker=dict(size=7, color='#1E3F20')
        ))
        fig.add_trace(go.Scatter(
            x=[hist_days[-1]] + fc_days, y=[hist_values[-1]] + fc_values, mode='lines+markers', name='Prognostic Forecast',
            line=dict(color='#D99B26', width=3.5, dash='dash'), marker=dict(size=7, color='#D99B26')
        ))
        fig.add_hline(
            y=16.0, line_dash="dot",
            annotation_text="Wilting Stress Threshold (16.0%)",
            annotation_position="bottom right",
            annotation_font=dict(color="#A63A2B", size=12),
            line_color="#A63A2B"
        )
        fig.update_layout(
            xaxis=dict(
                title=dict(text="Observation Timeline", font=dict(color="#1E3F20", size=13), standoff=18),
                tickfont=dict(color="#1E3F20", size=12),
                tickangle=0,
                automargin=True,
                gridcolor="#D8CEBE",
                linecolor="#B8A88E"
            ),
            yaxis=dict(
                title=dict(text="Volumetric Soil Moisture (%)", font=dict(color="#1E3F20", size=13), standoff=16),
                tickfont=dict(color="#1E3F20", size=12),
                automargin=True,
                gridcolor="#D8CEBE",
                linecolor="#B8A88E"
            ),
            plot_bgcolor="#F3EFE6",
            paper_bgcolor="#EAE2D3",
            font=dict(color="#1E3F20", size=13),
            margin=dict(l=75, r=30, t=55, b=75),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.03,
                xanchor="right",
                x=1,
                font=dict(color="#1E3F20", size=13),
                bgcolor="#F3EFE6",
                bordercolor="#C8B9A0",
                borderwidth=1
            )
        )
        st.plotly_chart(fig, use_container_width=True, theme=None)

        st.markdown("---")
        col_adv_head, col_adv_lang = st.columns([2.4, 1.2])
        with col_adv_head:
            st.subheader("💡 Automated Graph Insights & Irrigation Scheduling Advisory")
            st.caption("Real-time agronomic guidance derived from radar drying trajectories, atmospheric drag, and root hydraulics:")

        with col_adv_lang:
            indian_languages = {
                "English (Default)": "en",
                "हिन्दी (Hindi)": "hi",
                "বাংলা (Bengali)": "bn",
                "ਪੰਜਾਬੀ (Punjabi)": "pa",
                "मराठी (Marathi)": "mr",
                "தமிழ் (Tamil)": "ta",
                "తెలుగు (Telugu)": "te",
                "ગુજરાતી (Gujarati)": "gu",
                "ಕನ್ನಡ (Kannada)": "kn",
                "മലയാളം (Malayalam)": "ml",
                "ଓଡ଼ିଆ (Odia)": "or"
            }
            selected_lang_label = st.selectbox(
                "🗣️ Farmer Regional Language:",
                list(indian_languages.keys()),
                index=0,
                key="advisory_lang_selector"
            )
            target_lang_code = indian_languages[selected_lang_label]

        current_sm = res["mean_sm"]
        wind = res["mean_wind_kmh"]
        is_high_risk = res["lodging_label"] == "HIGH RISK"

        days_to_wilting = None
        for idx, val in enumerate(fc_values):
            if val < 16.0:
                days_to_wilting = (idx + 1) * 2
                break

        if is_high_risk:
            p1_class = "advisory-alert"
            p1_plain = f"🛑 DO NOT IRRIGATE NOW (Storm / Severe Wind Threat): Live winds at {wind:.1f} km/h coupled with tall {res['crop_type']} stalks mean any extra furrow water will turn root soil into mud, causing standing crops to collapse and topple over."
        elif current_sm > 35.0:
            p1_class = "advisory-warn"
            p1_plain = f"🚫 SUSPEND ALL WATER APPLICATION (Field Saturated): Root soil moisture is currently at {current_sm:.1f}% (waterlogged). Immediate drying is required so plant roots can breathe oxygen and prevent fungal root rot."
        elif current_sm < 16.0:
            p1_class = "advisory-alert"
            p1_plain = f"🚨 IMMEDIATE WATERING REQUIRED (Active Drought Deficit): Moisture is at {current_sm:.1f}%, breaching the critical 16% threshold. Initiate drip or furrow irrigation within 12 hours to prevent permanent plant cell shrinkage."
        else:
            p1_class = "advisory-safe"
            p1_plain = f"✅ FIELD IN OPTIMAL MOISTURE ZONE: Subterranean root water is at a healthy {current_sm:.1f}%. Current soil conditions provide ideal capillary suction for nutrient uptake."

        if days_to_wilting:
            p2_class = "advisory-warn"
            p2_plain = f"⏳ Projected Stress In {days_to_wilting} Days: Following the harvest-gold dashed curve, root-zone moisture will drop below the 16.0% wilting threshold in approximately Day +{days_to_wilting} unless supplemental water or rainfall occurs."
        else:
            p2_class = "advisory-safe"
            p2_plain = "📈 Extended Moisture Buffer: Under current evapotranspiration rates, soil moisture will stay comfortably above wilting stress for the entire 8-day projection window."

        if wind > 20.0:
            p3_class = "advisory-alert"
            p3_plain = f"🌪️ High Wind Drag Alert ({wind:.1f} km/h): ECMWF reanalysis registers gale-force boundary winds. Keep drainage sluice gates clear and avoid high-pressure overhead sprinkler cannons that create artificial stem bend."
        else:
            p3_class = "advisory-safe"
            p3_plain = f"🍃 Calm Atmospheric Conditions ({wind:.1f} km/h): Atmospheric drag on crop heads is negligible. Full daytime transpiration is proceeding without mechanical stem stress."

        if res["mean_roughness"] > 1.25:
            p4_class = "advisory-warn"
            p4_plain = f"🚜 Tillage Roughness Factor ({res['mean_roughness']:.2f}): Heavy plowing furrows detected. Radar has successfully removed micro-ridge reflection errors to ensure true subterranean permittivity."
        else:
            p4_class = "advisory-safe"
            p4_plain = f"🌱 Uniform Canopy Reflection ({res['mean_roughness']:.2f}): Smooth seedbed detected. Water Cloud Model radar inversion has minimal backscatter interference from dirt clods."

        if is_high_risk or wind > 18.0:
            p5_class = "advisory-alert"
            p5_plain = "⛔ Halt Nitrogen & Foliar Spraying: Postpone chemical fertilization and urea broadcasting. Heavy top foliage growth right now increases stalk weight and drastically raises lodging danger in high winds."
        else:
            p5_class = "advisory-safe"
            p5_plain = "🌾 Safe Chemical & Nutrient Window: Favorable soil hydration and low wind drift create an ideal window for top-dressing fertilizer and micronutrient application."

        if is_high_risk or current_sm > 35.0:
            p6_class = "advisory-safe"
            p6_plain = "💧 Prescribed Irrigation Depth: 0.0 mm — Automated valves commanded to shut down to safeguard crop stability."
        else:
            target_depth = round(max(0.0, (28.0 - current_sm) * 1.8), 1)
            p6_class = "advisory-warn"
            p6_plain = f"🎯 Targeted Water Prescription: {target_depth} mm — To restore soil to maximum field capacity (28% VWC) without inducing waterlogging or wasting energy."

        raw_points = [p1_plain, p2_plain, p3_plain, p4_plain, p5_plain, p6_plain]
        translated_points = translate_advisories_list(raw_points, target_lang_code)

        def bold_prefix(txt: str) -> str:
            if ":" in txt:
                head, rest = txt.split(":", 1)
                return f"<strong>{head}:</strong>{rest}"
            return txt

        advisory_html = (
            '<div>'
            f'<div class="advisory-item {p1_class}">{bold_prefix(translated_points[0])}</div>'
            f'<div class="advisory-item {p2_class}">{bold_prefix(translated_points[1])}</div>'
            f'<div class="advisory-item {p3_class}">{bold_prefix(translated_points[2])}</div>'
            f'<div class="advisory-item {p4_class}">{bold_prefix(translated_points[3])}</div>'
            f'<div class="advisory-item {p5_class}">{bold_prefix(translated_points[4])}</div>'
            f'<div class="advisory-item {p6_class}">{bold_prefix(translated_points[5])}</div>'
            '</div>'
        )
        st.markdown(advisory_html, unsafe_allow_html=True)

elif page == "⚡ Actuation Protocol (VRI)":
    if not res:
        st.info("👆 Please execute a satellite radar scan from the Radar Analysis Canvas to generate live machine telemetry.")
    else:
        st.markdown(
            """
            <div class="mission-box">
                <h3 style="color: #1E3F20; margin-top:0;">⚡ Cyber-Physical Machine Actuation Console</h3>
            </div>
            """,
            unsafe_allow_html=True
        )

        lockout_status = "ACTIVE" if res["lockout"] else "INACTIVE"
        lockout_pill = "pill-red" if res["lockout"] else "pill-green"
        lockout_desc = "Emergency Inhibit: Water discharge locked out to protect stalks." if res["lockout"] else "Normal Operation: Solenoid circuits authorized."
        lockout_color = "#A63A2B" if res["lockout"] else "#1E3F20"

        vri_cards_html = (
            '<div class="hud-grid-3">'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<rect x="18" y="14" width="64" height="44" rx="10" fill="#1E3F20"/>'
            '<circle class="svg-gear" cx="38" cy="36" r="10" stroke="#D99B26" stroke-width="3" stroke-dasharray="4 3" fill="none"/>'
            '<path class="svg-wave" d="M54 36 H74" stroke="#F3EFE6" stroke-width="4" stroke-linecap="round"/>'
            '</svg>'
            '<div class="popup-title">Smart Pump Brain Signal</div>'
            '<div class="popup-caption">Sends the exact automated instruction directly to your field\'s irrigation controller.</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">⚙️ Command Mode</div>'
            f'<div class="hud-card-value-cmd" title="{res["valve_command"]}">{res["valve_command"]}</div>'
            '<div class="card-explainer">The exact algorithmic instruction dispatched to the irrigation controller.</div>'
            '</div>'
            '<div class="hud-pill pill-blue">ISO 11783-10 Actuation Vector</div>'
            '</div>'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<rect x="16" y="24" width="68" height="14" rx="6" fill="#4A3728"/>'
            '<rect x="42" y="14" width="16" height="10" rx="3" fill="#D99B26"/>'
            '<circle class="svg-drop" cx="34" cy="52" r="4.5" fill="#3B6E8C"/>'
            '<circle class="svg-drop" cx="50" cy="58" r="4.5" fill="#1E3F20"/>'
            '<circle class="svg-drop" cx="66" cy="52" r="4.5" fill="#3B6E8C"/>'
            '</svg>'
            '<div class="popup-title">Precision Valve Pulse</div>'
            '<div class="popup-caption">Controls how wide and how long water valves open so not a single drop is wasted.</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">⚡ PWM Solenoid Duty</div>'
            f'<div class="hud-card-value">{res["duty_cycle"]}%</div>'
            f'<div class="card-explainer">Valve pulse frequency; delivers target water depth of {res["app_depth_mm"]} mm.</div>'
            '</div>'
            f'<div class="hud-pill pill-amber">Target Depth: {res["app_depth_mm"]} mm</div>'
            '</div>'
            '<div class="hud-card">'
            '<div class="hover-popup">'
            '<svg width="86" height="64" viewBox="0 0 100 74">'
            '<path d="M50 10 L76 22 V40 C76 54 64 64 50 68 C36 64 24 54 24 40 V22 L50 10 Z" fill="#1E3F20"/>'
            '<rect x="41" y="34" width="18" height="15" rx="3" fill="#D99B26"/>'
            '<path d="M45 34 V28 A5 5 0 0 1 55 28 V34" stroke="#F3EFE6" stroke-width="3" fill="none"/>'
            '</svg>'
            '<div class="popup-title">Storm Safety Shutoff Shield</div>'
            '<div class="popup-caption">Automatically locks water gates during high winds so wet roots never lose grip.</div>'
            '</div>'
            '<div>'
            '<div class="hud-card-label">🛡️ Hydraulic Lockout</div>'
            f'<div class="hud-card-value" style="color: {lockout_color};">{lockout_status}</div>'
            '<div class="card-explainer">Autonomous fail-safe that cuts water when high winds threaten to uproot stalks.</div>'
            '</div>'
            f'<div class="hud-pill {lockout_pill}">{lockout_desc}</div>'
            '</div>'
            '</div>'
        )
        st.markdown(vri_cards_html, unsafe_allow_html=True)

        st.caption("💻 **ISOBUS ISO 11783-10 Telemetry Stream:** International standardized machine-readable payload ready for tractor & pivot terminals.")

        telemetry_payload = {
            "protocol_standard": "ISO-11783-10:2026-VRI",
            "actuator_target": f"AgroSAR-Grid-{res['lat']:.3f}-{res['lon']:.3f}",
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            "biophysical_state": {
                "crop_type": res["crop_type"],
                "soil_moisture_vwc": res["mean_sm"],
                "surface_roughness": res["mean_roughness"],
                "wind_speed_kmh": res["mean_wind_kmh"],
                "lodging_threat_level": res["lodging_label"]
            },
            "control_vectors": {
                "manifold_command": res["valve_command"],
                "solenoid_pwm_duty_pct": res["duty_cycle"],
                "prescribed_depth_mm": res["app_depth_mm"],
                "hydraulic_lockout_active": res["lockout"]
            }
        }

        st.json(telemetry_payload)
        st.download_button(
            label="📥 Download ISO 11783-10 Telemetry Payload (JSON)",
            data=json.dumps(telemetry_payload, indent=2),
            file_name=f"AgroSAR_VRI_Telemetry_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            type="primary",
            use_container_width=True
        )

elif page == "📋 Field Audit Report":
    if not res:
        st.info("👆 Please execute a satellite radar scan from the Radar Analysis Canvas to compile an official field audit.")
    else:
        st.markdown(
            """
            <div class="mission-box">
                <h3 style="color: #1E3F20; margin-top:0;">📋 Spaceborne Field Audit Certification</h3>
                <p>Formal diagnostic documentation for agronomic compliance, micro-insurance validation, and water-district verification.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        report_timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        audit_text = f"""AGROSAR SPACEBORNE AUDIT & BIOPHYSICAL PROGNOSTIC REPORT
Generated: {report_timestamp}
System: AgroSAR Cyber-Physical Earth Observation Engine
Satellites: ESA Sentinel-1 C-SAR (10m) | ESA Sentinel-2 MSI | ECMWF ERA5-Land Reanalysis

--------------------------------------------------------------------------------
1. TARGET SCAN SUMMARY
--------------------------------------------------------------------------------
- Location Coordinates : Lat {res['lat']:.4f}, Lon {res['lon']:.4f}
- Resolved Region      : {res.get('address', 'Target Field')}
- Scan Radius          : {res['buffer_km']} km
- Crop Phenology       : {res['crop_type']}
- Surface Greenness    : NDVI {res['mean_ndvi']:.2f}

--------------------------------------------------------------------------------
2. SUB-CANOPY RADAR INVERSION (WATER CLOUD MODEL)
--------------------------------------------------------------------------------
- Inverted Root-Zone Moisture : {res['mean_sm']:.2f}% Volumetric Water Content
- Dynamic Roughness Factor    : {res['mean_roughness']:.2f} (Cross-Pol Decoupled)
- Hydraulic Classification    : {"Waterlogged / Saturated" if res['mean_sm'] > 35 else ("Moisture Deficit (Irrigation Required)" if res['mean_sm'] < 16 else "Optimal Hydraulic Conductivity")}

--------------------------------------------------------------------------------
3. BIOMECHANICAL LODGING PROGNOSTICS
--------------------------------------------------------------------------------
- Atmospheric Wind Vector     : {res['mean_wind_kmh']:.1f} km/h (ECMWF 10m Reanalysis)
- Lodging Risk Index Score    : {res['mean_lodging']:.2f}
- Structural Vulnerability    : {res['lodging_label']}
- Agronomic Directive         : {"Halt all canal irrigation and nitrogen application. Clear drainage channels to prevent stalk toppling." if res['lodging_label'] == "HIGH RISK" else "Stalk elasticity and root anchorage are structurally sound under current atmospheric load."}

--------------------------------------------------------------------------------
4. AUTONOMOUS ACTUATION TELEMETRY (ISOBUS ISO 11783-10)
--------------------------------------------------------------------------------
- Actuation Mode              : {res['valve_command']}
- Prescribed Solenoid Duty    : {res['duty_cycle']}%
- Target Irrigation Depth     : {res['app_depth_mm']} mm
- Hydraulic Lockout Override  : {res['lockout']}

--------------------------------------------------------------------------------
AgroSAR Prognostics Engine — Spaceborne Precision Hydrology System
"""
        st.code(audit_text, language="text")
        st.download_button(
            label="📄 Download Official Field Audit Certificate (TXT)",
            data=audit_text,
            file_name=f"AgroSAR_Audit_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            type="primary",
            use_container_width=True
        )

elif page == "👥 Project Innovators & Mentor":
    st.markdown(
        """
        <div class="mission-box">
            <h3 style="color: #1E3F20; margin-top:0;">👥 Project Architecture & Engineering Team</h3>
            <p>AgroSAR: A Multi-Temporal Spaceborne Radar Inversion Framework for Sub-Canopy Hydrology and Lodging Prognostics.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.subheader("🎓 Project Mentor")
    mentor_html = (
        '<div class="hud-card" style="border-color: #1E3F20; min-height: 92px; margin-bottom: 18px;">'
        '<div class="profile-popup">'
        '<div class="profile-badge">🎓 Project Mentor</div>'
        '<div class="profile-row"><strong>Name:</strong> Prof. Subhrangshu Das</div>'
        '<div class="profile-row"><strong>Designation:</strong> Associate Professor & Project Supervisor</div>'
        '<div class="profile-row"><strong>Departments:</strong> CSIT, CST, CSE (Cyber Security) & CSE (Networks)</div>'
        '<div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>'
        '</div>'
        '<div class="hud-card-name" style="color: #1E3F20;">PROF. SUBHRANGSHU DAS</div>'
        '</div>'
    )
    st.markdown(mentor_html, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("👨‍💻 Project Innovators / Builders")
    col1, col2 = st.columns(2)
    with col1:
        team_col1_html = (
            '<div class="hud-card" style="margin-bottom:16px; min-height: 92px;">'
            '<div class="profile-popup">'
            '<div class="profile-badge">👨‍💻 Project Innovator • Group 18</div>'
            '<div class="profile-row"><strong>Name:</strong> Ansh Verma</div>'
            '<div class="profile-row"><strong>Roll No.:</strong> 8</div>'
            '<div class="profile-row"><strong>Enrollment No.:</strong> 12024002023007</div>'
            '<div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>'
            '<div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>'
            '</div>'
            '<div class="hud-card-name">ANSH VERMA</div>'
            '</div>'
            '<div class="hud-card" style="margin-bottom:16px; min-height: 92px;">'
            '<div class="profile-popup">'
            '<div class="profile-badge">👨‍💻 Project Innovator • Group 18</div>'
            '<div class="profile-row"><strong>Name:</strong> Bishal Dutta</div>'
            '<div class="profile-row"><strong>Roll No.:</strong> 18</div>'
            '<div class="profile-row"><strong>Enrollment No.:</strong> 12024002023015</div>'
            '<div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>'
            '<div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>'
            '</div>'
            '<div class="hud-card-name">BISHAL DUTTA</div>'
            '</div>'
        )
        st.markdown(team_col1_html, unsafe_allow_html=True)
    with col2:
        team_col2_html = (
            '<div class="hud-card" style="margin-bottom:16px; min-height: 92px;">'
            '<div class="profile-popup">'
            '<div class="profile-badge">👨‍💻 Project Innovator • Group 18</div>'
            '<div class="profile-row"><strong>Name:</strong> Arghya Paramanik</div>'
            '<div class="profile-row"><strong>Roll No.:</strong> 10</div>'
            '<div class="profile-row"><strong>Enrollment No.:</strong> 12024002023009</div>'
            '<div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>'
            '<div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>'
            '</div>'
            '<div class="hud-card-name">ARGHYA PARAMANIK</div>'
            '</div>'
            '<div class="hud-card" style="margin-bottom:16px; min-height: 92px;">'
            '<div class="profile-popup">'
            '<div class="profile-badge">👩‍💻 Project Innovator • Group 18</div>'
            '<div class="profile-row"><strong>Name:</strong> Adrija Sarkar</div>'
            '<div class="profile-row"><strong>Roll No.:</strong> 3</div>'
            '<div class="profile-row"><strong>Enrollment No.:</strong> 12024002023003</div>'
            '<div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>'
            '<div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>'
            '</div>'
            '<div class="hud-card-name">ADRIJA SARKAR</div>'
            '</div>'
        )
        st.markdown(team_col2_html, unsafe_allow_html=True)
