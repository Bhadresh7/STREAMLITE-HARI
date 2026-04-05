import streamlit as st
from mongo_db import db_client
from auth import check_auth, show_sidebar_user_info, inject_login_css

# Page configuration (must be first Streamlit command)
st.set_page_config(
    page_title="Stock Analysis Hub",
    page_icon="📈",
    layout="wide"
)

# ── Authentication Gate ──
if not check_auth():
    st.stop()

# Inject shared CSS
inject_login_css()

st.markdown("""
<style>
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        text-align: center;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .sub-title {
        font-size: 1.3rem;
        text-align: center;
        color: var(--text-color);
        opacity: 0.7;
        margin-bottom: 2rem;
    }
    .page-card {
        background: rgba(128, 128, 128, 0.1);
        padding: 2rem;
        border-radius: 1rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        transition: transform 0.2s, box-shadow 0.2s;
        height: 100%;
    }
    .page-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
    }
    .page-card h3 {
        color: var(--text-color);
        margin-bottom: 0.5rem;
    }
    .page-card p {
        color: var(--text-color);
        opacity: 0.7;
    }
    .page-icon {
        font-size: 3rem;
        margin-bottom: 1rem;
    }
    .stat-box {
        background: linear-gradient(135deg, rgba(102, 126, 234, 0.15), rgba(118, 75, 162, 0.15));
        padding: 1rem 1.5rem;
        border-radius: 0.75rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        text-align: center;
    }
    .stat-box h4 {
        margin: 0 0 0.25rem 0;
        color: var(--text-color);
        opacity: 0.7;
        font-size: 0.85rem;
        text-transform: uppercase;
    }
    .stat-box p {
        margin: 0;
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--text-color);
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar user info ──
show_sidebar_user_info()

st.markdown('<div class="main-title">📈 Stock Analysis Hub</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">AI-Powered Trading Intelligence Platform</div>', unsafe_allow_html=True)

# =============================================================================
# 📊 MongoDB Dashboard Stats
# =============================================================================
if db_client.connected:
    stats = db_client.get_dashboard_stats()

    st.markdown("### 📊 Platform Statistics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.markdown(f"""
        <div class="stat-box">
            <h4>🔍 Total Scans</h4>
            <p>{stats.get('total_scans', 0)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="stat-box">
            <h4>📊 Analyses</h4>
            <p>{stats.get('total_analyses', 0)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="stat-box">
            <h4>🎯 Signals</h4>
            <p>{stats.get('total_signals', 0)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="stat-box">
            <h4>💰 Trades</h4>
            <p>{stats.get('total_trades', 0)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c5:
        st.markdown(f"""
        <div class="stat-box">
            <h4>📋 Stocks Scanned</h4>
            <p>{stats.get('unique_tickers_scanned', 0)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c6:
        st.markdown(f"""
        <div class="stat-box">
            <h4>🔬 Stocks Analyzed</h4>
            <p>{stats.get('unique_tickers_analyzed', 0)}</p>
        </div>
        """, unsafe_allow_html=True)

    st.sidebar.success("🟢 MongoDB Connected")

    # Show top analyzed tickers
    top_analyzed = db_client.get_top_analyzed_tickers(limit=5)
    if top_analyzed:
        st.sidebar.markdown("### 🔬 Top Analyzed")
        for t in top_analyzed:
            st.sidebar.markdown(f"- **{t['_id']}** — {t['count']}× (Avg Conf: {t.get('avg_confidence', 0):.0f})")
else:
    st.sidebar.error("🔴 MongoDB Disconnected")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class="page-card">
        <div class="page-icon">🔍</div>
        <h3>Automatic Stock Scanner</h3>
        <p>Scan 150+ NSE stocks automatically. Multi-factor scoring with market context analysis, 
        technical indicators, and risk management. Identifies the top 10 high-probability 
        intraday opportunities.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_📊_Stock_Scanner.py", label="Open Stock Scanner →", use_container_width=True)

with col2:
    st.markdown("""
    <div class="page-card">
        <div class="page-icon">📊</div>
        <h3>Intraday Analysis Engine</h3>
        <p>Production-grade intraday analysis with institutional features. 
        Includes directional bias locking, trade memory, session rules, 
        drawdown protection, and real-time signal generation.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_📈_Intraday_Analysis.py", label="Open Intraday Analysis →", use_container_width=True)

# Show admin panel card only for admins
if st.session_state.get('is_admin'):
    st.divider()
    st.markdown("""
    <div class="page-card" style="border-left: 3px solid #667eea;">
        <div class="page-icon">🛡️</div>
        <h3>Admin Panel</h3>
        <p>Manage platform users — create new accounts, edit roles and passwords, 
        or remove users. Only accessible to administrators.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_🛡️_Admin_Panel.py", label="Open Admin Panel →", use_container_width=True)

st.divider()

# =============================================================================
# Recent Activity from MongoDB
# =============================================================================
if db_client.connected:
    st.markdown("### 📜 Recent Activity")

    tab1, tab2, tab3 = st.tabs(["🔍 Scan History", "📊 Analysis History", "🎯 Signal Log"])

    with tab1:
        scan_history = db_client.get_scan_history(limit=10)
        if scan_history:
            import pandas as pd
            rows = []
            for run in scan_history:
                ts = run.get('timestamp', '')
                if hasattr(ts, 'strftime'):
                    ts = ts.strftime('%Y-%m-%d %H:%M')
                rows.append({
                    'Time': ts,
                    'Stocks Scanned': run.get('total_stocks_scanned', 0),
                    'Results': run.get('qualifying_results', 0),
                    'Market Bias': run.get('market_bias', 'N/A'),
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.info("No scan history yet. Run your first scan!")

    with tab2:
        import pandas as pd
        # Get recent analysis from all tickers
        recent_analyses = list(db_client.analysis_collection.find().sort('timestamp', -1).limit(15)) if db_client.connected else []
        if recent_analyses:
            rows = []
            for a in recent_analyses:
                ts = a.get('timestamp', '')
                if hasattr(ts, 'strftime'):
                    ts = ts.strftime('%Y-%m-%d %H:%M')
                rows.append({
                    'Time': ts,
                    'Ticker': a.get('ticker', ''),
                    'Signal': a.get('signal', ''),
                    'Confidence': f"{a.get('confidence_score', 0):.0f}/100",
                    'Trend': a.get('trend', ''),
                    'Bias': a.get('primary_bias', ''),
                    'VIX': f"{a.get('vix', 0):.1f}",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.info("No analysis history yet.")

    with tab3:
        signal_history = db_client.get_signal_history(limit=15)
        if signal_history:
            import pandas as pd
            rows = []
            for s in signal_history:
                ts = s.get('timestamp', '')
                if hasattr(ts, 'strftime'):
                    ts = ts.strftime('%Y-%m-%d %H:%M')
                rows.append({
                    'Time': ts,
                    'Ticker': s.get('ticker', ''),
                    'Signal': s.get('signal', ''),
                    'Entry': f"₹{s.get('entry', 0):.2f}",
                    'SL': f"₹{s.get('stop_loss', 0):.2f}",
                    'R:R': f"{s.get('risk_reward', 0):.2f}",
                    'Confidence': f"{s.get('confidence', 0):.0f}",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.info("No signals logged yet.")

st.divider()

st.markdown("### 🔗 Quick Navigation")
st.info("👈 Use the **sidebar** to navigate between pages, or click the links above.")

st.markdown("""
### ⚠️ Disclaimer
- This platform provides **probability-based analysis**, not trading predictions
- News events and gaps can override technical signals  
- Always use proper position sizing and risk management
- Past performance does not guarantee future results
""")
