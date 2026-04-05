import streamlit as st
from mongo_db import db_client


def inject_login_css():
    """Inject premium CSS shared across all pages"""
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

        /* ── Sidebar user badge ── */
        .user-badge {
            background: linear-gradient(135deg, rgba(102,126,234,0.15), rgba(118,75,162,0.15));
            border: 1px solid rgba(102,126,234,0.3);
            border-radius: 0.75rem;
            padding: 0.75rem 1rem;
            margin-bottom: 1rem;
        }
        .user-badge-name {
            font-weight: 700;
            font-size: 1rem;
            color: var(--text-color);
        }
        .user-badge-role {
            font-size: 0.8rem;
            opacity: 0.6;
            color: var(--text-color);
        }
    </style>
    """, unsafe_allow_html=True)


def _classic_login_css():
    """Full-page centered login with classic dark theme"""
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

        /* ── Hide sidebar & header on login ── */
        [data-testid="stSidebar"] { display: none !important; }
        header[data-testid="stHeader"] { display: none !important; }
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }

        /* ── Force main content to center vertically ── */
        .stApp > .main > .block-container {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 100vh !important;
            max-width: 100% !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }

        /* ── Login card ── */
        .login-card {
            background: #16213e;
            border: 1px solid #2a3a5c;
            border-radius: 16px;
            padding: 48px 40px 36px;
            width: 400px;
            max-width: 90vw;
            box-shadow: 0 12px 40px rgba(0,0,0,0.5);
            margin: 0 auto;
        }

        .login-card .logo {
            text-align: center;
            font-size: 52px;
            margin-bottom: 8px;
        }

        .login-card .title {
            font-family: 'Inter', sans-serif;
            text-align: center;
            font-size: 24px;
            font-weight: 700;
            color: #e8e8e8;
            margin-bottom: 4px;
        }

        .login-card .subtitle {
            font-family: 'Inter', sans-serif;
            text-align: center;
            font-size: 13px;
            color: #7a8ba8;
            margin-bottom: 32px;
        }

        .login-card .footer {
            text-align: center;
            font-size: 11px;
            color: #4a5568;
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid #2a3a5c;
        }

        .err-box {
            background: rgba(220, 53, 69, 0.1);
            border: 1px solid rgba(220, 53, 69, 0.3);
            color: #ff6b6b;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
            font-size: 13px;
            margin-top: 8px;
        }
    </style>
    """, unsafe_allow_html=True)


def show_login_page():
    """Render a perfectly centered classic login page."""
    _classic_login_css()

    # Card header (pure HTML for styling)
    st.markdown("""
    <div class="login-card">
        <div class="logo">📈</div>
        <div class="title">Stock Analysis Hub</div>
        <div class="subtitle">Enter your credentials to continue</div>
    </div>
    """, unsafe_allow_html=True)

    # Streamlit form (centered via CSS on parent .block-container)
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", placeholder="Enter username")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if submitted:
            if not username or not password:
                st.markdown(
                    '<div class="err-box">Please enter both username and password</div>',
                    unsafe_allow_html=True,
                )
                return False

            user = db_client.verify_user(username.strip(), password)
            if user:
                st.session_state['authenticated'] = True
                st.session_state['username'] = user['username']
                st.session_state['is_admin'] = user.get('is_admin', False)
                db_client.log_login(user['username'])
                st.rerun()
            else:
                st.markdown(
                    '<div class="err-box">Invalid username or password</div>',
                    unsafe_allow_html=True,
                )
                return False

    st.markdown(
        '<div style="text-align:center;font-size:11px;color:#4a5568;margin-top:12px;">'
        '© 2026 Stock Analysis Hub · Secure Login</div>',
        unsafe_allow_html=True,
    )
    return False


def check_auth():
    """
    Gate-check for authentication.
    Call at the top of every page. Returns True if user is authenticated.
    If not authenticated, renders the login page and stops execution.
    """
    if not db_client.connected:
        st.error("🔴 Database is not connected. Cannot authenticate.")
        st.stop()
        return False

    if st.session_state.get('authenticated'):
        return True

    show_login_page()
    st.stop()
    return False


def show_sidebar_user_info():
    """Display user info and logout button in the sidebar."""
    username = st.session_state.get('username', 'Unknown')
    is_admin = st.session_state.get('is_admin', False)
    role_label = "🛡️ Administrator" if is_admin else "👤 User"

    st.sidebar.markdown(f"""
    <div class="user-badge">
        <div class="user-badge-name">👋 {username}</div>
        <div class="user-badge-role">{role_label}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("🚪 Logout", use_container_width=True):
        for key in ['authenticated', 'username', 'is_admin']:
            st.session_state.pop(key, None)
        st.rerun()

    # ── Hide Admin Panel from sidebar for non-admins ──
    if not is_admin:
        st.markdown("""
        <style>
            /* Hide the Admin Panel link in the sidebar by targeting its href */
            [data-testid="stSidebarNav"] a[href*="Admin_Panel"] {
                display: none !important;
            }
        </style>
        """, unsafe_allow_html=True)
