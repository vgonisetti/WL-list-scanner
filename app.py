import streamlit as st
import asyncio
import aiohttp
import json
from datetime import datetime

# --- 1. UI CONFIGURATION & CUSTOM CSS ---
st.set_page_config(page_title="SmartWL | Alternate Routes", layout="centered", initial_sidebar_state="collapsed")

# Premium dark-theme CSS (High-Contrast, Minimalist)
st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(145deg, #0f172a, #020617);
        color: #f8fafc;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
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


# --- 2. OFFLINE DATA LAYER (Zero-Latency Station Load) ---
@st.cache_data
def load_offline_stations():
    """
    Loads station codes instantly from the local JSON file.
    Cached by Streamlit so it only runs once per server reboot.
    """
    try:
        with open('list_of_stations.json', 'r') as file:
            raw_data = json.load(file)
            
        stations_dict = {}
        for item in raw_data:
            # Handles different potential JSON key naming conventions
            code = item.get("code") or item.get("stationCode") or item.get("station_code")
            name = item.get("name") or item.get("stationName") or item.get("station_name")
            if code and name:
                stations_dict[code] = name
                
        return stations_dict
    except Exception as e:
        st.error(f"Error loading offline stations: {e}")
        return {"ED": "Erode", "TPTY": "Tirupati"} # Fallback

STATIONS = load_offline_stations()

# Mock route for testing Train 20630. 
# (Future Upgrade: Fetch this array dynamically via a Train Route API)
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


# --- 4. ASYNC API ORCHESTRATOR (Live RapidAPI Fetch) ---
async def fetch_availability(session, train, travel_date, cls, src, dst, p_type):
    """
    Fires asynchronous requests to the live RapidAPI endpoint.
    """
    # NOTE: Check your RapidAPI Playground if this exact URL path needs adjusting
    url = "https://irctc-api2.p.rapidapi.com/api/v1/checkSeatAvailability"
    
    # Adjust parameter keys if the specific API requires different names (e.g., 'sourceStation')
    querystring = {
        "trainNo": train,
        "source": src,
        "destination": dst,
        "classType": cls,
        "date": travel_date 
    }
    
    headers = {
        "X-RapidAPI-Key": st.secrets["RAPIDAPI_KEY"],
        "X-RapidAPI-Host": "irctc-api2.p.rapidapi.com"
    }
    
    try:
        async with session.get(url, headers=headers, params=querystring) as response:
            data = await response.json()
            
            # Print to Streamlit Cloud Logs for easy debugging of exact JSON keys
            print(f"API Response for {src} to {dst}: {data}")
            
            # Adjust these mapping keys based on the actual JSON structure printed in the logs
            status = data.get("current_status", "N/A")
            price = data.get("ticket_fare", 0)
            
            return {"src": src, "dst": dst, "type": p_type, "status": status, "price": price}
            
    except Exception as e:
        print(f"API Error: {str(e)}")
        return {"src": src, "dst": dst, "type": p_type, "error": True, "status": "Error", "price": 0}

async def orchestrate_search(train, travel_date, cls, src, dst):
    pairs = generate_pairs(TRAIN_ROUTE, src, dst, spread=2)
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_availability(session, train, travel_date, cls, p["src"], p["dst"], p["type"]) for p in pairs]
        results = await asyncio.gather(*tasks)
        
    return results


# --- 5. STREAMLIT UI ---
st.title("Smart Route Finder")
st.markdown("<p style='color: #94a3b8;'>Find hidden booking quotas instantly.</p>", unsafe_allow_html=True)

with st.container():
    col1, col2 = st.columns(2)
    
    with col1:
        # Pre-select ED (Erode) if it exists in the JSON, otherwise fallback to index 0
        default_src_idx = list(STATIONS.keys()).index("ED") if "ED" in STATIONS else 0
        src_input = st.selectbox("From", options=list(STATIONS.keys()), index=default_src_idx, format_func=lambda x: f"{x} - {STATIONS[x]}")
        
        train_input = st.text_input("Train No.", value="20630")
        
        # New Date Input formatted as YYYY-MM-DD
        date_input = st.date_input("Travel Date", min_value=datetime.today())
        # date format:
        formatted_date = date_input.strftime("%d-%m-%Y") 


    with col2:
        default_dst_idx = list(STATIONS.keys()).index("TPTY") if "TPTY" in STATIONS else 1
        dst_input = st.selectbox("To", options=list(STATIONS.keys()), index=default_dst_idx, format_func=lambda x: f"{x} - {STATIONS[x]}")
        
        cls_input = st.selectbox("Class", options=["2A", "3A", "SL", "1A"])


if st.button("Find Better Waitlist", type="primary", use_container_width=True):
    if src_input == dst_input:
        st.error("Source and Destination cannot be the same.")
    else:
        with st.spinner("Fetching live data from IRCTC via RapidAPI..."):
            
            raw_results = asyncio.run(orchestrate_search(train_input, formatted_date, cls_input, src_input, dst_input))
            
            baseline = next((r for r in raw_results if r["type"] == "baseline"), None)
            alternates = [r for r in raw_results if r["type"] != "baseline" and not r.get("error")]
            
            st.markdown("### Search Results")
            
            # Display Baseline
            if baseline:
                st.markdown(f"""
                <div class="baseline-card">
                    <div style="font-size: 12px; color: #94a3b8; margin-bottom: 8px;">ORIGINAL ROUTE</div>
                    <h4>{baseline['src']} ➔ {baseline['dst']}</h4>
                </div>
                """, unsafe_allow_html=True)
                
                b_col1, b_col2 = st.columns(2)
                b_col1.metric("Current Status", baseline['status'])
                b_col2.metric("Price", f"₹{baseline['price']}")
                
            st.divider()
            
            # Display Alternates
            if alternates:
                st.markdown("### Recommended Alternates")
                for alt in alternates:
                    # In a production app, you would add logic here to parse the WL number 
                    # and strictly show only statuses that are mathematically better.
                    st.markdown(f"""
                    <div class="hacked-card">
                        <div style="font-size: 12px; color: #10b981; font-weight: 600; margin-bottom: 8px;">ALTERNATE QUOTA FOUND</div>
                        <h4>{alt['src']} ➔ {alt['dst']}</h4>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    a_col1, a_col2, a_col3 = st.columns(3)
                    a_col1.metric("Status", alt['status'])
                    a_col2.metric("Total Fare", f"₹{alt['price']}")
                    
                    # Prevent math errors if price is missing/string
                    try:
                        extra_cost = int(alt['price']) - int(baseline['price'])
                        a_col3.metric("Cost Difference", f"₹{extra_cost}")
                    except (ValueError, TypeError):
                        a_col3.metric("Cost Difference", "N/A")
            else:
                st.info("No alternate routes could be fetched successfully.")
            
