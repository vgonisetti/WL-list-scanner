import streamlit as st
import asyncio
import aiohttp
import json
from datetime import datetime

# --- 1. UI CONFIGURATION & CUSTOM CSS ---
st.set_page_config(page_title="SmartWL | Alternate Routes", layout="centered", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(145deg, #0f172a, #020617);
        color: #f8fafc;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.4rem;
        font-weight: 700;
    }
    .baseline-card {
        padding: 20px;
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(30, 41, 59, 0.7);
        margin-bottom: 20px;
    }
    .hacked-card {
        padding: 20px;
        border-radius: 12px;
        border: 1px solid rgba(16, 185, 129, 0.4);
        background: linear-gradient(to bottom right, rgba(30, 41, 59, 0.9), rgba(16, 185, 129, 0.05));
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)


# --- 2. OFFLINE DATA LAYER ---
@st.cache_data
def load_offline_stations():
    try:
        with open('list_of_stations.json', 'r') as file:
            raw_data = json.load(file)
            
        stations_dict = {}
        for item in raw_data:
            code = item.get("code") or item.get("stationCode") or item.get("station_code")
            name = item.get("name") or item.get("stationName") or item.get("station_name")
            if code and name:
                stations_dict[code] = name
        return stations_dict
    except Exception as e:
        return {"ED": "Erode", "TPTY": "Tirupati"} 

STATIONS = load_offline_stations()
TRAIN_ROUTE = ["PGT", "CBE", "TUP", "ED", "SA", "KPD", "TPTY", "RU"]


# --- 3. ALGORITHM: ROUTE GENERATOR ---
def generate_pairs(route, src, dst, spread=2):
    try:
        src_idx = route.index(src)
        dst_idx = route.index(dst)
    except ValueError:
        return []
        
    pairs = [{"src": src, "dst": dst, "type": "baseline"}]
    for i in range(1, spread + 1):
        if src_idx - i >= 0:
            pairs.append({"src": route[src_idx - i], "dst": dst, "type": "prev_board"})
        if dst_idx + i < len(route):
            pairs.append({"src": src, "dst": route[dst_idx + i], "type": "next_drop"})
        if src_idx - i >= 0 and dst_idx + i < len(route):
            pairs.append({"src": route[src_idx - i], "dst": route[dst_idx + i], "type": "both_extended"})
            
    return pairs


# --- 4. ASYNC API ORCHESTRATOR ---
async def fetch_availability(session, train, travel_date, cls, src, dst, p_type):
    # UPDATE THIS URL TO MATCH THE EXACT ONE IN YOUR RAPIDAPI PLAYGROUND
    url = "https://irctc1.p.rapidapi.com/api/v3/getLiveStation" 
    
    querystring = {
        "fromStationCode": src,
        "toStationCode": dst,
        "date": travel_date 
    }
    
    headers = {
        "x-rapidapi-key": st.secrets["RAPIDAPI_KEY"],
        "x-rapidapi-host": "irctc1.p.rapidapi.com"
    }
    
    try:
        async with session.get(url, headers=headers, params=querystring) as response:
            data = await response.json()
            
            # Print to Streamlit Cloud logs
            print(f"RAW API JSON for {src}->{dst}: {data}") 
            
            if data.get("status") is False:
                return {"src": src, "dst": dst, "type": p_type, "status": "API Error", "train_name": "N/A"}
            
            # Parsing the exact JSON array you provided
            if "data" in data and isinstance(data["data"], list):
                target_train = next((t for t in data["data"] if str(t.get("trainNumber")) == str(train)), None)
                
                if target_train:
                    train_name = target_train.get("trainName", "Unknown")
                    dep_time = target_train.get("departureTime", "N/A")
                    
                    # Passing schedule data instead of waitlist data
                    return {"src": src, "dst": dst, "type": p_type, "status": f"Departs: {dep_time}", "train_name": train_name}
                else:
                    return {"src": src, "dst": dst, "type": p_type, "status": "Train not found on route", "train_name": "N/A"}
            
            return {"src": src, "dst": dst, "type": p_type, "status": "No Trains", "train_name": "N/A"}
            
    except Exception as e:
        return {"src": src, "dst": dst, "type": p_type, "error": True, "status": "Fetch Error", "train_name": "N/A"}

async def orchestrate_search(train, travel_date, cls, src, dst):
    pairs = generate_pairs(TRAIN_ROUTE, src, dst, spread=2)
    if not pairs:
        return [{"src": src, "dst": dst, "type": "baseline", "error": True, "status": "Station not in test route", "train_name": "N/A"}]

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_availability(session, train, travel_date, cls, p["src"], p["dst"], p["type"]) for p in pairs]
        results = await asyncio.gather(*tasks)
        
    return results


# --- 5. STREAMLIT UI ---
st.title("Smart Route Finder")
st.markdown("<p style='color: #94a3b8;'>Routing via Train Schedules.</p>", unsafe_allow_html=True)

with st.container():
    col1, col2 = st.columns(2)
    
    with col1:
        default_src_idx = list(STATIONS.keys()).index("ED") if "ED" in STATIONS else 0
        src_input = st.selectbox("From", options=list(STATIONS.keys()), index=default_src_idx, format_func=lambda x: f"{x} - {STATIONS[x]}")
        train_input = st.text_input("Train No.", value="17422") # Updated default to match your JSON
        date_input = st.date_input("Travel Date", min_value=datetime.today())
        formatted_date = date_input.strftime("%Y-%m-%d") 

    with col2:
        default_dst_idx = list(STATIONS.keys()).index("TPTY") if "TPTY" in STATIONS else 1
        dst_input = st.selectbox("To", options=list(STATIONS.keys()), index=default_dst_idx, format_func=lambda x: f"{x} - {STATIONS[x]}")
        cls_input = st.selectbox("Class", options=["2A", "3A", "SL"])

if st.button("Search Route Options", type="primary", use_container_width=True):
    if src_input == dst_input:
        st.error("Source and Destination cannot be the same.")
    else:
        with st.spinner("Fetching live train schedules..."):
            
            raw_results = asyncio.run(orchestrate_search(train_input, formatted_date, cls_input, src_input, dst_input))
            
            baseline = next((r for r in raw_results if r["type"] == "baseline"), None)
            alternates = [r for r in raw_results if r["type"] != "baseline" and not r.get("error")]
            
            st.markdown("### Route Options")
            
            if baseline:
                st.markdown(f"""
                <div class="baseline-card">
                    <div style="font-size: 12px; color: #94a3b8; margin-bottom: 8px;">ORIGINAL ROUTE</div>
                    <h4>{baseline['src']} ➔ {baseline['dst']}</h4>
                </div>
                """, unsafe_allow_html=True)
                
                b_col1, b_col2 = st.columns(2)
                b_col1.metric("Schedule", baseline.get('status', 'N/A'))
                b_col2.metric("Train Name", baseline.get('train_name', 'N/A'))
                
            st.divider()
            
            if alternates:
                for alt in alternates:
                    if alt['status'] in ["Parse Error", "Fetch Error"]:
                        continue

                    st.markdown(f"""
                    <div class="hacked-card">
                        <div style="font-size: 12px; color: #10b981; font-weight: 600; margin-bottom: 8px;">ALTERNATE BOARDING</div>
                        <h4>{alt['src']} ➔ {alt['dst']}</h4>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    a_col1, a_col2 = st.columns(2)
                    a_col1.metric("Schedule", alt.get('status', 'N/A'))
                    a_col2.metric("Train Name", alt.get('train_name', 'N/A'))
            else:
                st.info("No alternate schedules could be fetched.")
        
