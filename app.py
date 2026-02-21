import streamlit as st
import os
from main import run_council

# 1. Config (MUST be the first command)
st.set_page_config(page_title="Silicon Council", page_icon="🦁", layout="wide")

# 2. CSS: Hide Streamlit UI & Fix Mobile Tables
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        .stDeployButton {display:none;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stDataFrame { overflow-x: auto; }
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 5px; }
        .stTabs [aria-selected="true"] { background-color: #ff4b4b; color: white; }
    </style>
""", unsafe_allow_html=True)

# 3. App Header
st.title("🦁 The Silicon Council")
st.markdown("### *Artificial Intelligence Investment Committee*")

# --- 4. Input Section (MODIFIED FOR ENTER KEY SUPPORT) ---
# We wrap the inputs in a form. The 'key' ensures Streamlit knows it's a form.
with st.form(key="search_form"):
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Pressing Enter here will now submit the form!
        ticker = st.text_input("Ticker Symbol", placeholder="e.g. BABA, META").upper()
        
    with col2:
        deep_dive = st.checkbox("Deep Dive?", value=True)
    
    # CRITICAL CHANGE: Use form_submit_button instead of regular button
    run_btn = st.form_submit_button("🚀 Convene Council", type="primary")

# 5. Execution Section
if run_btn and ticker:
    
    # --- A. Create the Status Box ---
    status_box = st.status(f"🕵️‍♂️ Investigating {ticker}...", expanded=True)
    
    try:
        status_box.write("Generating Financial Matrix...")
        status_box.write("Consulting Munger & Feynman...")

        # 📈 VISUAL: Stock Price Chart (1 Year)
        st.subheader(f"📉 {ticker} Price Trend (1Y)")
        try:
            import yfinance as yf
            chart_data = yf.Ticker(ticker).history(period="1y")['Close']
            st.line_chart(chart_data)
        except:
            st.warning("Could not load stock chart.")
        
        # --- C. Run the Council ---
        files = run_council(
            ticker, 
            verbose=deep_dive, 
            save_markdown=True
        )
        
        # Close the box
        status_box.update(label="✅ Analysis Complete!", state="complete", expanded=False)
        
        # --- D. Display the Tabs ---
        if files:
            tab1, tab2, tab3 = st.tabs(["🍷 Explained Simply", "🧠 Deep Dive", "👴 Reality Check"])
            
            # Tab 1: Simple
            with tab1:
                if isinstance(files, dict) and files.get("simple") and os.path.exists(files["simple"]):
                    with open(files["simple"], "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                else:
                    st.info("Simple report not generated.")
            
            # Tab 2: Full
            with tab2:
                full_path = files["full"] if isinstance(files, dict) else files
                
                if full_path and os.path.exists(full_path):
                    with open(full_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                else:
                    st.error("Full report file not found.")
            
            with tab3:
                if isinstance(files, dict) and files.get("full"):
                    # We can't easily parse just the reality check from the full file without regex
                    # So simpler solution: The "Deep Dive" tab already contains it at the bottom!
                    st.info("The Reality Check is included at the end of the Deep Dive report.")
                    # OR, you can save it as a separate file in main.py if you really want a dedicated tab.
            
    except Exception as e:
        status_box.update(label="❌ Council Crashed", state="error")
        st.error(f"Error: {e}")