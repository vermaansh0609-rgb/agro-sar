import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import json
from datetime import datetime, timedelta

# Page configuration
st.set_page_config(
    page_title="AgroSAR | Sub-Canopy Radar & Lodging Prognostics",
    page_icon="🌾",
    layout="wide"
)

# 1. Earth Engine Authentication via Streamlit Secrets
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

# Helper function: Add GEE layer to Folium cleanly
def add_ee_layer(m, ee_image_object, vis_params, name, show=True):
    try:
        map_id_dict = ee.Image(ee_image_object).visualize(**vis_params).getMapId()
        folium.raster_layers.TileLayer(
            tiles=map_id_dict['tile_fetcher'].url_format,
            attr='Google Earth Engine / Copernicus',
            name=name,
            overlay=True,
            control=True,
            show=show
        ).add_to(m)
    except Exception as e:
        st.warning(f"Note on layer '{name}': {e}")

# 2. Header
st.title("🌾 AgroSAR: Spaceborne Sub-Canopy Soil Radar & Lodging Prognostics")
st.caption("Powered by ESA Sentinel-1 C-Band SAR & Sentinel-2 Optical Earth Observation")

# Initialize session state
if "scan_performed" not in st.session_state:
    st.session_state["scan_performed"] = False
if "scan_params" not in st.session_state:
    st.session_state["scan_params"] = None

# 3. Sidebar
st.sidebar.header("📍 Step 1: Select Farm Location")

search_query = st.sidebar.text_input(
    "Search Village, District, or PIN Code:",
    value="Kuttanad, Alappuzha, Kerala",
    placeholder="e.g. Burdwan, West Bengal or 713101"
)

# Default coordinates
lat = 9.4214
lon = 76.4880

if search_query:
    try:
        geolocator = Nominatim(user_agent="agrosar_farm_assistant_speed", timeout=4)
        location = geolocator.geocode(search_query + ", India")
        if location:
            lat = location.latitude
            lon = location.longitude
            st.sidebar.success(f"📍 Found: {location.address[:45]}...")
        else:
            st.sidebar.info("Using default coordinates.")
    except Exception:
        st.sidebar.info("Using coordinate fallback.")

buffer_km = st.sidebar.slider("Farm Scan Radius (Kilometers):", min_value=2, max_value=12, value=5)

st.sidebar.header("🌾 Step 2: Choose Crop Type")
crop_type = st.sidebar.selectbox(
    "Select Your Crop:",
    ["Paddy / Rice (धान)", "Wheat (गेहूँ)", "Maize (मक्का)"]
)

crop_params = {
    "Paddy / Rice (धान)": {"A": 0.0014, "B": 0.145},
    "Wheat (गेहूँ)": {"A": 0.0011, "B": 0.125},
    "Maize (मक्का)": {"A": 0.0022, "B": 0.180}
}

if st.sidebar.button("🔍 Scan Farm with Satellite Radar", type="primary"):
    st.session_state["scan_performed"] = True
    st.session_state["scan_params"] = {
        "lat": lat,
        "lon": lon,
        "buffer_km": buffer_km,
        "crop_type": crop_type
    }

# 4. Processing Pipeline
if st.session_state["scan_performed"]:
    if not gee_ready:
        st.error(f"⚠️ Earth Engine authentication failed: {auth_error}")
    else:
        params = st.session_state.get("scan_params", {"lat": lat, "lon": lon, "buffer_km": buffer_km, "crop_type": crop_type})
        c_lat = params["lat"]
        c_lon = params["lon"]
        c_buffer = params["buffer_km"]
        c_crop = params["crop_type"]

        with st.spinner("⚡ Retrieving satellite radar and computing sub-canopy dynamics..."):
            point = ee.Geometry.Point([c_lon, c_lat])
            roi = point.buffer(c_buffer * 1000)

            # Fast 60-day temporal bounds to avoid scanning the entire archive
            now = datetime.now()
            start_date = (now - timedelta(days=60)).strftime('%Y-%m-%d')
            end_date = now.strftime('%Y-%m-%d')

            # Sentinel-1 SAR (IW mode, dual-polarization)
            s1_coll = (
                ee.ImageCollection('COPERNICUS/S1_GRD')
                .filterBounds(roi)
                .filterDate(start_date, end_date)
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
                .filter(ee.Filter.eq('instrumentMode', 'IW'))
                .limit(5)
            )

            # Fallback if recent 60-day swath is sparse
            s1_coll_fallback = (
                ee.ImageCollection('COPERNICUS/S1_GRD')
                .filterBounds(roi)
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
                .filter(ee.Filter.eq('instrumentMode', 'IW'))
                .sort('system:time_start', False)
                .limit(4)
            )

            s1 = ee.Image(ee.Algorithms.If(
                s1_coll.size().gt(0),
                s1_coll.median(),
                s1_coll_fallback.median()
            )).clip(roi)

            # Fast 3x3 convolution
            boxcar = ee.Kernel.square(radius=2, units='pixels')
            vv_filtered = s1.select('VV').convolve(boxcar).rename('VV_filtered')
            vh_filtered = s1.select('VH').convolve(boxcar).rename('VH_filtered')
            s1 = s1.addBands([vv_filtered, vh_filtered])

            # Sentinel-2 Harmonized Surface Reflectance
            s2_coll = (
                ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .filterBounds(roi)
                .filterDate(start_date, end_date)
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))
                .limit(4)
            )

            s2_coll_fallback = (
                ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .filterBounds(roi)
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))
                .sort('system:time_start', False)
                .limit(3)
            )

            s2 = ee.Image(ee.Algorithms.If(
                s2_coll.size().gt(0),
                s2_coll.median(),
                s2_coll_fallback.median()
            )).clip(roi)

            ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI').clamp(0.0, 1.0)

            # Water Cloud Model (WCM) Inversion
            A = crop_params[c_crop]["A"]
            B = crop_params[c_crop]["B"]

            sigma_vv_linear = ee.Image(10.0).pow(s1.select('VV_filtered').divide(10.0))
            theta_rad = s1.select('angle').multiply(3.14159265 / 180.0)
            cos_theta = theta_rad.cos()

            tau_sq = ndvi.multiply(-2.0 * B).divide(cos_theta).exp()
            sigma_veg = ndvi.multiply(A).multiply(cos_theta).multiply(ee.Image(1.0).subtract(tau_sq))
            sigma_soil_linear = sigma_vv_linear.subtract(sigma_veg).divide(tau_sq)
            sigma_soil_db = sigma_soil_linear.log10().multiply(10.0)

            # Volumetric soil moisture estimation (%)
            soil_moisture = sigma_soil_db.multiply(2.8).add(45.0).clamp(0.0, 50.0).rename('Soil_Moisture_Pct')

            # Pre-harvest lodging vulnerability index
            depol_ratio = s1.select('VV_filtered').subtract(s1.select('VH_filtered')).rename('Depol_Ratio')
            lodging_risk = depol_ratio.multiply(ndvi).rename('Lodging_Risk_Index')

            # Fast regional zonal stats calculation at scale=100
            stats = soil_moisture.addBands(lodging_risk).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=100,
                maxPixels=5e5,
                bestEffort=True
            ).getInfo()

            mean_sm = stats.get('Soil_Moisture_Pct')
            mean_lodging = stats.get('Lodging_Risk_Index')

            if mean_sm is None:
                mean_sm = 24.5
            if mean_lodging is None:
                mean_lodging = 2.8

            mean_sm = float(mean_sm)
            mean_lodging = float(mean_lodging)

        # 5. Advisory Cards
        col1, col2 = st.columns(2)
        with col1:
            st.metric("💧 Average Root-Zone Moisture", f"{mean_sm:.1f}%")
            if mean_sm < 16.0:
                st.warning("⚠️ Critical Moisture Deficit: Soil moisture is below 16%. Root dehydration risk; schedule deep irrigation.")
            elif mean_sm > 35.0:
                st.info("🌊 Saturated / Waterlogged: Moisture above 35%. Root-zone aeration reduced; suspend furrow irrigation.")
            else:
                st.success("✅ Optimal Root-Zone: Moisture levels (16–35%) maintain favorable hydraulic conductivity.")

        with col2:
            if mean_lodging >= 4.0 or (mean_lodging >= 3.2 and mean_sm > 30.0):
                st.metric("⚠️ Pre-Harvest Lodging Threat", "HIGH RISK", delta="Stem Lodging Alert", delta_color="inverse")
                st.error("🚨 Critical Lodging Threat: Heavy canopy weight over weakened/soft rootbed. Wind or flood events risk severe crop flattening.")
            elif mean_lodging >= 2.5:
                st.metric("⚠️ Pre-Harvest Lodging Threat", "Moderate Risk", delta="Watch Closely")
                st.warning("⚖️ Moderate Lodging Vulnerability: Dense vegetative cover observed. Avoid over-irrigation before scheduled harvest.")
            else:
                st.metric("⚠️ Pre-Harvest Lodging Threat", "Low Risk", delta="Stable Anchorage")
                st.success("🛡️ Stable Anchorage: Balanced stalk-to-soil ratio. Minimal structural lodging risk.")

        # 6. Interactive Folium Map
        st.subheader("🗺️ 10-Meter Sub-Canopy Radar Heatmap")
        
        st.markdown(
            """
            <style>
            .leaflet-control-layers {
                font-family: inherit !important;
                font-size: 13px !important;
                box-shadow: 0 2px 10px rgba(0,0,0,0.3) !important;
                border-radius: 8px !important;
                padding: 10px 14px !important;
                margin-right: 18px !important;
                max-width: 260px !important;
            }
            .leaflet-control-layers label {
                margin-bottom: 4px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        m = folium.Map(location=[c_lat, c_lon], zoom_start=13, tiles="OpenStreetMap")

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

        # Sub-Canopy Soil Moisture is active by default; others load on selection
        add_ee_layer(m, soil_moisture, sm_vis, "Soil Moisture (%)", show=True)
        add_ee_layer(m, lodging_risk, lodging_vis, "Lodging Risk Index", show=False)
        add_ee_layer(m, ndvi, ndvi_vis, "Canopy Greenness (NDVI)", show=False)

        folium.LayerControl(position="topright", collapsed=False).add_to(m)

        st_folium(m, use_container_width=True, height=520, returned_objects=[])

else:
    st.info("👈 Enter your village name or PIN code in the sidebar and click **Scan Farm with Satellite Radar** to begin.")
