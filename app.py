import streamlit as st
import asyncio
import aiohttp
import pandas as pd
import time

# --- 1. UI CONFIGURATION & CUSTOM CSS ---
st.set_page_config(page_title="SmartWL | Alternate Routes", layout="centered", initial_sidebar_state="collapsed")

# Injecting premium dark-theme CSS (Minimalist, High-Contrast)
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


# --- 2. MOCK DATA LAYER (Simulating local SQLite DB) ---
# In production, replace this with a local SQLite DB query
STATIONS = {"PGT": "Palakkad", "CBE": "Coimbatore", "TUP": "Tiruppur", "ED": "Erode", 
            "SA": "Salem", "KPD": "Katpadi", "TPTY": "Tirupati", "RU": "Renigunta"}
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
async def fetch_availability(session, train, cls, src, dst, p_type):
    """
    Mock asynchronous API call. Replace the sleep and mock data with an actual aiohttp 
    request to your RapidAPI endpoint when you are ready.
    """
    await asyncio.sleep(0.8) # Simulate network latency
    
    # Mocking the specific scenario
    status, price = "WL 15", 980
    if p_type == "baseline":
        status, price = "WL 11", 980
    elif src == "PGT" and dst == "RU":
        status, price = "WL 3", 1300
    elif src == "CBE" and dst == "TPTY":
        status, price = "WL 8", 1100

    return {"src": src, "dst": dst, "type": p_type, "status": status, "price": price}

async def orchestrate_search(train, cls, src, dst):
    pairs = generate_pairs(TRAIN_ROUTE, src, dst, spread=2)
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_availability(session, train, cls, p["src"], p["dst"], p["type"]) for p in pairs]
        results = await asyncio.gather(*tasks)
        
    return results


# --- 5. STREAMLIT UI ---
st.title("Smart Route Finder")
st.markdown("<p style='color: #94a3b8;'>Find hidden booking quotas instantly.</p>", unsafe_allow_html=True)

with st.container():
    col1, col2 = st.columns(2)
    with col1:
        src_input = st.selectbox("From", options=list(STATIONS.keys()), index=3, format_func=lambda x: f"{x} - {STATIONS[x]}")
        train_input = st.text_input("Train No.", value="20630")
    with col2:
        dst_input = st.selectbox("To", options=list(STATIONS.keys()), index=6, format_func=lambda x: f"{x} - {STATIONS[x]}")
        cls_input = st.selectbox("Class", options=["2A", "3A", "SL"])

if st.button("Find Better Waitlist", type="primary", use_container_width=True):
    if src_input == dst_input:
        st.error("Source and Destination cannot be the same.")
    else:
        with st.spinner("Executing concurrent API checks..."):
            # Run the asynchronous fan-out
            raw_results = asyncio.run(orchestrate_search(train_input, cls_input, src_input, dst_input))
            
            baseline = next((r for r in raw_results if r["type"] == "baseline"), None)
            alternates = [r for r in raw_results if r["type"] != "baseline"]
            
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
            # In production, parse "WL 11" to check if numeric WL is actually lower
            better_alts = [alt for alt in alternates if alt['status'] in ["WL 3", "WL 8"]] 
            
            if better_alts:
                st.markdown("### Recommended Alternates")
                for alt in better_alts:
                    st.markdown(f"""
                    <div class="hacked-card">
                        <div style="font-size: 12px; color: #10b981; font-weight: 600; margin-bottom: 8px;">BETTER QUOTA FOUND</div>
                        <h4>{alt['src']} ➔ {alt['dst']}</h4>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    a_col1, a_col2, a_col3 = st.columns(3)
                    a_col1.metric("Status", alt['status'], delta="Higher Chance", delta_color="normal")
                    a_col2.metric("Total Fare", f"₹{alt['price']}")
                    a_col3.metric("Extra Cost", f"₹{alt['price'] - baseline['price']}", delta_color="inverse")
            else:
                st.info("No better alternate routes found for this train.")
      
