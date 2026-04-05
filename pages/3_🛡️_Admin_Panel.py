import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_db import db_client
from auth import check_auth, show_sidebar_user_info, inject_login_css

# ── Authentication Gate ──
if not check_auth():
    st.stop()

# ── Admin-only access ──
if not st.session_state.get('is_admin', False):
    st.error("🚫 Access Denied — This page is only available to administrators.")
    st.stop()

inject_login_css()
show_sidebar_user_info()

# ── Page CSS ──
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    .admin-header {
        font-family: 'Inter', sans-serif;
        font-size: 2.2rem;
        font-weight: 800;
        text-align: center;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.25rem;
    }
    .admin-subtitle {
        text-align: center;
        color: var(--text-color);
        opacity: 0.55;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .stat-row { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
    .stat-card {
        flex: 1;
        background: linear-gradient(135deg, rgba(102,126,234,0.1), rgba(118,75,162,0.1));
        border: 1px solid rgba(102,126,234,0.2);
        border-radius: 0.75rem;
        padding: 1rem;
        text-align: center;
    }
    .stat-val {
        font-size: 1.8rem; font-weight: 800;
        background: linear-gradient(135deg, #667eea, #764ba2);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .stat-lbl { font-size: 0.78rem; opacity: 0.55; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 0.2rem; }
    .section-title {
        font-family: 'Inter', sans-serif;
        font-size: 1.2rem; font-weight: 700;
        margin-top: 1rem; margin-bottom: 0.75rem;
        padding-bottom: 0.4rem;
        border-bottom: 2px solid rgba(102,126,234,0.25);
    }
    .user-row {
        background: rgba(128,128,128,0.06);
        border: 1px solid rgba(128,128,128,0.15);
        border-radius: 0.75rem;
        padding: 1rem 1.25rem;
        margin-bottom: 0.6rem;
    }
    .badge-admin {
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: #fff; padding: 2px 10px; border-radius: 1rem; font-size: 0.72rem; font-weight: 600;
    }
    .badge-user {
        background: rgba(128,128,128,0.2);
        color: var(--text-color); padding: 2px 10px; border-radius: 1rem; font-size: 0.72rem; font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# HEADER
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="admin-header">🛡️ Admin Panel</div>', unsafe_allow_html=True)
st.markdown('<div class="admin-subtitle">User management · Activity history · Audit trail</div>', unsafe_allow_html=True)

# Fetch all users
users = db_client.get_all_users()
total_users = len(users)
admin_count = sum(1 for u in users if u.get('is_admin'))
regular_count = total_users - admin_count

st.markdown(f"""
<div class="stat-row">
    <div class="stat-card"><div class="stat-val">{total_users}</div><div class="stat-lbl">Total Users</div></div>
    <div class="stat-card"><div class="stat-val">{admin_count}</div><div class="stat-lbl">Admins</div></div>
    <div class="stat-card"><div class="stat-val">{regular_count}</div><div class="stat-lbl">Users</div></div>
</div>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
# SEARCH BAR — filter by username
# ═════════════════════════════════════════════════════════════════════════════
usernames = ['All Users'] + [u['username'] for u in users]
search_col1, search_col2 = st.columns([3, 1])
with search_col1:
    search_query = st.text_input("🔍 Search user by name", placeholder="Type a username to filter…", key="user_search")
with search_col2:
    selected_user = st.selectbox("Or select user", usernames, key="user_select")

# Determine effective filter
filter_username = None
if search_query and search_query.strip():
    filter_username = search_query.strip().lower()
elif selected_user != 'All Users':
    filter_username = selected_user

# ═════════════════════════════════════════════════════════════════════════════
# TABS — User Management | Login History | Search History | Scan History | Analysis History
# ═════════════════════════════════════════════════════════════════════════════
tab_users, tab_login, tab_search, tab_scan, tab_analysis = st.tabs([
    "👥 Users", "🔐 Login History", "🔍 Search History", "📊 Scan History", "📈 Analysis History"
])

# ── Helper: format timestamp ──
def fmt_ts(ts):
    if hasattr(ts, 'strftime'):
        return ts.strftime('%Y-%m-%d %H:%M:%S UTC')
    return str(ts) if ts else 'N/A'

# ═══════════════════════════════════════════
# TAB 1 — USER MANAGEMENT
# ═══════════════════════════════════════════
with tab_users:
    # ── Create User ──
    st.markdown('<div class="section-title">➕ Create New User</div>', unsafe_allow_html=True)
    with st.form("create_user_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            new_username = st.text_input("Username", placeholder="e.g. john_doe", key="nu")
        with c2:
            new_password = st.text_input("Password", type="password", placeholder="Min 4 chars", key="np")
        with c3:
            new_role = st.selectbox("Role", ["User", "Admin"], key="nr")
        if st.form_submit_button("✅ Create User", use_container_width=True, type="primary"):
            if not new_username or not new_password:
                st.error("⚠️ Username and password required.")
            elif len(new_password) < 4:
                st.error("⚠️ Password too short (min 4 chars).")
            elif len(new_username.strip()) < 3:
                st.error("⚠️ Username too short (min 3 chars).")
            else:
                ok = db_client.create_user(new_username.strip().lower(), new_password, is_admin=(new_role == "Admin"))
                if ok:
                    st.success(f"✅ User **{new_username.strip().lower()}** created!")
                    st.rerun()
                else:
                    st.error(f"❌ Username already exists.")

    st.divider()

    # ── User List (filtered) ──
    st.markdown('<div class="section-title">👥 All Users</div>', unsafe_allow_html=True)

    display_users = users
    if filter_username:
        display_users = [u for u in users if filter_username in u.get('username', '').lower()]

    if not display_users:
        st.info("No users match the filter.")
    else:
        for user in display_users:
            uname = user.get('username', '')
            is_admin = user.get('is_admin', False)
            created = fmt_ts(user.get('created_at', ''))
            badge = '<span class="badge-admin">ADMIN</span>' if is_admin else '<span class="badge-user">USER</span>'

            st.markdown(f"""
            <div class="user-row">
                <strong>👤 {uname}</strong> {badge}<br>
                <small style="opacity:0.5">Created: {created}</small>
            </div>
            """, unsafe_allow_html=True)

            col_edit, col_del = st.columns(2)
            with col_edit:
                with st.expander(f"✏️ Edit {uname}"):
                    with st.form(f"edit_{uname}"):
                        pw = st.text_input("New password (blank = keep)", type="password", key=f"pw_{uname}")
                        role = st.selectbox("Role", ["Admin", "User"], index=0 if is_admin else 1, key=f"rl_{uname}")
                        if st.form_submit_button("💾 Save", use_container_width=True):
                            upd = {'is_admin': (role == "Admin")}
                            if pw:
                                if len(pw) < 4:
                                    st.error("Password too short.")
                                else:
                                    upd['password'] = pw
                            if db_client.update_user(uname, upd):
                                st.success(f"✅ Updated {uname}")
                                st.rerun()
                            else:
                                st.error("❌ Update failed.")

            with col_del:
                if uname != 'admin':
                    if st.button(f"🗑️ Delete {uname}", key=f"del_{uname}"):
                        st.session_state[f'cdel_{uname}'] = True
                    if st.session_state.get(f'cdel_{uname}'):
                        st.warning(f"Delete **{uname}**? This cannot be undone.")
                        y, n = st.columns(2)
                        with y:
                            if st.button("Yes, delete", key=f"cy_{uname}", type="primary"):
                                if db_client.delete_user(uname):
                                    st.success(f"Deleted {uname}")
                                    st.session_state.pop(f'cdel_{uname}', None)
                                    st.rerun()
                        with n:
                            if st.button("Cancel", key=f"cn_{uname}"):
                                st.session_state.pop(f'cdel_{uname}', None)
                                st.rerun()
                else:
                    st.caption("🔒 Primary admin protected")

            st.markdown("---")


# ═══════════════════════════════════════════
# TAB 2 — LOGIN HISTORY
# ═══════════════════════════════════════════
with tab_login:
    st.markdown('<div class="section-title">🔐 Login History</div>', unsafe_allow_html=True)
    logins = db_client.get_login_history(username=filter_username, limit=200)
    if logins:
        rows = []
        for l in logins:
            rows.append({
                'Time': fmt_ts(l.get('timestamp')),
                'Username': l.get('username', ''),
                'IP Address': l.get('ip_address', 'N/A'),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(f"Showing {len(rows)} login records" + (f" for **{filter_username}**" if filter_username else ""))
    else:
        st.info("No login history found." + (f" (filter: {filter_username})" if filter_username else ""))


# ═══════════════════════════════════════════
# TAB 3 — SEARCH HISTORY
# ═══════════════════════════════════════════
with tab_search:
    st.markdown('<div class="section-title">🔍 Search History</div>', unsafe_allow_html=True)
    searches = db_client.get_user_search_history(username=filter_username, limit=200)
    if searches:
        rows = []
        for s in searches:
            details = s.get('details', {})
            rows.append({
                'Time': fmt_ts(s.get('timestamp')),
                'Username': s.get('username', ''),
                'Ticker': s.get('ticker', ''),
                'Signal': details.get('signal', '') if isinstance(details, dict) else '',
                'Confidence': details.get('confidence_score', '') if isinstance(details, dict) else '',
                'Trend': details.get('trend', '') if isinstance(details, dict) else '',
                'Price': details.get('current_price', '') if isinstance(details, dict) else '',
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(f"Showing {len(rows)} search records" + (f" for **{filter_username}**" if filter_username else ""))
    else:
        st.info("No search history found." + (f" (filter: {filter_username})" if filter_username else ""))


# ═══════════════════════════════════════════
# TAB 4 — SCAN HISTORY
# ═══════════════════════════════════════════
with tab_scan:
    st.markdown('<div class="section-title">📊 Scan History</div>', unsafe_allow_html=True)
    scans = db_client.get_user_scan_history(username=filter_username, limit=200)
    if scans:
        rows = []
        for s in scans:
            rows.append({
                'Time': fmt_ts(s.get('timestamp')),
                'Username': s.get('username', ''),
                'Stocks Scanned': s.get('total_stocks_scanned', 0),
                'Results Found': s.get('qualifying_results', 0),
                'Market Bias': s.get('market_bias', 'N/A'),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(f"Showing {len(rows)} scan records" + (f" for **{filter_username}**" if filter_username else ""))

        # Show detailed scan results for the selected user
        if filter_username:
            st.markdown("#### 📋 Detailed Scan Results")
            scan_results = list(db_client.scan_results_collection.find(
                {'username': filter_username}
            ).sort('scan_timestamp', -1).limit(50))
            if scan_results:
                detail_rows = []
                for r in scan_results:
                    ctx = r.get('market_context', {})
                    detail_rows.append({
                        'Time': fmt_ts(r.get('scan_timestamp')),
                        'Rank': r.get('rank', 0),
                        'Symbol': r.get('symbol', ''),
                        'Price': f"₹{r.get('current_price', 0):.2f}",
                        'Score': round(r.get('total_score', 0), 2),
                        'Bias': r.get('bias', ''),
                        'Confidence': r.get('confidence', ''),
                        'Expected % Low': f"{r.get('expected_pct_low', 0):.2f}%",
                        'Expected % High': f"{r.get('expected_pct_high', 0):.2f}%",
                        'SL': f"₹{r.get('stop_loss', 0):.2f}",
                        'Target': f"₹{r.get('target', 0):.2f}",
                        'ATR': round(r.get('atr', 0), 2),
                        'RSI': round(r.get('rsi', 0), 2),
                        'Vol Ratio': round(r.get('volume_ratio', 0), 2),
                        'Mkt Bias': ctx.get('bias', ''),
                        'NIFTY': f"₹{ctx.get('nifty_price', 0):.2f}",
                    })
                st.dataframe(pd.DataFrame(detail_rows), hide_index=True, use_container_width=True)
            else:
                st.info("No detailed scan results for this user.")
    else:
        st.info("No scan history found." + (f" (filter: {filter_username})" if filter_username else ""))


# ═══════════════════════════════════════════
# TAB 5 — ANALYSIS HISTORY
# ═══════════════════════════════════════════
with tab_analysis:
    st.markdown('<div class="section-title">📈 Analysis History</div>', unsafe_allow_html=True)
    analyses = db_client.get_user_analysis_history(username=filter_username, limit=200)
    if analyses:
        rows = []
        for a in analyses:
            rows.append({
                'Time': fmt_ts(a.get('timestamp')),
                'Username': a.get('username', ''),
                'Ticker': a.get('ticker', ''),
                'Price': f"₹{a.get('current_price', 0):.2f}",
                'Signal': a.get('signal', ''),
                'Reason': a.get('signal_reason', ''),
                'Entry': f"₹{a.get('entry_price', 0):.2f}",
                'SL': f"₹{a.get('stop_loss', 0):.2f}",
                'T1': f"₹{a.get('target1', 0):.2f}",
                'T2': f"₹{a.get('target2', 0):.2f}",
                'T3': f"₹{a.get('target3', 0):.2f}",
                'R:R': round(a.get('risk_reward', 0), 2),
                'Confidence': f"{a.get('confidence_score', 0):.0f}/100",
                'Level': a.get('confidence_level', ''),
                'Strategy': a.get('strategy_tag', ''),
                'Trend': a.get('trend', ''),
                'RSI': round(a.get('rsi', 0), 2),
                'VWAP': f"₹{a.get('vwap', 0):.2f}",
                'Support': f"₹{a.get('support', 0):.2f}",
                'Resistance': f"₹{a.get('resistance', 0):.2f}",
                'Regime': a.get('market_regime', ''),
                'Session': a.get('session_name', ''),
                'Bias': a.get('primary_bias', ''),
                'Bias Str': round(a.get('bias_strength', 0), 1),
                'Structure': a.get('structure_bias', ''),
                'HTF': a.get('htf_bias', ''),
                'LTF': a.get('ltf_bias', ''),
                'MTF Aligned': '✅' if a.get('mtf_aligned') else '❌',
                'Volatility': a.get('volatility_regime', ''),
                'Order Flow': a.get('order_flow', ''),
                'NIFTY Bias': a.get('nifty_bias', ''),
                'VIX': round(a.get('vix', 0), 1),
                'Vol Quality': a.get('volume_quality', ''),
                'Vol Ratio': round(a.get('volume_ratio', 0), 2),
                'Position Size': a.get('position_size', ''),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(f"Showing {len(rows)} analysis records" + (f" for **{filter_username}**" if filter_username else ""))

        # Signal log sub-section
        st.markdown("#### 🎯 Signal Log")
        signals = db_client.get_user_signal_history(username=filter_username, limit=200)
        if signals:
            sig_rows = []
            for s in signals:
                sig_rows.append({
                    'Time': fmt_ts(s.get('timestamp')),
                    'Username': s.get('username', ''),
                    'Ticker': s.get('ticker', ''),
                    'Signal': s.get('signal', ''),
                    'Entry': f"₹{s.get('entry', 0):.2f}",
                    'SL': f"₹{s.get('stop_loss', 0):.2f}",
                    'T1': f"₹{s.get('target1', 0):.2f}",
                    'T2': f"₹{s.get('target2', 0):.2f}",
                    'T3': f"₹{s.get('target3', 0):.2f}",
                    'R:R': round(s.get('risk_reward', 0), 2),
                    'Strategy': s.get('strategy_tag', ''),
                    'Confidence': s.get('confidence', ''),
                    'Reason': s.get('reason', ''),
                })
            st.dataframe(pd.DataFrame(sig_rows), hide_index=True, use_container_width=True)
        else:
            st.info("No signal records found.")
    else:
        st.info("No analysis history found." + (f" (filter: {filter_username})" if filter_username else ""))
