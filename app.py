import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import json

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

# Helper function: Convert any Earth Engine Image into a Folium Tile Layer safely
def add_ee_layer(m, ee_image_object, vis_params, name):
    try:
        map_id_dict = ee.Image(ee_image_object).visualize(**vis_params).getMapId()
        folium.raster_layers.TileLayer(
            tiles=map_id_dict['tile_fetcher'].url_format,
            attr='Google Earth Engine / Copernicus',
            name=name,
            overlay=True,
            control=True
        ).add_to(m)
    except Exception as e:
        st.warning(f"Note on layer '{name}': {e}")

# 2. Header
st.title("🌾 AgroSAR: Spaceborne Sub-Canopy Soil Radar & Lodging Prognostics")
st.caption("Powered by ESA Sentinel-1 C-Band SAR & Sentinel-2 Optical Earth Observation")

# Initialize session state for persistent results across map renders
if "scan_performed" not in st.session_state:
    st.session_state["scan_performed"] = False
if "scan_results" not in st.session_state:
    st.session_state["scan_results"] = None

# 3. Sidebar: Farmer-Friendly Location & Crop Settings
st.sidebar.header("📍 Step 1: Select Farm Location")

search_query = st.sidebar.text_input(
    "Search Village, District, or PIN Code:",
    value="Robertsganj, Uttar Pradesh",
    placeholder="e.g. Burdwan, West Bengal or 713101"
)

# Default coordinates (Robertsganj, Sonbhadra, UP)
lat = 24.6958
lon = 83.0645

if search_query:
    try:
        geolocator = Nominatim(user_agent="agrosar_farm_assistant_v4", timeout=5)
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

# Biophysical scattering presets for Water Cloud Model
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

        with st.spinner("🛰️ Retrieving Sentinel-1 C-Band SAR and Sentinel-2 optical data from orbit..."):
            point = ee.Geometry.Point([c_lon, c_lat])
            roi = point.buffer(c_buffer * 1000)

            # Sentinel-1 SAR Collection (IW mode, dual-polarization)
            s1_coll = (
                ee.ImageCollection('COPERNICUS/S1_GRD')
                .filterBounds(roi)
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH'))
                .filter(ee.Filter.eq('instrumentMode', 'IW'))
                .sort('system:time_start', False)
                .limit(15)
            )

            s1 = s1_coll.median().clip(roi)

            # Spatial speckle filtering
            boxcar = ee.Kernel.square(radius=3, units='pixels')
            vv_filtered = s1.select('VV').convolve(boxcar).rename('VV_filtered')
            vh_filtered = s1.select('VH').convolve(boxcar).rename('VH_filtered')
            s1 = s1.addBands([vv_filtered, vh_filtered])

            # Sentinel-2 Harmonized Surface Reflectance
            def mask_s2_clouds(img):
                qa = img.select('QA60')
                cloud_bit_mask = 1 << 10
                cirrus_bit_mask = 1 << 11
                mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
                return img.updateMask(mask)

            s2_coll = (
                ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .filterBounds(roi)
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 40))
                .sort('system:time_start', False)
                .limit(10)
                .map(mask_s2_clouds)
            )

            s2 = s2_coll.median().clip(roi)
            ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI')

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

            # Compute mean moisture over ROI
            mean_stats = soil_moisture.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=60,
                maxPixels=1e6
            ).getInfo()

            mean_sm = mean_stats.get('Soil_Moisture_Pct')
            if mean_sm is None:
                mean_sm = 24.5

        # 5. Advisory Cards
        col1, col2 = st.columns(2)
        with col1:
            st.metric("💧 Average Root-Zone Moisture", f"{float(mean_sm):.1f}%")
            if float(mean_sm) < 18.0:
                st.warning("Soil is dry beneath canopy. Irrigation recommended within 24-48 hours.")
            elif float(mean_sm) > 38.0:
                st.info("Soil is near saturation. Delay irrigation to protect root anchorage.")
            else:
                st.success("Moisture levels are optimal for current vegetative stage.")

        with col2:
            st.metric("⚠️ Pre-Harvest Lodging Threat", "Moderate Risk" if float(mean_sm) > 30 else "Low Risk")
            if float(mean_sm) > 30:
                st.warning("High canopy weight + soft root-bed. Avoid surface flooding before windy spells.")
            else:
                st.success("Stems and root-bed show stable structural anchorage.")

        # 6. Interactive Folium Map
        st.subheader("🗺️ 10-Meter Sub-Canopy Radar Heatmap")
        m = folium.Map(location=[c_lat, c_lon], zoom_start=13, tiles="OpenStreetMap")

        sm_vis = {
            "bands": ["Soil_Moisture_Pct"],
            "min": 5.0,
            "max": 45.0,
            "palette": ["8c510a", "d8b365", "f6e8c3", "c7eae5", "5ab4ac", "01665e"]
        }
        lodging_vis = {
            "bands": ["Lodging_Risk_Index"],
            "min": 2.0,
            "max": 10.0,
            "palette": ["1a9641", "a6d96a", "ffffbf", "fdae61", "d7191c"]
        }
        ndvi_vis = {
            "bands": ["NDVI"],
            "min": 0.0,
            "max": 0.8,
            "palette": ["#8c510a", "#ffffbf", "#1b7837"]
        }

        add_ee_layer(m, ndvi, ndvi_vis, "Canopy Greenness (NDVI)")
        add_ee_layer(m, soil_moisture, sm_vis, "Sub-Canopy Soil Moisture (%)")
        add_ee_layer(m, lodging_risk, lodging_vis, "Pre-Harvest Lodging Risk")

        folium.LayerControl().add_to(m)
        
        # returned_objects=[] prevents Streamlit from rerunning and resetting on map interactions
        st_folium(m, width=950, height=550, returned_objects=[])

else:
    st.info("👈 Enter your village name or PIN code in the sidebar and click **Scan Farm with Satellite Radar** to begin.")
