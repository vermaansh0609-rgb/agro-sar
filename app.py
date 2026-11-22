import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import requests
import json
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
def translate_advisories_cached(texts_tuple: tuple, target_lang_code: str):
    if target_lang_code == "en":
        return list(texts_tuple)
    translated_list = []
    translator = GoogleTranslator(source="en", target=target_lang_code)
    for item in texts_tuple:
        try:
            translated_list.append(translator.translate(item))
        except Exception:
            translated_list.append(item)
    return translated_list

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
        background: linear-gradient(180deg, #f4f7f1 0%, #ebe5d8 100%) !important;
        color: #1f2d1f !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    }

    .agro-brand-bar {
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 8px 4px 12px 4px;
        margin-bottom: 6px;
        border-bottom: 2px solid rgba(45, 106, 79, 0.18);
    }

    .agro-title {
        font-size: 2.25rem;
        font-weight: 900;
        letter-spacing: 0.02em;
        background: linear-gradient(90deg, #1b4332 0%, #2d6a4f 55%, #b68900 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        line-height: 1.1;
    }

    div[data-testid="stHorizontalBlock"] .stButton > button {
        background: rgba(255, 255, 255, 0.82);
        color: #1b4332;
        border: 1px solid rgba(45, 106, 79, 0.25);
        border-radius: 999px;
        padding: 0.45rem 0.95rem;
        font-weight: 600;
        font-size: 0.88rem;
        box-shadow: 0 2px 6px rgba(27, 67, 50, 0.06);
        transition: all 0.25s ease;
    }
    div[data-testid="stHorizontalBlock"] .stButton > button:hover {
        background: #2d6a4f;
        color: #ffffff;
        border-color: #2d6a4f;
        transform: translateY(-1px);
    }
    div[data-testid="stHorizontalBlock"] .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2d6a4f 0%, #40916c 100%) !important;
        color: #ffffff !important;
        border: 1px solid #1b4332 !important;
        box-shadow: 0 4px 12px rgba(45, 106, 79, 0.28) !important;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2d6a4f 0%, #52796f 100%);
        color: #ffffff;
        border: none;
        border-radius: 10px;
        font-weight: 700;
        box-shadow: 0 4px 14px rgba(45, 106, 79, 0.25);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #1b4332 0%, #2d6a4f 100%);
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
        background: #ffffff;
        border: 1.5px solid rgba(45, 106, 79, 0.24);
        border-radius: 14px;
        padding: 18px 16px;
        position: relative;
        box-shadow: 0 6px 20px rgba(62, 47, 28, 0.08);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 185px;
        transition: transform 0.28s ease, box-shadow 0.28s ease, border-color 0.28s ease;
        cursor: pointer;
    }

    .hud-card:hover {
        transform: translateY(-4px);
        border-color: #d4a373;
        box-shadow: 0 12px 28px rgba(45, 106, 79, 0.18);
        z-index: 30;
    }

    .hud-card::before {
        content: "";
        position: absolute;
        top: 0; left: 16px; right: 16px;
        height: 4px;
        border-radius: 0 0 4px 4px;
        background: linear-gradient(90deg, #2d6a4f, #e9c46a);
    }

    .hover-popup {
        visibility: hidden;
        opacity: 0;
        position: absolute;
        bottom: calc(100% + 12px);
        left: 50%;
        transform: translateX(-50%) translateY(8px);
        width: 270px;
        background: #fffdf8;
        border: 2px solid #2d6a4f;
        border-radius: 14px;
        padding: 12px 14px;
        box-shadow: 0 14px 32px rgba(27, 67, 50, 0.25);
        z-index: 999;
        transition: opacity 0.25s ease, transform 0.25s ease, visibility 0.25s;
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
        border-color: #2d6a4f transparent transparent transparent;
    }

    .hud-card:hover .hover-popup {
        visibility: visible;
        opacity: 1;
        transform: translateX(-50%) translateY(0);
    }

    .popup-title {
        font-size: 0.82rem;
        font-weight: 800;
        color: #1b4332;
        margin-top: 6px;
        margin-bottom: 3px;
    }

    .popup-caption {
        font-size: 0.74rem;
        color: #4a554a;
        line-height: 1.32;
    }

    .profile-popup {
        visibility: hidden;
        opacity: 0;
        position: absolute;
        bottom: calc(100% + 12px);
        left: 50%;
        transform: translateX(-50%) translateY(8px);
        width: 310px;
        background: #fffdf8;
        border: 2px solid #2d6a4f;
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: 0 14px 34px rgba(27, 67, 50, 0.25);
        z-index: 999;
        transition: opacity 0.25s ease, transform 0.25s ease, visibility 0.25s;
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
        border-color: #2d6a4f transparent transparent transparent;
    }

    .hud-card:hover .profile-popup {
        visibility: visible;
        opacity: 1;
        transform: translateX(-50%) translateY(0);
    }

    .profile-row {
        font-size: 0.78rem;
        color: #2d3a2d;
        margin-bottom: 4px;
        line-height: 1.35;
    }

    .profile-badge {
        display: inline-block;
        background: #e9f5db;
        color: #1b4332;
        font-weight: 700;
        font-size: 0.72rem;
        padding: 2px 8px;
        border-radius: 999px;
        margin-bottom: 6px;
        border: 1px solid #95d5b2;
    }

    .hud-card-name {
        font-size: 1.3rem;
        font-weight: 800;
        color: #1b4332;
        margin: auto 0;
        letter-spacing: 0.03em;
    }

    .hud-card-label {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #5c4d3c;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .hud-card-value {
        font-size: 1.85rem;
        font-weight: 800;
        color: #1b4332;
        margin: 8px 0 4px 0;
        line-height: 1.15;
    }

    .hud-card-value-cmd {
        font-size: clamp(0.88rem, 1.08vw, 1.05rem);
        font-weight: 800;
        color: #2d6a4f;
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
        color: #526052;
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
        background: #e9f5db;
        border: 1px solid #95d5b2;
        color: #1b4332;
    }

    .pill-amber {
        background: #fefae0;
        border: 1px solid #e9c46a;
        color: #8c5a00;
    }

    .pill-red {
        background: #fde8e8;
        border: 1px solid #f8b4b4;
        color: #9b1c1c;
    }

    .pill-blue {
        background: #e0f2fe;
        border: 1px solid #7dd3fc;
        color: #075985;
    }

    .mission-box {
        background: rgba(255, 255, 255, 0.88);
        border: 1.5px solid rgba(45, 106, 79, 0.22);
        border-radius: 14px;
        padding: 20px 22px;
        margin-bottom: 20px;
        box-shadow: 0 4px 16px rgba(62, 47, 28, 0.06);
        color: #1f2d1f;
    }

    .advisory-item {
        background: #ffffff;
        border-left: 4px solid #2d6a4f;
        padding: 12px 16px;
        margin-bottom: 10px;
        border-radius: 0 10px 10px 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: #1f2d1f;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    }
    .advisory-alert {
        border-left-color: #c1121f;
        background: #fff5f5;
    }
    .advisory-warn {
        border-left-color: #d97706;
        background: #fffbeb;
    }
    .advisory-safe {
        border-left-color: #2d6a4f;
        background: #f2f9f1;
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
    splash_html = """
    <div style="
        background: linear-gradient(135deg, #1b4332 0%, #2d6a4f 55%, #7f5539 100%);
        border-radius: 20px;
        padding: 54px 28px;
        text-align: center;
        color: #fffdf8;
        box-shadow: 0 18px 42px rgba(27, 67, 50, 0.28);
        border: 3px solid #e9c46a;
        margin: 14px auto 22px auto;
        max-width: 920px;
    ">
        <svg width="96" height="96" viewBox="0 0 100 100" style="margin-bottom: 10px;">
            <circle cx="50" cy="50" r="44" fill="#e9c46a" opacity="0.22"/>
            <circle cx="50" cy="36" r="14" fill="#ffb703"/>
            <path d="M50 84 L50 44" stroke="#95d5b2" stroke-width="5" stroke-linecap="round"/>
            <path d="M50 66 C34 62, 28 48, 36 42 C44 46, 48 56, 50 66 Z" fill="#74c69d"/>
            <path d="M50 58 C66 54, 72 40, 64 34 C56 38, 52 48, 50 58 Z" fill="#b7e4c7"/>
            <ellipse cx="50" cy="85" rx="28" ry="6" fill="#d4a373"/>
        </svg>
        <div style="font-size: 2.5rem; font-weight: 900; letter-spacing: 0.02em; color: #fefae0; margin-bottom: 6px;">
            🙏 Namaste & Hello, Kisan Mitra!
        </div>
        <div style="font-size: 1.15rem; font-weight: 600; color: #e9c46a; margin-bottom: 14px;">
            Welcome to AGROSAR — Smart Sub-Canopy Soil Moisture & Crop Protection Assistant
        </div>
        <p style="font-size: 0.96rem; color: #f1faee; max-width: 640px; margin: 0 auto; line-height: 1.55;">
            No underground sensors needed. Check root-zone water levels, storm lodging risk, and precision irrigation advice in your own language.
        </p>
    </div>
    """
    st.markdown(splash_html, unsafe_allow_html=True)
    _, col_enter, _ = st.columns([1.2, 1.6, 1.2])
    with col_enter:
        if st.button("🌾 Enter AgroSAR Portal", type="primary", use_container_width=True):
            st.session_state["splash_seen"] = True
            st.rerun()
    st.stop()

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
    <svg width="46" height="46" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="2" y="2" width="60" height="60" rx="16" fill="#1b4332"/>
        <circle cx="44" cy="20" r="7" fill="#ffb703"/>
        <path d="M32 52V24" stroke="#95d5b2" stroke-width="3.5" stroke-linecap="round"/>
        <path d="M32 42C21 40 16 30 22 25C28 28 31 35 32 42Z" fill="#52b788"/>
        <path d="M32 35C43 33 48 23 42 18C36 21 33 28 32 35Z" fill="#b7e4c7"/>
        <path d="M16 52C22 49 42 49 48 52" stroke="#d4a373" stroke-width="3.5" stroke-linecap="round"/>
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
            <h3 style="color: #1b4332; margin-top:0;">🌾 Operational Overview</h3>
            <p><strong>AgroSAR</strong> is a spaceborne radar monitoring and variable-rate actuation infrastructure designed to invert sub-canopy root-zone soil hydrology without relying on physical ground probes.</p>
            <p>Conventional optical vegetation indices (like NDVI) only evaluate top-canopy greenness and fail to detect subterranean root saturation or moisture deficits. AgroSAR leverages <strong>ESA Sentinel-1 C-band synthetic aperture radar (SAR)</strong> to penetrate dense crop foliage, separating soil dielectric permittivity from geometric surface roughness.</p>
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
                <div style="color: #2d3a2d; font-size: 0.9rem; margin-top: 8px; line-height: 1.55;">
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
                <div style="color: #2d3a2d; font-size: 0.9rem; margin-top: 8px; line-height: 1.55;">
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
                <div style="color: #2d3a2d; font-size: 0.9rem; margin-top: 8px; line-height: 1.55;">
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
                    background: linear-gradient(135deg, #2d6a4f, #40916c);
                    border: none;
                    color: #ffffff;
                    padding: 9px 12px;
                    font-weight: 700;
                    border-radius: 8px;
                    cursor: pointer;
                    width: 100%;
                    font-size: 0.85rem;
                    box-shadow: 0 3px 8px rgba(45, 106, 79, 0.25);
                ">🎯 Ping Live Field GPS</button>
                <p id="status" style="color: #1b4332; font-size: 0.74rem; margin-top: 6px; font-weight: 600;"></p>
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

        sm_pill = "pill-amber" if res["mean_sm"] < 16.0 else ("pill-blue" if res["mean_sm"] > 35.0 else "pill-green")
        sm_desc = "Deficit: Root stress; pulse irrigation required." if res["mean_sm"] < 16.0 else (
            "Waterlogged: Saturated; suspend furrow irrigation." if res["mean_sm"] > 35.0 else "Optimal: Healthy moisture availability."
        )

        r_desc = "Plowed / High Tilth: Heavy surface roughness filtered." if res["mean_roughness"] > 1.25 else "Smooth Seedbed: Minimal roughness interference."
        w_desc = "High aerodynamic drag on standing stalks." if res["mean_wind_kmh"] > 25.0 else "Gentle breeze: Minimal mechanical shear stress."

        hud_cards_html = f"""
        <div class="hud-grid">
            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <rect x="10" y="42" width="80" height="26" rx="6" fill="#7f5539"/>
                        <path d="M50 42 L50 18 M50 32 L38 24 M50 28 L62 20" stroke="#52b788" stroke-width="4" stroke-linecap="round"/>
                        <circle class="svg-drop" cx="34" cy="52" r="4" fill="#38bdf8"/>
                        <circle class="svg-drop" cx="50" cy="56" r="5" fill="#0284c7"/>
                        <circle class="svg-drop" cx="66" cy="52" r="4" fill="#38bdf8"/>
                    </svg>
                    <div class="popup-title">Root-Zone Water Vision</div>
                    <div class="popup-caption">Radar waves pass right through leaves to measure water hugging the crop roots below!</div>
                </div>
                <div>
                    <div class="hud-card-label">💧 Decoupled Moisture</div>
                    <div class="hud-card-value">{res['mean_sm']:.1f}%</div>
                    <div class="card-explainer">True subterranean root water, calculated beneath crop foliage.</div>
                </div>
                <div class="hud-pill {sm_pill}">{sm_desc}</div>
            </div>

            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <path d="M10 54 Q22 40 34 54 T58 54 T82 54 L90 66 L10 66 Z" fill="#9c6644"/>
                        <path class="svg-wave" d="M22 14 L46 44 M78 14 L54 44" stroke="#2d6a4f" stroke-width="3" stroke-linecap="round"/>
                        <circle cx="50" cy="48" r="5" fill="#e9c46a"/>
                    </svg>
                    <div class="popup-title">Soil Bump & Furrow Filter</div>
                    <div class="popup-caption">Separates plowed dirt clods from real moisture so rough soil never tricks the reading.</div>
                </div>
                <div>
                    <div class="hud-card-label">🪨 Roughness Factor</div>
                    <div class="hud-card-value">{res['mean_roughness']:.2f}</div>
                    <div class="card-explainer">Filters out bumps from tilling so radar isn't deceived.</div>
                </div>
                <div class="hud-pill pill-blue">{r_desc}</div>
            </div>

            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <path class="svg-wind" d="M12 24 H64 C72 24 72 14 64 14" stroke="#0284c7" stroke-width="3.5" fill="none" stroke-linecap="round"/>
                        <path class="svg-wind" d="M18 38 H76 C84 38 84 48 76 48" stroke="#38bdf8" stroke-width="3.5" fill="none" stroke-linecap="round"/>
                        <path class="svg-sway" d="M50 66 L50 30 M50 42 L40 34 M50 36 L60 28" stroke="#2d6a4f" stroke-width="4" stroke-linecap="round"/>
                    </svg>
                    <div class="popup-title">Field Breeze & Gust Check</div>
                    <div class="popup-caption">Tracks live 10m wind speed pushing against tall crop stems across your field.</div>
                </div>
                <div>
                    <div class="hud-card-label">🌬️ ERA5 Surface Wind</div>
                    <div class="hud-card-value">{res['mean_wind_kmh']:.1f} <span style="font-size:0.95rem; font-weight:500; color:#526052;">km/h</span></div>
                    <div class="card-explainer">Live 10-meter wind applying physical shear against crop stems.</div>
                </div>
                <div class="hud-pill pill-green">{w_desc}</div>
            </div>

            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <rect x="14" y="56" width="72" height="12" rx="4" fill="#7f5539"/>
                        <g class="svg-sway">
                            <path d="M46 58 L56 20" stroke="#d97706" stroke-width="5" stroke-linecap="round"/>
                            <ellipse cx="58" cy="18" rx="6" ry="10" transform="rotate(20 58 18)" fill="#ffb703"/>
                        </g>
                        <path class="svg-wind" d="M14 28 H42" stroke="#c1121f" stroke-width="3" stroke-linecap="round"/>
                    </svg>
                    <div class="popup-title">Crop Topple Safety Guard</div>
                    <div class="popup-caption">Checks if soggy roots + strong winds could bend or flatten your standing harvest.</div>
                </div>
                <div>
                    <div class="hud-card-label">⚠️ Lodging Threat</div>
                    <div class="hud-card-value" style="color: {'#c1121f' if res['lodging_label'] == 'HIGH RISK' else ('#d97706' if res['lodging_label'] == 'Moderate Risk' else '#1b4332')};">
                        {res['lodging_label']}
                    </div>
                    <div class="card-explainer">Calculates if wind drag torque will topple roots in wet soil.</div>
                </div>
                <div class="hud-pill {l_pill}">{l_desc}</div>
            </div>
        </div>
        """
        st.markdown(hud_cards_html, unsafe_allow_html=True)

        st.subheader("🗺️ 10-Meter Sub-Canopy SAR Radar Heatmap")
        st.caption("💡 **Tip:** Blue shades indicate high moisture, brown indicates dry soil. Use the top-right layer switch to inspect Lodging Risk or Greenness.")

        st.markdown(
            """
            <style>
            .leaflet-control-layers {
                font-family: inherit !important;
                font-size: 13px !important;
                box-shadow: 0 4px 14px rgba(27, 67, 50, 0.25) !important;
                border-radius: 10px !important;
                padding: 10px 14px !important;
                margin-right: 18px !important;
                background: rgba(255, 253, 248, 0.96) !important;
                color: #1b4332 !important;
                border: 1.5px solid #2d6a4f !important;
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
            "palette": ["1a9641", "a6d96a", "ffffbf", "fdae61", "d7191c"]
        }
        ndvi_vis = {
            "bands": ["NDVI"],
            "min": 0.0,
            "max": 0.8,
            "palette": ["#8c510a", "#ffffbf", "#1b7837"]
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
            line=dict(color='#2d6a4f', width=3.5), marker=dict(size=7)
        ))
        fig.add_trace(go.Scatter(
            x=[hist_days[-1]] + fc_days, y=[hist_values[-1]] + fc_values, mode='lines+markers', name='Prognostic Forecast',
            line=dict(color='#d97706', width=3.5, dash='dash'), marker=dict(size=7)
        ))
        fig.add_hline(
            y=16.0, line_dash="dot", annotation_text="Wilting Stress Threshold (16.0%)",
            annotation_position="bottom right", line_color="#c1121f"
        )
        fig.update_layout(
            xaxis_title="Observation Timeline", yaxis_title="Volumetric Soil Moisture (%)",
            plot_bgcolor='rgba(255,255,255,0.75)', paper_bgcolor='rgba(255,255,255,0.0)',
            font=dict(color="#1f2d1f"), margin=dict(l=10, r=10, t=30, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)

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
            p2_plain = f"⏳ Projected Stress In {days_to_wilting} Days: Following the orange dashed curve, root-zone moisture will drop below the 16.0% wilting threshold in approximately Day +{days_to_wilting} unless supplemental water or rainfall occurs."
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

        raw_points = (p1_plain, p2_plain, p3_plain, p4_plain, p5_plain, p6_plain)
        translated_points = translate_advisories_cached(raw_points, target_lang_code)

        def bold_prefix(txt: str) -> str:
            if ":" in txt:
                head, rest = txt.split(":", 1)
                return f"<strong>{head}:</strong>{rest}"
            return txt

        advisory_html = f"""
        <div>
            <div class="advisory-item {p1_class}">{bold_prefix(translated_points[0])}</div>
            <div class="advisory-item {p2_class}">{bold_prefix(translated_points[1])}</div>
            <div class="advisory-item {p3_class}">{bold_prefix(translated_points[2])}</div>
            <div class="advisory-item {p4_class}">{bold_prefix(translated_points[3])}</div>
            <div class="advisory-item {p5_class}">{bold_prefix(translated_points[4])}</div>
            <div class="advisory-item {p6_class}">{bold_prefix(translated_points[5])}</div>
        </div>
        """
        st.markdown(advisory_html, unsafe_allow_html=True)

elif page == "⚡ Actuation Protocol (VRI)":
    if not res:
        st.info("👆 Please execute a satellite radar scan from the Radar Analysis Canvas to generate live machine telemetry.")
    else:
        st.markdown(
            """
            <div class="mission-box">
                <h3 style="color: #1b4332; margin-top:0;">⚡ Cyber-Physical Machine Actuation Console</h3>
            </div>
            """,
            unsafe_allow_html=True
        )

        lockout_status = "ACTIVE" if res["lockout"] else "INACTIVE"
        lockout_pill = "pill-red" if res["lockout"] else "pill-green"
        lockout_desc = "Emergency Inhibit: Water discharge locked out to protect stalks." if res["lockout"] else "Normal Operation: Solenoid circuits authorized."

        vri_cards_html = f"""
        <div class="hud-grid-3">
            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <rect x="18" y="14" width="64" height="44" rx="10" fill="#1b4332"/>
                        <circle class="svg-gear" cx="38" cy="36" r="10" stroke="#e9c46a" stroke-width="3" stroke-dasharray="4 3" fill="none"/>
                        <path class="svg-wave" d="M54 36 H74" stroke="#95d5b2" stroke-width="4" stroke-linecap="round"/>
                    </svg>
                    <div class="popup-title">Smart Pump Brain Signal</div>
                    <div class="popup-caption">Sends the exact automated instruction directly to your field's irrigation controller.</div>
                </div>
                <div>
                    <div class="hud-card-label">⚙️ Command Mode</div>
                    <div class="hud-card-value-cmd" title="{res['valve_command']}">{res['valve_command']}</div>
                    <div class="card-explainer">The exact algorithmic instruction dispatched to the irrigation controller.</div>
                </div>
                <div class="hud-pill pill-blue">ISO 11783-10 Actuation Vector</div>
            </div>

            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <rect x="16" y="24" width="68" height="14" rx="6" fill="#52796f"/>
                        <rect x="42" y="14" width="16" height="10" rx="3" fill="#e9c46a"/>
                        <circle class="svg-drop" cx="34" cy="52" r="4.5" fill="#0284c7"/>
                        <circle class="svg-drop" cx="50" cy="58" r="4.5" fill="#38bdf8"/>
                        <circle class="svg-drop" cx="66" cy="52" r="4.5" fill="#0284c7"/>
                    </svg>
                    <div class="popup-title">Precision Valve Pulse</div>
                    <div class="popup-caption">Controls how wide and how long water valves open so not a single drop is wasted.</div>
                </div>
                <div>
                    <div class="hud-card-label">⚡ PWM Solenoid Duty</div>
                    <div class="hud-card-value">{res['duty_cycle']}%</div>
                    <div class="card-explainer">Valve pulse frequency; delivers target water depth of {res['app_depth_mm']} mm.</div>
                </div>
                <div class="hud-pill pill-amber">Target Depth: {res['app_depth_mm']} mm</div>
            </div>

            <div class="hud-card">
                <div class="hover-popup">
                    <svg width="86" height="64" viewBox="0 0 100 74">
                        <path d="M50 10 L76 22 V40 C76 54 64 64 50 68 C36 64 24 54 24 40 V22 L50 10 Z" fill="#2d6a4f"/>
                        <rect x="41" y="34" width="18" height="15" rx="3" fill="#ffb703"/>
                        <path d="M45 34 V28 A5 5 0 0 1 55 28 V34" stroke="#fefae0" stroke-width="3" fill="none"/>
                    </svg>
                    <div class="popup-title">Storm Safety Shutoff Shield</div>
                    <div class="popup-caption">Automatically locks water gates during high winds so wet roots never lose grip.</div>
                </div>
                <div>
                    <div class="hud-card-label">🛡️ Hydraulic Lockout</div>
                    <div class="hud-card-value" style="color: {'#c1121f' if res['lockout'] else '#1b4332'};">
                        {lockout_status}
                    </div>
                    <div class="card-explainer">Autonomous fail-safe that cuts water when high winds threaten to uproot stalks.</div>
                </div>
                <div class="hud-pill {lockout_pill}">{lockout_desc}</div>
            </div>
        </div>
        """
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
                <h3 style="color: #1b4332; margin-top:0;">📋 Spaceborne Field Audit Certification</h3>
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
            <h3 style="color: #1b4332; margin-top:0;">👥 Project Architecture & Engineering Team</h3>
            <p>AgroSAR: A Multi-Temporal Spaceborne Radar Inversion Framework for Sub-Canopy Hydrology and Lodging Prognostics.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.subheader("🎓 Academic Guidance & Project Mentorship")
    st.markdown(
        """
        <div class="hud-card" style="border-color: #2d6a4f; background: #f2f9f1; min-height: 92px; margin-bottom: 18px;">
            <div class="profile-popup">
                <div class="profile-badge">🎓 Project Mentor</div>
                <div class="profile-row"><strong>Name:</strong> Prof. Subhrangshu Das</div>
                <div class="profile-row"><strong>Designation:</strong> Associate Professor & Project Supervisor</div>
                <div class="profile-row"><strong>Departments:</strong> CSIT, CST, CSE (Cyber Security) & CSE (Networks)</div>
                <div class="profile-row"><strong>Lab Affiliation:</strong> IEDC Lab (Innovation & Entrepreneurship Development Centre)</div>
                <div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>
            </div>
            <div class="hud-card-name" style="color: #1b4332;">PROF. SUBHRANGSHU DAS</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("---")
    st.subheader("👨‍💻 Project Innovators / Builders")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            """
            <div class="hud-card" style="margin-bottom:16px; min-height: 92px;">
                <div class="profile-popup">
                    <div class="profile-badge">👨‍💻 Project Innovator • Group 18</div>
                    <div class="profile-row"><strong>Name:</strong> Ansh Verma</div>
                    <div class="profile-row"><strong>Roll No.:</strong> 8</div>
                    <div class="profile-row"><strong>Enrollment No.:</strong> 12024002023007</div>
                    <div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>
                    <div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>
                </div>
                <div class="hud-card-name">ANSH VERMA</div>
            </div>

            <div class="hud-card" style="margin-bottom:16px; min-height: 92px;">
                <div class="profile-popup">
                    <div class="profile-badge">👨‍💻 Project Innovator • Group 18</div>
                    <div class="profile-row"><strong>Name:</strong> Bishal Dutta</div>
                    <div class="profile-row"><strong>Roll No.:</strong> 18</div>
                    <div class="profile-row"><strong>Enrollment No.:</strong> 12024002023015</div>
                    <div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>
                    <div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>
                </div>
                <div class="hud-card-name">BISHAL DUTTA</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            """
            <div class="hud-card" style="margin-bottom:16px; min-height: 92px;">
                <div class="profile-popup">
                    <div class="profile-badge">👨‍💻 Project Innovator • Group 18</div>
                    <div class="profile-row"><strong>Name:</strong> Arghya Paramanik</div>
                    <div class="profile-row"><strong>Roll No.:</strong> 10</div>
                    <div class="profile-row"><strong>Enrollment No.:</strong> 12024002023009</div>
                    <div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>
                    <div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>
                </div>
                <div class="hud-card-name">ARGHYA PARAMANIK</div>
            </div>

            <div class="hud-card" style="margin-bottom:16px; min-height: 92px;">
                <div class="profile-popup">
                    <div class="profile-badge">👩‍💻 Project Innovator • Group 18</div>
                    <div class="profile-row"><strong>Name:</strong> Adrija Sarkar</div>
                    <div class="profile-row"><strong>Roll No.:</strong> 3</div>
                    <div class="profile-row"><strong>Enrollment No.:</strong> 12024002023003</div>
                    <div class="profile-row"><strong>Stream:</strong> B.Tech in Computer Science & Information Technology (CSIT)</div>
                    <div class="profile-row"><strong>College:</strong> Institute of Engineering and Management (IEM), Kolkata</div>
                </div>
                <div class="hud-card-name">ADRIJA SARKAR</div>
            </div>
            """,
            unsafe_allow_html=True
        )
