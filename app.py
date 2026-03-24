import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from datetime import datetime, timedelta
import numpy as np
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
import pytz
from mongo_db import db_client

st.set_page_config(page_title="Intraday Analysis", page_icon="📊", layout="wide")

# Auth Guard
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = 'guest'
if 'username' not in st.session_state:
    st.session_state.username = ''

if not st.session_state.logged_in:
    st.title("🔐 Login Required")
    st.markdown("Please sign in to access the Institutional-Grade Trading Engine")
    
    if not db_client.connected:
        st.error("🚨 Database Connection Failed! Please check your MongoDB URI or network settings.")
        st.info("Falling back to local session state (Data won't persist across restarts).")
        
    # Simple centered layout for login
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
            
            if submitted:
                user = db_client.verify_user(username, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_role = 'admin' if user.get('is_admin') else 'user'
                    st.session_state.username = username
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid username or password")
    
    st.stop()  # Prevents rest of application from loading

# Sidebar Navigation (Logout / Admin Panel)
st.sidebar.markdown(f"**Logged in as: {st.session_state.username}**")
if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.user_role = 'guest'
    st.session_state.username = ''
    st.rerun()

if st.session_state.user_role == 'admin':
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Administrator")
    page_sel = st.sidebar.radio("Navigation", ["Trading Engine", "User Management"])
    if page_sel == "User Management":
        st.title("👥 User Management (Admin Only)")
        st.markdown("Create new credentials for traders.")
        
        with st.form("create_user_form"):
            new_user = st.text_input("New Username")
            new_pass = st.text_input("New Password", type="password")
            is_admin_acc = st.checkbox("Grant Admin Privileges")
            create_submitted = st.form_submit_button("Create User")
            
            if create_submitted:
                if len(new_user) > 3 and len(new_pass) > 3:
                    if db_client.create_user(new_user, new_pass, is_admin_acc):
                        st.success(f"User {new_user} created successfully!")
                    else:
                        st.error("User creation failed. Username might already exist.")
                else:
                    st.error("Username and Password must be at least 4 characters")
                    
        st.markdown("---")
        st.markdown("### 📊 User Search History")
        search_history = db_client.get_all_users_searches()
        if search_history:
            for username, searches in search_history.items():
                with st.expander(f"Search Activity: {username}"):
                    if not searches:
                        st.write("No recent searches.")
                    else:
                        for s in searches:
                            details = s.get('details', {})
                            interval_str = details.get('interval', 'N/A')
                            points_str = details.get('data_points', 0)
                            sig = details.get('signal', 'WAIT')
                            
                            st.markdown(f"**{s['ticker']}** @ {s['time'].strftime('%m-%d %H:%M UTC')}")
                            
                            log_text = f"🛡️ System Status: ✅ All Safety Layers Active\n"
                            log_text += f"📊 Ready to analyze: {s['ticker']}\n"
                            log_text += f"🔍 Attempting to fetch {s['ticker']} ({interval_str})...\n"
                            
                            if points_str:
                                log_text += f"✅ Successfully fetched {points_str} data points for {s['ticker']}\n"
                            else:
                                log_text += f"❌ Data fetch error or Safe Mode Blocked\n"
                                
                            if sig and sig not in ["N/A"]:
                                log_text += f"🤖 AI Signal Generated: {sig}"
                                if sig not in ["WAIT", "SAFE MODE BLOCK", "FAILED TO FETCH"]:
                                    log_text += f" (Conf: {details.get('confidence', 'N/A')})\n"
                                    log_text += f"💵 Entry: ₹{details.get('entry', 'N/A')} | Target-1: ₹{details.get('target_1', 'N/A')} | SL: ₹{details.get('stop_loss', 'N/A')}\n"
                                    log_text += f"📝 Reason: {details.get('reason', 'N/A')}\n"
                                else:
                                    log_text += "\n"
                                    if 'reason' in details:
                                        log_text += f"📝 Reason: {details.get('reason', 'N/A')}\n"
                                        
                            st.code(log_text)
        else:
            st.info("No search history logged yet.")
            
        st.stop()


# Custom CSS
st.markdown("""
    <style>
    .stMetric { background-color: rgba(128, 128, 128, 0.1); padding: 15px; border-radius: 10px; }
    h1 { color: #4CAF50; }
    .buy-signal { background-color: rgba(76, 175, 80, 0.15); padding: 10px; border-radius: 5px; border-left: 4px solid #4CAF50; }
    .sell-signal { background-color: rgba(244, 67, 54, 0.15); padding: 10px; border-radius: 5px; border-left: 4px solid #f44336; }
    .neutral-signal { background-color: rgba(255, 193, 7, 0.15); padding: 10px; border-radius: 5px; border-left: 4px solid #FFC107; }
    .no-trade-zone { background-color: rgba(255, 87, 34, 0.15); padding: 15px; border-radius: 5px; border-left: 4px solid #FF5722; }
    </style>
""", unsafe_allow_html=True)

# IST Timezone
IST = pytz.timezone('Asia/Kolkata')

# Initialize Session State for Memory & Trade Tracking
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []  # All trades across all tickers
if 'ticker_memory' not in st.session_state:
    st.session_state.ticker_memory = {}  # Per-ticker analysis
if 'directional_bias' not in st.session_state:
    st.session_state.directional_bias = {}  # Locked bias per ticker
if 'last_trade_time' not in st.session_state:
    st.session_state.last_trade_time = {}  # Cooldown tracking
if 'daily_trade_count' not in st.session_state:
    st.session_state.daily_trade_count = {'date': None, 'total': 0, 'per_ticker': {}}
if 'consecutive_losses' not in st.session_state:
    st.session_state.consecutive_losses = 0
if 'forced_break_until' not in st.session_state:
    st.session_state.forced_break_until = None

# Market Session Configuration
MARKET_SESSIONS = {
    "Opening": {"start": "09:15", "end": "10:00", "rules": "Scalps only, Target-1 only"},
    "Best": {"start": "10:00", "end": "11:30", "rules": "Full setups allowed"},
    "Midday": {"start": "11:30", "end": "13:30", "rules": "❌ No trade"},
    "Late": {"start": "13:30", "end": "14:45", "rules": "Trend continuation only"},
    "Closing": {"start": "14:45", "end": "15:30", "rules": "❌ No fresh entries"}
}

# =============================================================================
# INSTITUTIONAL UPGRADES - PRODUCTION-GRADE COMPONENTS
# =============================================================================

def validate_data_integrity(df, ticker=""):
    """
    FAIL-SAFE: Data validation gate before any analysis
    Returns: (is_valid, quality_score, error_message)
    """
    if df is None:
        return False, 0, "Data is None"
    
    # Check if this is an index (indices may have zero volume)
    is_index = ticker.startswith('^')
    
    # Check 1: Minimum candles
    if len(df) < 50:
        return False, 0, f"Insufficient data - Need 50 candles, got {len(df)}"
    
    # Check 2: No NaN in critical columns
    critical_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    if df[critical_cols].isna().any().any():
        nan_count = df[critical_cols].isna().sum().sum()
        if nan_count > 2:
            return False, 0, f"Data quality issue - {nan_count} missing values"
        else:
            # Forward fill small gaps
            df.fillna(method='ffill', limit=2, inplace=True)
    
    # Check 3: Logical price consistency
    invalid_candles = (df['High'] < df['Low']).sum()
    if invalid_candles > 0:
        return False, 0, f"Data corruption - {invalid_candles} invalid OHLC candles"
    
    # Check 4: Volume sanity (skip for indices)
    if not is_index:
        if df['Volume'].sum() == 0:
            return False, 0, "Zero volume detected - Ticker may be halted"
    
    # Check 5: Calculate quality score
    quality_score = 100
    if not is_index:
        zero_volume_candles = (df['Volume'] == 0).sum()
        if zero_volume_candles > 0:
            quality_score -= min(30, zero_volume_candles * 5)
    
    return True, quality_score, "Data validated"

def fetch_market_context():
    """
    Fetch NIFTY 50 and India VIX for market direction intelligence
    Returns: dict with market context
    Enhanced with retry logic and better error handling
    """
    import time
    
    # Default fallback values
    default_return = {
        'nifty_bias': 'UNKNOWN',
        'nifty_change': 0,
        'vix': 15,
        'risk_level': 'MODERATE',
        'error': None
    }
    
    max_retries = 2
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            # Fetch NIFTY 50 with timeout handling
            nifty = yf.Ticker("^NSEI")
            nifty_data = nifty.history(period="2d", interval="15m", timeout=10)
            
            if nifty_data is not None and not nifty_data.empty and len(nifty_data) > 0:
                nifty_current = nifty_data['Close'].iloc[-1]
                nifty_prev = nifty_data['Close'].iloc[-20] if len(nifty_data) >= 20 else nifty_data['Close'].iloc[0]
                nifty_change = ((nifty_current - nifty_prev) / nifty_prev) * 100
                
                # Determine NIFTY direction
                if nifty_change > 0.5:
                    nifty_bias = "BULLISH"
                elif nifty_change < -0.5:
                    nifty_bias = "BEARISH"
                else:
                    nifty_bias = "NEUTRAL"
            else:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                nifty_bias = "UNKNOWN"
                nifty_change = 0
            
            # Fetch India VIX
            vix_current = 15  # Default
            try:
                vix = yf.Ticker("^INDIAVIX")
                vix_data = vix.history(period="1d", interval="15m", timeout=10)
                if vix_data is not None and not vix_data.empty:
                    vix_current = vix_data['Close'].iloc[-1]
            except Exception as vix_error:
                pass  # Use default VIX value
            
            return {
                'nifty_bias': nifty_bias,
                'nifty_change': nifty_change,
                'vix': vix_current,
                'risk_level': 'HIGH' if vix_current > 20 else 'MODERATE' if vix_current > 15 else 'LOW',
                'error': None
            }
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            default_return['error'] = str(e)
            return default_return
    
    return default_return

def establish_directional_bias(df, ticker):
    """
    DIRECTIONAL INTELLIGENCE: Establish and lock market bias
    Prevents flip-flopping by maintaining directional commitment
    """
    if len(df) < 50:
        return "NEUTRAL", 0, "Insufficient data"
    
    # Analyze last 50 candles for structure
    recent = df.tail(50)
    
    # Higher highs and higher lows = Uptrend
    highs = recent['High'].values
    lows = recent['Low'].values
    
    higher_highs = sum(highs[i] > highs[i-5] for i in range(5, len(highs)))
    higher_lows = sum(lows[i] > lows[i-5] for i in range(5, len(lows)))
    
    lower_highs = sum(highs[i] < highs[i-5] for i in range(5, len(highs)))
    lower_lows = sum(lows[i] < lows[i-5] for i in range(5, len(lows)))
    
    # Calculate bias strength
    bullish_structure = higher_highs + higher_lows
    bearish_structure = lower_highs + lower_lows
    
    # Determine primary bias
    if bullish_structure > bearish_structure * 1.5:
        primary_bias = "BULLISH"
        strength = min(100, (bullish_structure / (bullish_structure + bearish_structure)) * 100)
    elif bearish_structure > bullish_structure * 1.5:
        primary_bias = "BEARISH"
        strength = min(100, (bearish_structure / (bullish_structure + bearish_structure)) * 100)
    else:
        primary_bias = "NEUTRAL"
        strength = 50
    
    # Confirm with EMAs
    ema_9 = EMAIndicator(df['Close'], window=9).ema_indicator().iloc[-1]
    ema_21 = EMAIndicator(df['Close'], window=21).ema_indicator().iloc[-1]
    ema_50 = EMAIndicator(df['Close'], window=50).ema_indicator().iloc[-1]
    current_price = df['Close'].iloc[-1]
    
    # Invalidation levels
    if primary_bias == "BULLISH":
        invalidation_price = ema_50 * 0.995  # 0.5% below EMA-50
        if current_price < invalidation_price:
            primary_bias = "NEUTRAL"
            strength = 30
    elif primary_bias == "BEARISH":
        invalidation_price = ema_50 * 1.005  # 0.5% above EMA-50
        if current_price > invalidation_price:
            primary_bias = "NEUTRAL"
            strength = 30
    else:
        invalidation_price = current_price
    
    # Store in session state with timestamp
    if ticker not in st.session_state.directional_bias:
        st.session_state.directional_bias[ticker] = {
            'bias': primary_bias,
            'strength': strength,
            'established_at': datetime.now(IST),
            'invalidation_price': invalidation_price
        }
    else:
        # Check if bias should be updated (significant change)
        stored_bias = st.session_state.directional_bias[ticker]
        time_elapsed = (datetime.now(IST) - stored_bias['established_at']).total_seconds() / 60
        
        # Only update if: 1) Invalidation hit, OR 2) Strong reversal confirmed
        if primary_bias != stored_bias['bias'] and strength > 70 and time_elapsed > 30:
            st.session_state.directional_bias[ticker] = {
                'bias': primary_bias,
                'strength': strength,
                'established_at': datetime.now(IST),
                'invalidation_price': invalidation_price
            }
    
    return primary_bias, strength, invalidation_price

def check_consolidation_lock(df):
    """
    LOOPHOLE FIX: Detect price oscillation/consolidation
    Prevents signal flip-flopping in range-bound markets
    """
    if len(df) < 20:
        return False, 0
    
    recent = df.tail(20)
    price_range = (recent['High'].max() - recent['Low'].min())
    range_pct = (price_range / recent['Close'].iloc[-1]) * 100
    
    # Calculate VWAP crossings
    vwap = calculate_vwap(df).tail(20)
    closes = recent['Close']
    crossings = sum(1 for i in range(1, len(closes)) if 
                   (closes.iloc[i] > vwap.iloc[i] and closes.iloc[i-1] <= vwap.iloc[i-1]) or
                   (closes.iloc[i] < vwap.iloc[i] and closes.iloc[i-1] >= vwap.iloc[i-1]))
    
    # Consolidation detected if: tight range + multiple VWAP crossings
    is_consolidating = range_pct < 0.8 and crossings >= 3
    
    return is_consolidating, range_pct

def detect_move_exhaustion(df, signal_direction):
    """
    LOOPHOLE FIX: Detect if move is exhausted (late entry prevention)
    Blocks entries after significant intraday moves
    """
    if len(df) < 30:
        return False, 0, "Insufficient data"
    
    # Find session start (9:15 AM or earliest available)
    today_data = df[df.index.date == df.index[-1].date()]
    
    if len(today_data) < 5:
        return False, 0, "Insufficient intraday data"
    
    session_start_price = today_data['Open'].iloc[0]
    current_price = df['Close'].iloc[-1]
    move_pct = ((current_price - session_start_price) / session_start_price) * 100
    
    # Calculate expected daily range using ATR
    atr = AverageTrueRange(df['High'], df['Low'], df['Close'], window=14).average_true_range().iloc[-1]
    expected_range_pct = (atr * 3 / current_price) * 100  # 3x ATR as full day range
    
    # Move exhaustion calculation
    if expected_range_pct > 0:
        move_consumed = abs(move_pct) / expected_range_pct
    else:
        move_consumed = 0
    
    # Exhaustion criteria
    is_exhausted = False
    reason = ""
    
    if signal_direction == "BUY" and move_pct > 2.0 and move_consumed > 0.7:
        is_exhausted = True
        reason = f"Already up {move_pct:.1f}% today - {move_consumed*100:.0f}% of expected range consumed"
    elif signal_direction == "SELL" and move_pct < -2.0 and move_consumed > 0.7:
        is_exhausted = True
        reason = f"Already down {abs(move_pct):.1f}% today - {move_consumed*100:.0f}% of expected range consumed"
    
    return is_exhausted, move_pct, reason

def validate_volume_quality(df, ticker=""):
    """
    LOOPHOLE FIX: Validate volume is sustained, not isolated spike
    Prevents volume trap conditions
    For indices, returns neutral quality since volume isn't meaningful
    """
    # Indices don't have meaningful volume data
    if ticker.startswith('^'):
        return "INDEX_NO_VOLUME", 1.0
    
    if len(df) < 20:
        return "INSUFFICIENT_DATA", 1.0
    
    current_volume = df['Volume'].iloc[-1]
    avg_volume = df['Volume'].tail(20).mean()
    
    if avg_volume == 0:
        return "NO_VOLUME", 0
    
    volume_ratio = current_volume / avg_volume
    
    # Check if volume is building (last 5 candles)
    last_5_volumes = df['Volume'].tail(5).values
    above_average_count = sum(1 for v in last_5_volumes if v > avg_volume)
    
    # Quality classification
    if volume_ratio > 1.8:  # Spike detected
        if above_average_count >= 3:
            return "HIGH_QUALITY_SUSTAINED", volume_ratio
        elif above_average_count == 1:
            return "ISOLATED_SPIKE_TRAP", volume_ratio
        else:
            return "BUILDING_VOLUME", volume_ratio
    elif volume_ratio > 1.2:
        return "MODERATE_VOLUME", volume_ratio
    else:
        return "LOW_VOLUME", volume_ratio

def check_trade_cooldown(ticker, current_time):
    """
    DISCIPLINE: Enforce cooldown periods after trades
    Prevents revenge trading and overtrading
    """
    # Check forced break (after 2 consecutive losses)
    if st.session_state.forced_break_until:
        if current_time < st.session_state.forced_break_until:
            remaining = (st.session_state.forced_break_until - current_time).total_seconds() / 60
            return True, f"Forced break active - {remaining:.0f} min remaining after consecutive losses"
    
    # Check ticker-specific cooldown
    if ticker in st.session_state.last_trade_time:
        last_trade = st.session_state.last_trade_time[ticker]
        time_since_last = (current_time - last_trade['time']).total_seconds() / 60
        
        # Cooldown rules
        if last_trade['outcome'] == 'STOP_LOSS' and time_since_last < 30:
            return True, f"Cooldown after SL - Wait {30 - time_since_last:.0f} more minutes"
        elif last_trade['outcome'] == 'TARGET_HIT' and time_since_last < 15:
            return True, f"Cooldown after win - Wait {15 - time_since_last:.0f} more minutes"
        elif time_since_last < 20:
            return True, f"Same ticker cooldown - Wait {20 - time_since_last:.0f} more minutes"
    
    return False, ""

def check_daily_limits(ticker, current_date):
    """
    DISCIPLINE: Enforce daily trade limits
    Max 10 trades total, 3 per ticker, stop after 2 consecutive losses
    """
    # Reset counters if new day
    if st.session_state.daily_trade_count['date'] != current_date:
        st.session_state.daily_trade_count = {
            'date': current_date,
            'total': 0,
            'per_ticker': {}
        }
        st.session_state.consecutive_losses = 0
        st.session_state.forced_break_until = None
    
    # Check total daily limit
    if st.session_state.daily_trade_count['total'] >= 10:
        return True, "Daily limit reached (10 trades) - Resume tomorrow"
    
    # Check per-ticker limit
    ticker_count = st.session_state.daily_trade_count['per_ticker'].get(ticker, 0)
    if ticker_count >= 3:
        return True, f"{ticker} - Max 3 trades per day reached"
    
    # Check consecutive losses
    if st.session_state.consecutive_losses >= 2:
        return True, "2 consecutive losses - Mandatory break activated"
    
    return False, ""

def load_ticker_memory(ticker):
    """Load from DB mapping if not in state"""
    if ticker not in st.session_state.ticker_memory:
        db_mem = db_client.get_ticker_memory(ticker)
        if db_mem:
            st.session_state.ticker_memory[ticker] = db_mem
        else:
            st.session_state.ticker_memory[ticker] = {
                'last_10_trades': [],
                'trap_zones': {},
                'session_performance': {'Opening': [], 'Best': [], 'Late': []},
                'total_trades': 0
            }

def update_ticker_memory(ticker, signal, outcome=None):
    """
    MEMORY: Store trade outcomes and build historical context
    """
    load_ticker_memory(ticker)
    memory = st.session_state.ticker_memory[ticker]
    
    # Store trade
    trade_record = {
        'ticker': ticker,
        'timestamp': datetime.now(IST),
        'signal': signal['signal'],
        'entry': float(signal['entry']),
        'outcome': outcome,
        'session': signal.get('strategy_tag', 'UNKNOWN')
    }
    
    if outcome is not None:
        db_client.save_trade(trade_record)
        
    memory['last_10_trades'].append(trade_record)
    if len(memory['last_10_trades']) > 10:
        memory['last_10_trades'].pop(0)
    
    memory['total_trades'] += 1
    
    # Track trap zones (failed signals at similar price levels)
    if outcome == 'STOP_LOSS':
        price_zone = str(round(signal['entry'] / 10) * 10)  # Stringified for MongoDB keys
        if price_zone not in memory['trap_zones']:
            memory['trap_zones'][price_zone] = {'count': 0, 'last_occurred': None}
        memory['trap_zones'][price_zone]['count'] += 1
        memory['trap_zones'][price_zone]['last_occurred'] = datetime.now(IST)

    # Sync memory back to DB
    db_client.update_ticker_memory(ticker, memory)

def check_trap_zones(ticker, current_price):
    """
    MEMORY: Check if current price is near known trap zones
    """
    load_ticker_memory(ticker)
    memory = st.session_state.ticker_memory[ticker]
    trap_zones = memory.get('trap_zones', {})
    
    for price_zone_str, data in trap_zones.items():
        try:
            price_zone = float(price_zone_str)
            if abs(current_price - price_zone) < 20 and data['count'] >= 3:
                return True, f"Trap zone detected near ₹{price_zone} - {data['count']} previous failures"
        except:
            pass
    
    return False, ""

def adjust_confidence_for_market_context(base_confidence, ticker, signal_direction, market_context):
    """
    INTELLIGENCE: Adjust confidence based on market context and memory
    """
    adjusted_confidence = base_confidence
    adjustments = []
    
    # 1. NIFTY alignment check
    nifty_bias = market_context['nifty_bias']
    if signal_direction == "BUY" and nifty_bias == "BEARISH":
        adjusted_confidence -= 25
        adjustments.append("⚠️ NIFTY bearish - Stock fighting market (-25)")
    elif signal_direction == "SELL" and nifty_bias == "BULLISH":
        adjusted_confidence -= 25
        adjustments.append("⚠️ NIFTY bullish - Stock fighting market (-25)")
    elif signal_direction == "BUY" and nifty_bias == "BULLISH":
        adjusted_confidence += 10
        adjustments.append("✅ NIFTY aligned bullish (+10)")
    elif signal_direction == "SELL" and nifty_bias == "BEARISH":
        adjusted_confidence += 10
        adjustments.append("✅ NIFTY aligned bearish (+10)")
    
    # 2. VIX risk adjustment
    vix = market_context['vix']
    if vix > 20:
        adjusted_confidence -= 15
        adjustments.append(f"⚠️ High VIX ({vix:.1f}) - Elevated risk (-15)")
    elif vix < 12:
        adjusted_confidence += 5
        adjustments.append(f"✅ Low VIX ({vix:.1f}) - Stable market (+5)")
    
    # 3. Recent performance adjustment
    if ticker in st.session_state.ticker_memory:
        memory = st.session_state.ticker_memory[ticker]
        recent_trades = memory['last_10_trades'][-5:] if len(memory['last_10_trades']) >= 5 else memory['last_10_trades']
        
        if recent_trades:
            wins = sum(1 for t in recent_trades if t['outcome'] == 'TARGET_HIT')
            losses = sum(1 for t in recent_trades if t['outcome'] == 'STOP_LOSS')
            
            if losses >= 3:
                adjusted_confidence -= 20
                adjustments.append(f"⚠️ Recent poor performance ({losses} losses in last 5) (-20)")
            elif wins >= 4:
                adjusted_confidence += 10
                adjustments.append(f"✅ Recent strong performance ({wins} wins in last 5) (+10)")
    
    # 4. Directional bias strength
    if ticker in st.session_state.directional_bias:
        bias_data = st.session_state.directional_bias[ticker]
        if bias_data['bias'] != signal_direction.replace("BUY", "BULLISH").replace("SELL", "BEARISH"):
            if bias_data['strength'] > 60:
                adjusted_confidence -= 30
                adjustments.append(f"⚠️ Against established {bias_data['bias']} bias ({bias_data['strength']:.0f}% strength) (-30)")
    
    return max(0, min(100, adjusted_confidence)), adjustments

# Helper Functions
@st.cache_data(ttl=300)
def fetch_intraday_data(ticker, period="5d", interval="15m"):
    """Fetch intraday data with timezone conversion to IST - Enhanced with retry logic"""
    import time
    
    if not ticker or ticker.strip() == "":
        st.error("⚠️ Please enter a valid ticker symbol")
        return None, None
    
    # Clean and format ticker
    ticker = ticker.strip().upper()
    
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            # Add exchange suffix if not present for Indian stocks
            if ticker.startswith('^'):
                # Index symbols don't need suffix
                test_ticker = ticker
                st.info(f"🔍 Attempting to fetch {test_ticker} (Index)...")
            elif not ticker.endswith(('.NS', '.BO')):
                # Try .NS first for NSE stocks
                test_ticker = ticker + '.NS'
                st.info(f"🔍 Attempting to fetch {test_ticker} (NSE)...")
            else:
                test_ticker = ticker
            
            stock = yf.Ticker(test_ticker)
            df = stock.history(period=period, interval=interval, timeout=15)
            
            # Check if data is valid
            if df is not None and not df.empty and len(df) > 0:
                # Convert to IST
                try:
                    df.index = df.index.tz_convert(IST)
                except Exception as tz_error:
                    st.warning(f"⚠️ Timezone conversion issue: {tz_error}. Using original timezone.")
                
                # Fetch info with error handling
                info = {}
                try:
                    info = stock.info
                except Exception as info_error:
                    st.warning(f"⚠️ Could not fetch company info: {info_error}")
                    info = {'shortName': test_ticker, 'longName': test_ticker}
                
                st.success(f"✅ Successfully fetched {len(df)} data points for {test_ticker}")
                return df, info
            else:
                # If .NS didn't work, try .BO (BSE) - only for non-index symbols
                if not ticker.endswith(('.NS', '.BO')) and not ticker.startswith('^') and attempt == 0:
                    test_ticker = ticker + '.BO'
                    st.info(f"🔍 Trying {test_ticker} (BSE)...")
                    stock = yf.Ticker(test_ticker)
                    df = stock.history(period=period, interval=interval, timeout=15)
                    
                    if df is not None and not df.empty and len(df) > 0:
                        df.index = df.index.tz_convert(IST)
                        info = {}
                        try:
                            info = stock.info
                        except:
                            info = {'shortName': test_ticker, 'longName': test_ticker}
                        st.success(f"✅ Successfully fetched {len(df)} data points for {test_ticker}")
                        return df, info
                
                # Empty data - retry or fail
                if attempt < max_retries - 1:
                    st.warning(f"⏳ Attempt {attempt + 1} failed - No data returned. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    st.error(f"❌ No data available for {ticker}")
                    st.info("""**Troubleshooting:**
- Check if ticker symbol is correct
- Indian stocks need .NS (NSE) or .BO (BSE) suffix
- For indices, use ^ prefix (e.g., ^NSEI for NIFTY 50)
- Market may be closed or data unavailable for this period
- Example: RELIANCE.NS, TCS.NS, ^NSEI""")
                    return None, None
                    
        except Exception as e:
            error_msg = str(e)
            if attempt < max_retries - 1:
                st.warning(f"⚠️ Attempt {attempt + 1} error: {error_msg}. Retrying...")
                time.sleep(retry_delay)
                continue
            else:
                st.error(f"❌ Error fetching data after {max_retries} attempts: {error_msg}")
                if "404" in error_msg or "No data found" in error_msg:
                    st.info("💡 Ticker not found. Please verify the symbol.")
                elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    st.info("💡 Request timed out. Please check your internet connection and try again.")
                elif "connection" in error_msg.lower():
                    st.info("💡 Network connection issue. Please check your internet.")
                return None, None
    
    return None, None

def detect_candle_interval(df):
    """Automatically detect candle interval in minutes"""
    if len(df) < 2:
        return 15
    
    time_diff = (df.index[-1] - df.index[-2]).total_seconds() / 60
    return int(time_diff)

def get_current_session(current_time):
    """Determine current market session"""
    time_str = current_time.strftime("%H:%M")
    
    for session_name, session_info in MARKET_SESSIONS.items():
        start = session_info["start"]
        end = session_info["end"]
        
        if start <= time_str < end:
            return session_name, session_info["rules"]
    
    return "Closed", "Market is closed"

def calculate_target_time_windows(df, entry_time, candle_interval):
    """Calculate real IST time windows for targets"""
    target_windows = {}
    
    # Define candle counts for each target based on interval
    if candle_interval == 5:
        candles = {"Target-1": 1, "Target-2": 3, "Target-3": 6}
    elif candle_interval == 15:
        candles = {"Target-1": 1, "Target-2": 2, "Target-3": 4}
    else:
        candles = {"Target-1": 1, "Target-2": 2, "Target-3": 3}
    
    market_close = entry_time.replace(hour=15, minute=30, second=0, microsecond=0)
    
    for target, num_candles in candles.items():
        target_time = entry_time + timedelta(minutes=candle_interval * num_candles)
        
        if target_time > market_close:
            target_windows[target] = None  # Invalid - exceeds market hours
        else:
            target_windows[target] = target_time.strftime("%H:%M IST")
    
    return target_windows, candles

def check_signal_expiry(entry_time, current_time, candle_interval):
    """Check if signal has expired"""
    if candle_interval == 5:
        expiry_candles = 3
    elif candle_interval == 15:
        expiry_candles = 2
    else:
        expiry_candles = 2
    
    expiry_time = entry_time + timedelta(minutes=candle_interval * expiry_candles)
    
    if current_time > expiry_time:
        return True, expiry_time
    
    return False, expiry_time

def detect_gap_day(df):
    """Detect gap opening for Indian markets"""
    if len(df) < 2:
        return False, 0
    
    # Get previous day's close and today's open
    prev_close = df['Close'].iloc[-2]
    today_open = df['Open'].iloc[-1]
    
    gap_pct = ((today_open - prev_close) / prev_close) * 100
    
    if abs(gap_pct) > 1:
        return True, gap_pct
    
    return False, gap_pct

def detect_market_regime(df):
    """Detect if market is in TREND or RANGE day"""
    if len(df) < 50:
        return "UNKNOWN"
    
    high = df['High'].tail(50).max()
    low = df['Low'].tail(50).min()
    range_pct = ((high - low) / low) * 100
    
    # Check ADX-like behavior using EMA slope
    ema_21 = EMAIndicator(df['Close'], window=21).ema_indicator()
    ema_slope = (ema_21.iloc[-1] - ema_21.iloc[-10]) / ema_21.iloc[-10] * 100
    
    if range_pct > 3 and abs(ema_slope) > 1:
        return "TREND DAY"
    else:
        return "RANGE DAY"

def calculate_vwap(df):
    """Calculate intraday VWAP (Volume Weighted Average Price)"""
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    vwap = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
    return vwap

def detect_no_trade_zone(df):
    """Detect consolidation/no-trade zones"""
    if len(df) < 21:
        return False
    
    ema_9 = EMAIndicator(df['Close'], window=9).ema_indicator()
    ema_21 = EMAIndicator(df['Close'], window=21).ema_indicator()
    rsi = RSIIndicator(df['Close'], window=14).rsi()
    vwap = calculate_vwap(df)
    
    current_price = df['Close'].iloc[-1]
    current_rsi = rsi.iloc[-1]
    avg_volume = df['Volume'].tail(20).mean()
    current_volume = df['Volume'].iloc[-1]
    
    # Check conditions
    price_between_emas = (min(ema_9.iloc[-1], ema_21.iloc[-1]) < current_price < max(ema_9.iloc[-1], ema_21.iloc[-1]))
    rsi_neutral = 45 < current_rsi < 55
    low_volume = current_volume < avg_volume
    vwap_flat = abs(vwap.iloc[-1] - vwap.iloc[-10]) / vwap.iloc[-10] < 0.001
    
    if price_between_emas and rsi_neutral and low_volume:
        return True
    
    return False

def detect_false_breakout(df):
    """Detect false breakouts"""
    if len(df) < 3:
        return False
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # Volume spike followed by collapse
    volume_spike = last['Volume'] > df['Volume'].tail(20).mean() * 1.5
    volume_collapse = prev['Volume'] < df['Volume'].tail(20).mean()
    
    # Price re-enters range
    resistance = df['High'].tail(50).quantile(0.80)
    support = df['Low'].tail(50).quantile(0.20)
    
    price_re_entered = support < last['Close'] < resistance
    
    if volume_spike and volume_collapse and price_re_entered:
        return True
    
    return False

def check_vwap_deviation(df):
    """Check if price is too far from VWAP"""
    current_price = df['Close'].iloc[-1]
    vwap = calculate_vwap(df).iloc[-1]
    
    deviation_pct = abs((current_price - vwap) / vwap) * 100
    
    if deviation_pct > 1.5:
        return True, deviation_pct
    
    return False, deviation_pct

def calculate_support_resistance(df, window=50):
    """Calculate support and resistance levels using quantile-based approach"""
    recent_data = df.tail(window)
    
    support = recent_data['Low'].quantile(0.20)
    resistance = recent_data['High'].quantile(0.80)
    
    return support, resistance

def detect_trend(df, window=5):
    """Detect trend using EMAs with slope confirmation"""
    close = df['Close']
    ema_9 = EMAIndicator(close, window=9).ema_indicator()
    ema_21 = EMAIndicator(close, window=21).ema_indicator()
    ema_50 = EMAIndicator(close, window=50).ema_indicator()
    
    current_price = close.iloc[-1]
    
    recent_ema_9 = ema_9.tail(window)
    recent_ema_21 = ema_21.tail(window)
    recent_ema_50 = ema_50.tail(window)
    
    uptrend_count = (recent_ema_9 > recent_ema_21).sum()
    downtrend_count = (recent_ema_9 < recent_ema_21).sum()
    
    if uptrend_count >= 4:
        if current_price > ema_9.iloc[-1] > ema_21.iloc[-1] > ema_50.iloc[-1]:
            return "STRONG UPTREND", "🟢"
        else:
            return "UPTREND", "🟢"
    elif downtrend_count >= 4:
        if current_price < ema_9.iloc[-1] < ema_21.iloc[-1] < ema_50.iloc[-1]:
            return "STRONG DOWNTREND", "🔴"
        else:
            return "DOWNTREND", "🔴"
    else:
        return "SIDEWAYS", "🟡"

def detect_candlestick_patterns(df):
    """Detect common candlestick patterns with improved accuracy and future prediction"""
    patterns = []
    
    if len(df) < 3:
        return patterns, "NEUTRAL", []
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3] if len(df) > 2 else None
    
    open_price = last['Open']
    close_price = last['Close']
    high_price = last['High']
    low_price = last['Low']
    
    body = abs(close_price - open_price)
    range_price = high_price - low_price
    
    if range_price == 0:
        return [("No Clear Pattern", "⚪", "Wait for confirmation")], "NEUTRAL", []
    
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    future_trend = "NEUTRAL"
    prediction_reasons = []
    
    # Bullish patterns
    if close_price > open_price and body > (range_price * 0.6):
        patterns.append(("Bullish Marubozu", "🟢", "Strong buying pressure"))
        future_trend = "BULLISH"
        prediction_reasons.append("Strong bullish candle suggests continuation upward")
    
    if close_price > open_price and prev['Close'] < prev['Open'] and close_price > prev['Open']:
        patterns.append(("Bullish Engulfing", "🟢", "Reversal signal"))
        future_trend = "BULLISH"
        prediction_reasons.append("Bullish engulfing indicates trend reversal to upside")
    
    if (lower_wick > body * 2 and upper_wick < body * 0.5 and 
        body < range_price * 0.3):
        patterns.append(("Hammer", "🟢", "Potential bullish reversal"))
        if len(df) >= 5:
            recent_trend = df['Close'].tail(5).is_monotonic_decreasing
            if recent_trend or prev['Close'] < prev['Open']:
                future_trend = "BULLISH_REVERSAL"
                prediction_reasons.append("Hammer after downtrend signals bullish reversal - expect upward movement")
    
    # Doji
    if body < (range_price * 0.1):
        patterns.append(("Doji", "🟡", "Indecision - potential reversal"))
        if len(df) >= 5:
            recent_closes = df['Close'].tail(5)
            if recent_closes.iloc[-2] < recent_closes.iloc[-5]:
                future_trend = "BULLISH_REVERSAL"
                prediction_reasons.append("Doji after downtrend signals potential bullish reversal")
            elif recent_closes.iloc[-2] > recent_closes.iloc[-5]:
                future_trend = "BEARISH_REVERSAL"
                prediction_reasons.append("Doji after uptrend signals potential bearish reversal")
    
    # Bearish patterns
    if close_price < open_price and body > (range_price * 0.6):
        patterns.append(("Bearish Marubozu", "🔴", "Strong selling pressure"))
        future_trend = "BEARISH"
        prediction_reasons.append("Strong bearish candle suggests continuation downward")
    
    if close_price < open_price and prev['Close'] > prev['Open'] and close_price < prev['Open']:
        patterns.append(("Bearish Engulfing", "🔴", "Reversal signal"))
        future_trend = "BEARISH"
        prediction_reasons.append("Bearish engulfing indicates trend reversal to downside")
    
    if (upper_wick > body * 2 and lower_wick < body * 0.5 and 
        body < range_price * 0.3):
        patterns.append(("Shooting Star", "🔴", "Potential bearish reversal"))
        if len(df) >= 5:
            recent_trend = df['Close'].tail(5).is_monotonic_increasing
            if recent_trend or prev['Close'] > prev['Open']:
                future_trend = "BEARISH_REVERSAL"
                prediction_reasons.append("Shooting Star after uptrend signals bearish reversal - expect downward movement")
    
    # Three candle patterns
    if prev2 is not None:
        if (prev2['Close'] < prev2['Open'] and 
            prev['Close'] > prev['Open'] and 
            close_price > open_price and 
            close_price > prev['Close']):
            patterns.append(("Morning Star", "🟢", "Strong bullish reversal"))
            future_trend = "BULLISH_REVERSAL"
            prediction_reasons.append("Morning Star pattern - strong bullish reversal confirmed")
        
        if (prev2['Close'] > prev2['Open'] and 
            prev['Close'] < prev['Open'] and 
            close_price < open_price and 
            close_price < prev['Close']):
            patterns.append(("Evening Star", "🔴", "Strong bearish reversal"))
            future_trend = "BEARISH_REVERSAL"
            prediction_reasons.append("Evening Star pattern - strong bearish reversal confirmed")
    
    if not patterns:
        patterns = [("No Clear Pattern", "⚪", "Wait for confirmation")]
    
    return patterns, future_trend, prediction_reasons

def create_candlestick_chart(df, patterns, future_trend, prediction_reasons):
    """Create a clean candlestick chart showing last 20-30 candles with pattern annotations"""
    
    df_display = df.tail(30)
    
    fig = go.Figure()
    
    fig.add_trace(
        go.Candlestick(
            x=df_display.index,
            open=df_display['Open'],
            high=df_display['High'],
            low=df_display['Low'],
            close=df_display['Close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            increasing_fillcolor='#26a69a',
            decreasing_fillcolor='#ef5350'
        )
    )
    
    last_candle = df_display.iloc[-1]
    pattern_text = "<br>".join([f"{p[1]} {p[0]}" for p in patterns])
    
    fig.add_annotation(
        x=df_display.index[-1],
        y=last_candle['High'],
        text=pattern_text,
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=2,
        arrowcolor="#FFC107",
        ax=0,
        ay=-40,
        bgcolor="#1e2130",
        bordercolor="#FFC107",
        borderwidth=2,
        font=dict(size=12, color="white")
    )
    
    if future_trend == "BULLISH" or future_trend == "BULLISH_REVERSAL":
        fig.add_annotation(
            x=df_display.index[-1],
            y=last_candle['Close'],
            ax=50,
            ay=-60,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            text="",
            showarrow=True,
            arrowhead=3,
            arrowsize=2,
            arrowwidth=3,
            arrowcolor="#4CAF50"
        )
        prediction_symbol = "📈"
    elif future_trend == "BEARISH" or future_trend == "BEARISH_REVERSAL":
        fig.add_annotation(
            x=df_display.index[-1],
            y=last_candle['Close'],
            ax=50,
            ay=60,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            text="",
            showarrow=True,
            arrowhead=3,
            arrowsize=2,
            arrowwidth=3,
            arrowcolor="#f44336"
        )
        prediction_symbol = "📉"
    else:
        prediction_symbol = "↔️"
    
    fig.update_layout(
        title=f'Candlestick Pattern Analysis - {prediction_symbol} Predicted: {future_trend}',
        xaxis_title="Time",
        yaxis_title="Price",
        template='plotly_dark',
        height=600,
        hovermode='x unified',
        xaxis_rangeslider_visible=False,
        showlegend=False
    )
    
    return fig

def detect_volume_spike(df, window=20):
    """Detect if current volume is significantly higher than average"""
    if len(df) < window:
        return False, 0
    
    avg_volume = df['Volume'].tail(window).mean()
    current_volume = df['Volume'].iloc[-1]
    
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
    is_spike = volume_ratio > 1.5
    
    return is_spike, volume_ratio

def calculate_confidence_score(df, trend, signals, support, resistance, session_name, market_regime):
    """Calculate trading signal confidence score out of 100 with session and regime awareness"""
    score = 0
    reasons = []
    
    current_price = df['Close'].iloc[-1]
    
    # 1. Trend alignment (20 points)
    if "UPTREND" in trend and signals['signal'] == "BUY":
        score += 20
        reasons.append("✓ Trend aligned (20)")
    elif "DOWNTREND" in trend and signals['signal'] == "SELL":
        score += 20
        reasons.append("✓ Trend aligned (20)")
    else:
        reasons.append("✗ Trend not aligned (0)")
    
    # 2. RSI confirmation (15 points)
    rsi = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
    if signals['signal'] == "BUY" and 30 < rsi < 70:
        score += 15
        reasons.append("✓ RSI favorable (15)")
    elif signals['signal'] == "SELL" and 30 < rsi < 70:
        score += 15
        reasons.append("✓ RSI favorable (15)")
    else:
        reasons.append("✗ RSI not favorable (0)")
    
    # 3. MACD confirmation (15 points)
    macd_indicator = MACD(df['Close'])
    macd_line = macd_indicator.macd().iloc[-1]
    signal_line = macd_indicator.macd_signal().iloc[-1]
    
    if signals['signal'] == "BUY" and macd_line > signal_line:
        score += 15
        reasons.append("✓ MACD bullish (15)")
    elif signals['signal'] == "SELL" and macd_line < signal_line:
        score += 15
        reasons.append("✓ MACD bearish (15)")
    else:
        reasons.append("✗ MACD not confirming (0)")
    
    # 4. VWAP confirmation (15 points)
    vwap = calculate_vwap(df).iloc[-1]
    if signals['signal'] == "BUY" and current_price > vwap:
        score += 15
        reasons.append("✓ Price above VWAP (15)")
    elif signals['signal'] == "SELL" and current_price < vwap:
        score += 15
        reasons.append("✓ Price below VWAP (15)")
    else:
        reasons.append("✗ VWAP not confirming (0)")
    
    # 5. Volume spike (10 points)
    is_spike, volume_ratio = detect_volume_spike(df)
    if is_spike:
        score += 10
        reasons.append(f"✓ High volume ({volume_ratio:.1f}x) (10)")
    else:
        reasons.append("✗ Normal volume (0)")
    
    # 6. Session quality (15 points)
    if session_name == "Best":
        score += 15
        reasons.append("✓ Best trading session (15)")
    elif session_name == "Opening" or session_name == "Late":
        score += 7
        reasons.append("✓ Acceptable session (7)")
    else:
        reasons.append("✗ Poor session timing (0)")
    
    # 7. Market regime alignment (10 points)
    if market_regime == "TREND DAY" and signals['signal'] in ["BUY", "SELL"]:
        score += 10
        reasons.append("✓ Trend day - good for trends (10)")
    elif market_regime == "RANGE DAY":
        score -= 10
        reasons.append("✗ Range day - avoid trends (-10)")
    
    # Ensure score doesn't go below 0
    score = max(0, score)
    
    # Determine confidence level
    if score >= 75:
        confidence = "HIGH CONFIDENCE"
        color = "🟢"
    elif score >= 50:
        confidence = "MEDIUM CONFIDENCE"
        color = "🟡"
    else:
        confidence = "LOW CONFIDENCE - AVOID"
        color = "🔴"
    
    return score, confidence, color, reasons

def calculate_entry_exit(df, support, resistance, trend, session_name):
    """Calculate entry, exit with candle confirmation and session awareness"""
    current_price = df['Close'].iloc[-1]
    
    atr_indicator = AverageTrueRange(df['High'], df['Low'], df['Close'], window=14)
    atr = atr_indicator.average_true_range().iloc[-1]
    
    vwap = calculate_vwap(df).iloc[-1]
    macd_indicator = MACD(df['Close'])
    macd_line = macd_indicator.macd().iloc[-1]
    signal_line = macd_indicator.macd_signal().iloc[-1]
    
    ema_9 = EMAIndicator(df['Close'], window=9).ema_indicator().iloc[-1]
    
    # Check candle close confirmation
    last_candle = df.iloc[-1]
    candle_closed_bullish = last_candle['Close'] > vwap and last_candle['Close'] > ema_9
    candle_closed_bearish = last_candle['Close'] < vwap and last_candle['Close'] < ema_9
    
    signals = {}
    
    # Session restrictions
    if session_name == "Midday" or session_name == "Closing":
        signals = {
            "signal": "WAIT",
            "reason": f"No trading during {session_name} session",
            "entry": round(current_price, 2),
            "stop_loss": 0,
            "target1": 0,
            "target2": 0,
            "target3": 0,
            "profit1_pct": 0,
            "profit2_pct": 0,
            "profit3_pct": 0,
            "risk_reward": 0,
            "strategy_tag": "NO TRADE"
        }
        return signals
    
    # Calculate SL with buffer (SL-hunt protection)
    sl_buffer = atr * 0.3
    
    if "UPTREND" in trend and candle_closed_bullish and macd_line > signal_line:
        # Entry after candle close confirmation
        entry = current_price + (current_price * 0.001)  # 0.1% buffer
        stop_loss = support - sl_buffer
        
        # Risk-reward check
        risk = abs(entry - stop_loss)
        
        min_profit_5_pct = current_price * 1.05
        min_profit_10_pct = current_price * 1.10
        
        target1_atr = current_price + (atr * 1.5)
        target2_atr = current_price + (atr * 2.5)
        target3_atr = resistance
        
        target1 = max(target1_atr, min_profit_5_pct)
        target2 = max(target2_atr, min_profit_10_pct)
        target3 = max(target3_atr, current_price * 1.15)
        
        reward = abs(target1 - entry)
        risk_reward = reward / risk if risk > 0 else 0
        
        # Reject if R:R < 1.5
        if risk_reward < 1.5:
            signals = {
                "signal": "WAIT",
                "reason": f"Risk:Reward too low ({risk_reward:.2f}:1)",
                "entry": round(entry, 2),
                "stop_loss": round(stop_loss, 2),
                "target1": 0,
                "target2": 0,
                "target3": 0,
                "profit1_pct": 0,
                "profit2_pct": 0,
                "profit3_pct": 0,
                "risk_reward": round(risk_reward, 2),
                "strategy_tag": "REJECTED"
            }
            return signals
        
        profit1_pct = ((target1 - entry) / entry) * 100
        profit2_pct = ((target2 - entry) / entry) * 100
        profit3_pct = ((target3 - entry) / entry) * 100
        
        # Strategy tagging
        if session_name == "Opening":
            strategy_tag = "SCALP"
        elif "STRONG" in trend:
            strategy_tag = "MOMENTUM"
        else:
            strategy_tag = "TREND CONTINUATION"
        
        signals = {
            "signal": "BUY",
            "reason": "Candle closed above VWAP + EMA-9",
            "entry": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target1": round(target1, 2),
            "target2": round(target2, 2),
            "target3": round(target3, 2),
            "profit1_pct": round(profit1_pct, 2),
            "profit2_pct": round(profit2_pct, 2),
            "profit3_pct": round(profit3_pct, 2),
            "risk_reward": round(risk_reward, 2),
            "strategy_tag": strategy_tag
        }
        
    elif "DOWNTREND" in trend and candle_closed_bearish and macd_line < signal_line:
        entry = current_price - (current_price * 0.001)
        stop_loss = resistance + sl_buffer
        
        risk = abs(stop_loss - entry)
        
        min_profit_5_pct = current_price * 0.95
        min_profit_10_pct = current_price * 0.90
        
        target1_atr = current_price - (atr * 1.5)
        target2_atr = current_price - (atr * 2.5)
        target3_atr = support
        
        target1 = min(target1_atr, min_profit_5_pct)
        target2 = min(target2_atr, min_profit_10_pct)
        target3 = min(target3_atr, current_price * 0.85)
        
        reward = abs(entry - target1)
        risk_reward = reward / risk if risk > 0 else 0
        
        if risk_reward < 1.5:
            signals = {
                "signal": "WAIT",
                "reason": f"Risk:Reward too low ({risk_reward:.2f}:1)",
                "entry": round(entry, 2),
                "stop_loss": round(stop_loss, 2),
                "target1": 0,
                "target2": 0,
                "target3": 0,
                "profit1_pct": 0,
                "profit2_pct": 0,
                "profit3_pct": 0,
                "risk_reward": round(risk_reward, 2),
                "strategy_tag": "REJECTED"
            }
            return signals
        
        profit1_pct = ((entry - target1) / entry) * 100
        profit2_pct = ((entry - target2) / entry) * 100
        profit3_pct = ((entry - target3) / entry) * 100
        
        if session_name == "Opening":
            strategy_tag = "SCALP"
        elif "STRONG" in trend:
            strategy_tag = "MOMENTUM"
        else:
            strategy_tag = "TREND CONTINUATION"
        
        signals = {
            "signal": "SELL",
            "reason": "Candle closed below VWAP + EMA-9",
            "entry": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target1": round(target1, 2),
            "target2": round(target2, 2),
            "target3": round(target3, 2),
            "profit1_pct": round(profit1_pct, 2),
            "profit2_pct": round(profit2_pct, 2),
            "profit3_pct": round(profit3_pct, 2),
            "risk_reward": round(risk_reward, 2),
            "strategy_tag": strategy_tag
        }
    else:
        signals = {
            "signal": "WAIT",
            "reason": "No candle close confirmation or VWAP/MACD not aligned",
            "entry": round(current_price, 2),
            "stop_loss": round(support - atr, 2),
            "target1": round(resistance, 2),
            "target2": round(resistance + atr, 2),
            "target3": round(resistance + (atr * 2), 2),
            "profit1_pct": 0,
            "profit2_pct": 0,
            "profit3_pct": 0,
            "risk_reward": 0,
            "strategy_tag": "WAITING"
        }
    
    return signals

def create_advanced_chart(df, support, resistance, signals, trend):
    """Create comprehensive intraday chart with all indicators"""
    
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.5, 0.15, 0.15, 0.2],
        subplot_titles=('Price Action with Signals', 'RSI', 'MACD', 'Volume')
    )
    
    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        ),
        row=1, col=1
    )
    
    # EMAs
    for period, color in [(9, '#2196F3'), (21, '#FF9800'), (50, '#9C27B0')]:
        ema = EMAIndicator(df['Close'], window=period).ema_indicator()
        fig.add_trace(
            go.Scatter(x=df.index, y=ema, name=f'EMA{period}', 
                      line=dict(color=color, width=1.5)),
            row=1, col=1
        )
    
    # VWAP
    vwap = calculate_vwap(df)
    fig.add_trace(
        go.Scatter(x=df.index, y=vwap, name='VWAP', 
                  line=dict(color='#00BCD4', width=2, dash='dot')),
        row=1, col=1
    )
    
    # Support/Resistance
    fig.add_hline(y=support, line_dash="dash", line_color="green", 
                  annotation_text="Support", row=1, col=1)
    fig.add_hline(y=resistance, line_dash="dash", line_color="red", 
                  annotation_text="Resistance", row=1, col=1)
    
    # Entry/SL/Targets
    if signals['signal'] == "BUY":
        fig.add_hline(y=signals['entry'], line_dash="dot", line_color="#4CAF50", 
                      annotation_text="Entry", row=1, col=1)
        fig.add_hline(y=signals['stop_loss'], line_dash="dot", line_color="#f44336", 
                      annotation_text="Stop Loss", row=1, col=1)
        if signals['target1'] > 0:
            fig.add_hline(y=signals['target1'], line_dash="dot", line_color="#FFC107", 
                          annotation_text="Target 1", row=1, col=1)
            fig.add_hline(y=signals['target2'], line_dash="dot", line_color="#FF9800", 
                          annotation_text="Target 2", row=1, col=1)
    elif signals['signal'] == "SELL":
        fig.add_hline(y=signals['entry'], line_dash="dot", line_color="#f44336", 
                      annotation_text="Entry", row=1, col=1)
        fig.add_hline(y=signals['stop_loss'], line_dash="dot", line_color="#4CAF50", 
                      annotation_text="Stop Loss", row=1, col=1)
        if signals['target1'] > 0:
            fig.add_hline(y=signals['target1'], line_dash="dot", line_color="#FFC107", 
                          annotation_text="Target 1", row=1, col=1)
    
    # RSI
    rsi = RSIIndicator(df['Close'], window=14).rsi()
    fig.add_trace(
        go.Scatter(x=df.index, y=rsi, name='RSI', 
                  line=dict(color='#9C27B0', width=2)),
        row=2, col=1
    )
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
    
    # MACD
    macd_indicator = MACD(df['Close'])
    macd_line = macd_indicator.macd()
    signal_line = macd_indicator.macd_signal()
    macd_hist = macd_indicator.macd_diff()
    
    fig.add_trace(
        go.Scatter(x=df.index, y=macd_line, name='MACD', 
                  line=dict(color='#2196F3', width=2)),
        row=3, col=1
    )
    fig.add_trace(
        go.Scatter(x=df.index, y=signal_line, name='Signal', 
                  line=dict(color='#FF9800', width=2)),
        row=3, col=1
    )
    
    colors_macd = ['red' if val < 0 else 'green' for val in macd_hist]
    fig.add_trace(
        go.Bar(x=df.index, y=macd_hist, name='MACD Histogram', 
               marker_color=colors_macd, showlegend=False),
        row=3, col=1
    )
    
    # Volume
    colors = ['red' if df['Close'].iloc[i] < df['Open'].iloc[i] else 'green' 
              for i in range(len(df))]
    fig.add_trace(
        go.Bar(x=df.index, y=df['Volume'], name='Volume', 
               marker_color=colors, showlegend=False),
        row=4, col=1
    )
    
    fig.update_layout(
        title=f'Intraday Analysis - {trend[0]} {trend[1]}',
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        height=1000,
        hovermode='x unified'
    )
    
    fig.update_xaxes(title_text="Time (IST)", row=4, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    fig.update_yaxes(title_text="Volume", row=4, col=1)
    
    return fig

# Search function for stock lookup
@st.cache_data(ttl=3600)
def search_stocks_online(query):
    """Search for stocks using yfinance"""
    if not query or len(query) < 2:
        return []
    
    try:
        import requests
        from urllib.parse import quote
        
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={quote(query)}&quotesCount=10&newsCount=0"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        results = []
        if 'quotes' in data:
            for quote_data in data['quotes']:
                symbol = quote_data.get('symbol', '')
                name = quote_data.get('longname') or quote_data.get('shortname', '')
                exchange = quote_data.get('exchDisp', '')
                quote_type = quote_data.get('quoteType', '')
                
                if quote_type in ['EQUITY', 'ETF'] and symbol and name:
                    results.append({
                        'symbol': symbol,
                        'name': name,
                        'exchange': exchange,
                        'display': f"{symbol} - {name} ({exchange})"
                    })
        
        return results[:10]
    except Exception as e:
        return []

# Main App
st.title("📊 Institutional-Grade Intraday Trading Engine")
st.markdown("### AI-Powered Decision System with Production Safety Layers")

# System Control Panel
col_sys1, col_sys2, col_sys3 = st.columns([2, 1, 1])
with col_sys1:
    st.markdown("**🛡️ System Status:** ✅ All Safety Layers Active")
with col_sys2:
    if st.session_state.forced_break_until:
        remaining = max(0, (st.session_state.forced_break_until - datetime.now(IST)).total_seconds() / 60)
        if remaining > 0:
            st.warning(f"⏸️ Break: {remaining:.0f}min")
with col_sys3:
    if st.button("🔄 Reset System", help="Clear all memory, trades, and cooldowns"):
        st.session_state.trade_history = []
        st.session_state.ticker_memory = {}
        st.session_state.directional_bias = {}
        st.session_state.last_trade_time = {}
        st.session_state.daily_trade_count = {'date': None, 'total': 0, 'per_ticker': {}}
        st.session_state.consecutive_losses = 0
        st.session_state.forced_break_until = None
        st.success("✅ System reset successful!")
        st.rerun()

st.markdown("---")

# Initialize session state
if 'selected_ticker_intraday' not in st.session_state:
    st.session_state.selected_ticker_intraday = ""

# Input Section
col1, col2 = st.columns([3, 1])

with col1:
    search_query = st.text_input("🔍 Search Stock or Index", 
                                 placeholder="e.g., RELIANCE.NS, TCS.NS, ^NSEI, ^BSESN...",
                                 help="Enter ticker with .NS/.BO suffix for stocks, or use ^ for indices (e.g., ^NSEI for NIFTY 50)",
                                 key="ticker_search_intraday")
    
    # Quick access buttons for common tickers
    st.markdown("**🚀 Quick Access:**")
    col_q1, col_q2, col_q3, col_q4, col_q5 = st.columns(5)
    with col_q1:
        if st.button("📊 NIFTY 50", use_container_width=True):
            st.session_state.selected_ticker_intraday = "^NSEI"
            st.rerun()
    with col_q2:
        if st.button("📊 SENSEX", use_container_width=True):
            st.session_state.selected_ticker_intraday = "^BSESN"
            st.rerun()
    with col_q3:
        if st.button("🛢️ RELIANCE", use_container_width=True):
            st.session_state.selected_ticker_intraday = "RELIANCE.NS"
            st.rerun()
    with col_q4:
        if st.button("💻 TCS", use_container_width=True):
            st.session_state.selected_ticker_intraday = "TCS.NS"
            st.rerun()
    with col_q5:
        if st.button("🏦 HDFCBANK", use_container_width=True):
            st.session_state.selected_ticker_intraday = "HDFCBANK.NS"
            st.rerun()
    
    if search_query and len(search_query) >= 2:
        # Skip search if user entered a properly formatted ticker
        is_formatted_ticker = (
            search_query.upper().endswith(('.NS', '.BO')) or 
            search_query.upper().startswith('^') or
            '.' in search_query  # Has any exchange suffix
        )
        
        if is_formatted_ticker:
            st.success(f"✅ Direct ticker entry detected: **{search_query.upper()}**")
            st.info("👇 Click '🚀 Analyze Now' to proceed")
        else:
            with st.spinner("🔍 Searching..."):
                search_results = search_stocks_online(search_query)
            
                if search_results:
                    st.markdown("**💡 Search Results:**")
                    
                    result_options = ["Select a stock..."] + [r['display'] for r in search_results]
                    selected_result = st.selectbox(
                        "Choose from results:", 
                        result_options,
                        label_visibility="collapsed",
                        key="select_result_intraday"
                    )
                    
                    if selected_result != "Select a stock...":
                        selected_ticker = selected_result.split(" - ")[0]
                        st.session_state.selected_ticker_intraday = selected_ticker
                        st.success(f"✅ Selected: {selected_result}")
                else:
                    st.info("💡 No results found. Try entering ticker with exchange (e.g., RELIANCE.NS, TCS.NS, ^NSEI)")
                    manual_ticker = st.text_input("Or enter ticker manually:", key="manual_ticker_intraday")
                    if manual_ticker:
                        st.session_state.selected_ticker_intraday = manual_ticker

with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    interval = st.selectbox("⏱️ Interval", 
                           ["5m", "15m", "30m", "1h"],
                           index=1)

# Show selected ticker
if st.session_state.selected_ticker_intraday:
    st.info(f"📊 Ready to analyze: **{st.session_state.selected_ticker_intraday}**")

# Analyze button
col1, col2 = st.columns([1, 3])
with col1:
    analyze_btn = st.button("🚀 Analyze Now", type="primary", use_container_width=True)
with col2:
    if st.button("🔄 Clear Selection", use_container_width=True):
        st.session_state.selected_ticker_intraday = ""
        st.rerun()

ticker = st.session_state.selected_ticker_intraday if st.session_state.selected_ticker_intraday else search_query

if analyze_btn and ticker:
    with st.spinner("🔄 Fetching data and analyzing..."):
        
        df, info = fetch_intraday_data(ticker, period="5d", interval=interval)
        
        if df is None or df.empty:
            db_client.log_search(st.session_state.username, ticker, {
                "signal": "FAILED TO FETCH",
                "interval": interval,
                "data_points": 0,
                "reason": "YFinance Fetch Error"
            })
        
        if df is not None and not df.empty:
            # =============================================================================
            # INSTITUTIONAL LAYER 1: DATA VALIDATION (FAIL-SAFE)
            # =============================================================================
            is_valid, quality_score, validation_msg = validate_data_integrity(df, ticker)
            
            if not is_valid:
                db_client.log_search(st.session_state.username, ticker, {
                    "signal": "SAFE MODE BLOCK",
                    "interval": interval,
                    "data_points": len(df),
                    "reason": validation_msg
                })
                st.error(f"🛡️ **SAFE MODE ACTIVATED**")
                st.error(f"❌ {validation_msg}")
                st.warning("Data quality issue detected. Analysis aborted to prevent false signals.")
                st.info("**Recommended Actions:**\n- Try different ticker symbol\n- Check if market is open\n- Verify ticker exchange suffix (.NS or .BO)")
            else:
                # Show data quality if not perfect
                if quality_score < 100:
                    st.warning(f"⚠️ Data Quality: {quality_score}/100 - Proceeding with caution")
                
                # Get current IST time
                current_ist_time = datetime.now(IST)
                current_date = current_ist_time.date()
                
                # =============================================================================
                # INSTITUTIONAL LAYER 2: MARKET CONTEXT INTELLIGENCE
                # =============================================================================
                with st.spinner("🌐 Fetching market context (NIFTY, VIX)..."):
                    market_context = fetch_market_context()
                
                # Display warning if market context fetch had issues
                if market_context.get('error'):
                    st.warning(f"⚠️ Market context fetch issue: Using fallback values. {market_context['error']}")
                elif market_context['nifty_bias'] == 'UNKNOWN':
                    st.info("ℹ️ ^NSEI data unavailable - Using fallback market context values")
                
                # =============================================================================
                # INSTITUTIONAL LAYER 3: TRADE DISCIPLINE CHECKS
                # =============================================================================
                
                # Check cooldown
                is_cooldown, cooldown_msg = check_trade_cooldown(ticker, current_ist_time)
                
                # Check daily limits
                limit_reached, limit_msg = check_daily_limits(ticker, current_date)
                
                # Detect candle interval
                candle_interval = detect_candle_interval(df)
                
                # Get current session
                session_name, session_rules = get_current_session(current_ist_time)
                
                # =============================================================================
                # INSTITUTIONAL LAYER 4: DIRECTIONAL BIAS ENGINE
                # =============================================================================
                primary_bias, bias_strength, invalidation_price = establish_directional_bias(df, ticker)
                
                # =============================================================================
                # INSTITUTIONAL LAYER 5: LOOPHOLE DETECTION
                # =============================================================================
                
                # Check consolidation (prevents flip-flopping)
                is_consolidating, consolidation_range = check_consolidation_lock(df)
                
                # Validate volume quality (prevents volume traps)
                volume_quality, volume_ratio = validate_volume_quality(df, ticker)
                
                # Calculate indicators
                support, resistance = calculate_support_resistance(df)
                trend = detect_trend(df)
                patterns, future_trend, prediction_reasons = detect_candlestick_patterns(df)
                
                # Check for no-trade conditions
                is_no_trade_zone = detect_no_trade_zone(df)
                is_false_breakout = detect_false_breakout(df)
                is_gap_day, gap_pct = detect_gap_day(df)
                vwap_deviated, vwap_dev_pct = check_vwap_deviation(df)
                market_regime = detect_market_regime(df)
                
                # Check trap zones
                current_price = df['Close'].iloc[-1]
                in_trap_zone, trap_msg = check_trap_zones(ticker, current_price)
                
                # Calculate signals with session awareness
                signals = calculate_entry_exit(df, support, resistance, trend[0], session_name)
                
                # Check move exhaustion (prevents late entries)
                is_exhausted, move_pct, exhaustion_msg = detect_move_exhaustion(df, signals['signal'])
                
                # Calculate target time windows
                entry_time = df.index[-1]
                target_windows, target_candles = calculate_target_time_windows(df, entry_time, candle_interval)
                
                # Check signal expiry
                is_expired, expiry_time = check_signal_expiry(entry_time, current_ist_time, candle_interval)
                
                # =============================================================================
                # INSTITUTIONAL LAYER 6: INTELLIGENT CONFIDENCE ADJUSTMENT
                # =============================================================================
                
                # Base confidence from technical analysis
                confidence_score, confidence_level, confidence_color, score_reasons = calculate_confidence_score(
                    df, trend[0], signals, support, resistance, session_name, market_regime
                )
                
                # Adjust for market context and memory
                adjusted_confidence, context_adjustments = adjust_confidence_for_market_context(
                    confidence_score, ticker, signals['signal'], market_context
                )
                
                # Apply final confidence
                final_confidence = adjusted_confidence
                all_reasons = score_reasons + context_adjustments
                
                # Update confidence level based on final score
                if final_confidence >= 75:
                    confidence_level = "HIGH CONFIDENCE"
                    confidence_color = "🟢"
                elif final_confidence >= 50:
                    confidence_level = "MEDIUM CONFIDENCE"
                    confidence_color = "🟡"
                else:
                    confidence_level = "LOW CONFIDENCE - AVOID"
                    confidence_color = "🔴"
                
                current_price = df['Close'].iloc[-1]
                price_change = df['Close'].iloc[-1] - df['Close'].iloc[-2]
                price_change_pct = (price_change / df['Close'].iloc[-2]) * 100
                
                vwap_current = calculate_vwap(df).iloc[-1]
                is_volume_spike, volume_ratio_old = detect_volume_spike(df)
                
                # --- CAPTURE ANALYSIS RESULTS IN DB ---
                has_entry = signals['signal'] != "WAIT"
                details = {
                    "signal": signals['signal'],
                    "confidence": f"{final_confidence:.0f}%",
                    "entry": float(signals.get('entry', 0.0)) if has_entry else 0.0,
                    "target_1": float(signals.get('targets', {}).get('Target-1', 0.0)) if has_entry else None,
                    "stop_loss": float(signals.get('stop_loss', 0.0)) if has_entry else None,
                    "reason": all_reasons[0] if len(all_reasons) > 0 else "Analysis completed",
                    "interval": interval,
                    "data_points": len(df)
                }
                db_client.log_search(st.session_state.username, ticker, details)
                # --------------------------------------
                
                # =============================================================================
                # DISPLAY: MARKET CONTEXT & INTELLIGENCE
                # =============================================================================
                
                # Market Context Banner
                st.markdown("### 🌐 Market Intelligence Layer")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    nifty_color = "🟢" if market_context['nifty_bias'] == "BULLISH" else "🔴" if market_context['nifty_bias'] == "BEARISH" else "🟡"
                    st.metric("NIFTY 50 Bias", f"{nifty_color} {market_context['nifty_bias']}", 
                             f"{market_context['nifty_change']:+.2f}%")
                
                with col2:
                    vix_color = "🔴" if market_context['vix'] > 20 else "🟡" if market_context['vix'] > 15 else "🟢"
                    st.metric("India VIX", f"{vix_color} {market_context['vix']:.1f}", 
                             market_context['risk_level'])
                
                with col3:
                    bias_color = "🟢" if primary_bias == "BULLISH" else "🔴" if primary_bias == "BEARISH" else "🟡"
                    st.metric(f"{ticker} Bias", f"{bias_color} {primary_bias}", 
                             f"{bias_strength:.0f}% strength")
                
                with col4:
                    if volume_quality == "INDEX_NO_VOLUME":
                        volume_color = "📊"
                        display_text = "Index (N/A)"
                        display_value = "Volume not applicable"
                    else:
                        volume_color = "🔥" if volume_quality == "HIGH_QUALITY_SUSTAINED" else "⚠️" if volume_quality == "ISOLATED_SPIKE_TRAP" else "📊"
                        display_text = f"{volume_color} {volume_quality.replace('_', ' ')}"
                        display_value = f"{volume_ratio:.1f}x"
                    st.metric("Volume Quality", display_text, display_value)
                
                st.markdown("---")
                
                # Display Session Info
                st.markdown("### ⏰ Market Session & Time")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Current Time (IST)", current_ist_time.strftime("%H:%M"))
                with col2:
                    session_color = "🟢" if session_name in ["Best", "Opening", "Late"] else "🔴"
                    st.metric("Trading Session", f"{session_color} {session_name}")
                with col3:
                    st.metric("Candle Interval", f"{candle_interval} min")
                with col4:
                    st.metric("Market Regime", market_regime)
                
                st.info(f"**Session Rules:** {session_rules}")
                
                # =============================================================================
                # CRITICAL ALERTS & BLOCKS (INSTITUTIONAL SAFETY LAYER)
                # =============================================================================
                
                # FORCED BREAK WARNING
                if st.session_state.forced_break_until and current_ist_time < st.session_state.forced_break_until:
                    remaining_min = (st.session_state.forced_break_until - current_ist_time).total_seconds() / 60
                    st.error(f"""
                    ### 🛑 FORCED BREAK MODE ACTIVE
                    **2 Consecutive Losses Detected - Mandatory 90-Minute Break**
                    
                    Time Remaining: {remaining_min:.0f} minutes
                    Resume Trading: {st.session_state.forced_break_until.strftime('%H:%M IST')}
                    
                    **Reason:** Preventing revenge trading and emotional decisions
                    """)
                    st.stop()  # Halt all analysis
                
                # COOLDOWN ALERT
                if is_cooldown:
                    st.warning(f"⏸️ **COOLDOWN ACTIVE:** {cooldown_msg}")
                
                # DAILY LIMIT ALERT
                if limit_reached:
                    st.error(f"🚫 **TRADE LIMIT REACHED:** {limit_msg}")
                    st.info("**Daily Statistics:**\n" + 
                           f"- Total Trades Today: {st.session_state.daily_trade_count['total']}/10\n" +
                           f"- {ticker} Trades: {st.session_state.daily_trade_count['per_ticker'].get(ticker, 0)}/3\n" +
                           f"- Consecutive Losses: {st.session_state.consecutive_losses}")
                    st.stop()
                    
                    # CONSOLIDATION LOCK WARNING
                    if is_consolidating:
                        st.markdown("""
                        <div class="no-trade-zone">
                            <h2>🔒 CONSOLIDATION LOCK - Signal Flip-Flop Prevention</h2>
                            <p><strong>Detected:</strong> Price oscillating in {:.2f}% range with multiple VWAP crossings</p>
                            <p><strong>Action:</strong> Wait for clear breakout beyond range with volume confirmation</p>
                            <p><strong>Risk:</strong> Whipsaw trades and consecutive stop losses in this zone</p>
                        </div>
                        """.format(consolidation_range), unsafe_allow_html=True)
                    
                    # VOLUME TRAP ALERT
                    if volume_quality == "ISOLATED_SPIKE_TRAP":
                        st.error(f"""
                        ⚠️ **VOLUME TRAP DETECTED**
                        
                        Current volume spike ({volume_ratio:.1f}x average) appears isolated.
                        This is likely a single institutional block trade, not sustained buying/selling.
                        
                        **Action:** Wait for next candle to confirm volume follow-through before entry.
                        """)
                    
                    # MOVE EXHAUSTION WARNING
                    if is_exhausted:
                        st.error(f"""
                        🚫 **MOVE EXHAUSTION - Late Entry Blocked**
                        
                        {exhaustion_msg}
                        
                        **Risk:** Buying at top / Selling at bottom
                        **Action:** Wait for pullback to VWAP or EMA-21
                        """)
                    
                    # TRAP ZONE WARNING
                    if in_trap_zone:
                        st.error(f"""
                        ⚠️ **HISTORICAL TRAP ZONE DETECTED**
                        
                        {trap_msg}
                        
                        This price level has generated false signals before.
                        Confidence requirement increased to 85/100.
                        """)
                    
                    # DIRECTIONAL BIAS CONFLICT
                    if signals['signal'] in ["BUY", "SELL"]:
                        signal_bias = "BULLISH" if signals['signal'] == "BUY" else "BEARISH"
                        if primary_bias != "NEUTRAL" and signal_bias != primary_bias:
                            st.warning(f"""
                            ⚠️ **BIAS CONFLICT WARNING**
                            
                            Established {ticker} Bias: **{primary_bias}** ({bias_strength:.0f}% strength)
                            Current Signal: **{signals['signal']}** ({signal_bias})
                            
                            Trading against established bias - High risk of failure
                            Confidence has been downgraded by 30 points
                            """)
                    
                    # VIX HIGH RISK ALERT
                    if market_context['vix'] > 20:
                        st.warning(f"""
                        ⚠️ **HIGH VOLATILITY ENVIRONMENT**
                        
                        India VIX: {market_context['vix']:.1f} (HIGH)
                        
                        Wider stop-losses recommended
                        Confidence threshold increased
                        Consider reducing position size by 50%
                        """)
                    
                    st.warning(f"⚠️ **GAP DAY DETECTED:** Opening gap of {gap_pct:.2f}% - Wait 15-30 minutes for VWAP stabilization")
                
                st.markdown("---")
                
                # Display metrics
                st.markdown("### 📈 Current Market Status")
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                
                with col1:
                    st.metric("Current Price", f"₹{current_price:.2f}", 
                             f"{price_change_pct:+.2f}%")
                with col2:
                    st.metric("Trend", trend[0], trend[1])
                with col3:
                    st.metric("Support", f"₹{support:.2f}")
                with col4:
                    st.metric("Resistance", f"₹{resistance:.2f}")
                with col5:
                    rsi_current = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
                    st.metric("RSI", f"{rsi_current:.1f}")
                with col6:
                    st.metric("VWAP", f"₹{vwap_current:.2f}")
                
                st.markdown("---")
                
                # NO-TRADE WARNINGS
                if is_no_trade_zone:
                    st.markdown("""
                    <div class="no-trade-zone">
                        <h2>🚫 NO TRADE ZONE - MARKET CONSOLIDATING</h2>
                        <p>Price between EMAs, RSI neutral, low volume - Wait for clear breakout</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                if is_false_breakout:
                    st.error("⚠️ **FALSE BREAKOUT DETECTED** - Volume collapse after spike. Avoid this trade!")
                
                if vwap_deviated:
                    st.warning(f"⚠️ **Price too far from VWAP** ({vwap_dev_pct:.2f}% deviation) - Avoid late entries")
                
                if market_regime == "RANGE DAY" and signals['signal'] in ["BUY", "SELL"]:
                    st.warning("⚠️ **RANGE DAY** - Trend strategies may fail. Consider range-bound strategies instead.")
                
                st.markdown("---")
                
                # Confidence Score with Institutional Adjustments
                st.markdown("### 🎯 Institutional-Grade Confidence Score")
                
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.markdown(f"""
                    <div style="background-color: rgba(128, 128, 128, 0.1); padding: 20px; border-radius: 10px; text-align: center;">
                        <h1 style="color: {'#4CAF50' if final_confidence >= 75 else '#FFC107' if final_confidence >= 50 else '#f44336'}; margin: 0;">{final_confidence:.0f}/100</h1>
                        <h3 style="margin: 10px 0;">{confidence_color} {confidence_level}</h3>
                        <p style="margin: 5px 0; font-size: 0.9em;">Base: {confidence_score:.0f} → Adjusted: {final_confidence:.0f}</p>
                        <p style="margin: 0;">Volume: {'🔥 High Quality' if volume_quality == 'HIGH_QUALITY_SUSTAINED' else '⚠️ Trap Risk' if volume_quality == 'ISOLATED_SPIKE_TRAP' else 'Normal'}</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown("**📊 Complete Score Analysis:**")
                    for reason in all_reasons:
                        if "✓" in reason or "✅" in reason:
                            st.success(reason)
                        elif "✗" in reason or "⚠️" in reason:
                            st.error(reason)
                        else:
                            st.info(reason)
                
                st.markdown("---")
                
                # Trading Signals
                st.markdown("### 🎯 Trading Signal & Entry Confirmation")
                
                signal_class = "buy-signal" if signals['signal'] == "BUY" else "sell-signal" if signals['signal'] == "SELL" else "neutral-signal"
                
                st.markdown(f"""
                <div class="{signal_class}">
                    <h2>{signals['signal']} SIGNAL - {signals['strategy_tag']}</h2>
                    <p><strong>Reason:</strong> {signals['reason']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Signal Expiry
                if not is_expired and signals['signal'] in ["BUY", "SELL"]:
                    st.success(f"✅ **Signal valid till:** {expiry_time.strftime('%H:%M IST')}")
                elif is_expired:
                    st.error(f"❌ **Signal EXPIRED** at {expiry_time.strftime('%H:%M IST')} - Target-1 not hit in time")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("#### 📍 Entry & Exit")
                    st.metric("Entry Price", f"₹{signals['entry']:.2f}")
                    st.metric("Stop Loss (with buffer)", f"₹{signals['stop_loss']:.2f}")
                    st.metric("Risk/Reward", f"{signals['risk_reward']:.2f}:1")
                    
                    # R:R warning
                    if signals['risk_reward'] > 0 and signals['risk_reward'] < 1.5:
                        st.warning("⚠️ R:R below 1.5 - Trade rejected!")
                
                with col2:
                    st.markdown("#### 🎯 Targets & Time Windows")
                    if target_windows['Target-1']:
                        st.metric(f"Target 1 @ {target_windows['Target-1']}", 
                                 f"₹{signals['target1']:.2f}", 
                                 f"+{signals['profit1_pct']:.2f}%" if signals['signal'] != "WAIT" else None)
                    else:
                        st.warning("Target-1: Exceeds market hours")
                    
                    if target_windows['Target-2']:
                        st.metric(f"Target 2 @ {target_windows['Target-2']}", 
                                 f"₹{signals['target2']:.2f}", 
                                 f"+{signals['profit2_pct']:.2f}%" if signals['signal'] != "WAIT" else None)
                    else:
                        st.warning("Target-2: Exceeds market hours")
                    
                    if target_windows['Target-3']:
                        st.metric(f"Target 3 @ {target_windows['Target-3']}", 
                                 f"₹{signals['target3']:.2f}", 
                                 f"+{signals['profit3_pct']:.2f}%" if signals['signal'] != "WAIT" else None)
                    else:
                        st.warning("Target-3: Exceeds market hours - Avoid this trade")
                
                with col3:
                    st.markdown("#### 📊 Key Levels")
                    st.metric("Support Level", f"₹{support:.2f}")
                    st.metric("Resistance Level", f"₹{resistance:.2f}")
                    distance_to_support = ((current_price - support) / current_price) * 100
                    st.metric("Distance to Support", f"{distance_to_support:.2f}%")
                
                st.markdown("---")
                
                # Candlestick Patterns
                st.markdown("### 🕯️ Candlestick Pattern Analysis")
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    candle_fig = create_candlestick_chart(df, patterns, future_trend, prediction_reasons)
                    st.plotly_chart(candle_fig, use_container_width=True)
                
                with col2:
                    st.markdown("#### 🔮 Pattern Prediction")
                    
                    st.markdown("**Detected Patterns:**")
                    for pattern, emoji, description in patterns:
                        st.markdown(f"{emoji} **{pattern}**")
                        st.caption(description)
                    
                    st.markdown("---")
                    
                    if future_trend == "BULLISH" or future_trend == "BULLISH_REVERSAL":
                        st.success(f"**📈 Predicted: {future_trend}**")
                    elif future_trend == "BEARISH" or future_trend == "BEARISH_REVERSAL":
                        st.error(f"**📉 Predicted: {future_trend}**")
                    else:
                        st.warning(f"**↔️ Predicted: {future_trend}**")
                    
                    if prediction_reasons:
                        st.markdown("**Why this prediction?**")
                        for reason in prediction_reasons:
                            st.info(f"💡 {reason}")
                
                st.markdown("---")
                
                # Interactive Chart
                st.markdown("### 📊 Interactive Price Chart with Indicators")
                fig = create_advanced_chart(df, support, resistance, signals, trend)
                st.plotly_chart(fig, use_container_width=True)
                
                st.markdown("---")
                
                # Trading Plan
                st.markdown("### 📋 Institutional Trading Plan")
                
                # Determine if signal should be blocked based on institutional checks
                signal_blocked = (is_cooldown or limit_reached or is_consolidating or 
                                is_exhausted or final_confidence < 60 or is_no_trade_zone or
                                (in_trap_zone and final_confidence < 85) or
                                (volume_quality == "ISOLATED_SPIKE_TRAP"))
                
                if signals['signal'] == "BUY" and final_confidence >= 60 and not signal_blocked:
                    st.success(f"""
                    **{signals['strategy_tag']} - BUY Setup (Confidence: {final_confidence:.0f}/100):**
                    
                    **📍 Entry Strategy:**
                    - **Entry Price:** ₹{signals['entry']:.2f} (After candle close confirmation)
                    - **Entry Time:** Enter after current candle closes above VWAP + EMA-9
                    
                    **🛡️ Risk Management:**
                    - **Stop Loss:** ₹{signals['stop_loss']:.2f} (Includes ATR buffer for SL-hunt protection)
                    - **Risk:Reward:** {signals['risk_reward']:.2f}:1
                    - **Position Size:** {'50% of normal' if market_context['vix'] > 18 else '70% of normal' if session_name in ['Opening', 'Late'] else 'Full size'}
                    
                    **🎯 Profit Targets:**
                    - **Target 1:** ₹{signals['target1']:.2f} (+{signals['profit1_pct']:.2f}%) @ {target_windows['Target-1']} - Book 1/3 position, Move SL to entry
                    - **Target 2:** ₹{signals['target2']:.2f} (+{signals['profit2_pct']:.2f}%) @ {target_windows['Target-2']} - Book 1/3 position, Move SL to EMA-9
                    - **Target 3:** ₹{signals['target3']:.2f} (+{signals['profit3_pct']:.2f}%) @ {target_windows['Target-3']} - Book remaining position
                    
                    **⏱️ Signal Expiry:** {expiry_time.strftime('%H:%M IST')} ({target_candles['Target-1']} candles)
                    
                    **✅ Confirmations:**
                    - Candle closed above VWAP (₹{vwap_current:.2f})
                    - MACD bullish crossover confirmed
                    - Volume: {volume_quality} ({volume_ratio:.1f}x average)
                    - {session_name} session - {session_rules}
                    - NIFTY Bias: {market_context['nifty_bias']} ({market_context['nifty_change']:+.2f}%)
                    - {ticker} Bias: {primary_bias} ({bias_strength:.0f}% strength)
                    
                    **📊 Institutional Context:**
                    - Market Context Score: {final_confidence:.0f}/100 (includes NIFTY, VIX, memory adjustments)
                    - Directional Bias: Aligned ✅
                    - Volume Quality: {volume_quality}
                    - Historical Performance: {'Strong' if ticker in st.session_state.ticker_memory and len([t for t in st.session_state.ticker_memory[ticker].get('last_10_trades', []) if t.get('outcome') == 'TARGET_HIT']) >= 3 else 'Building track record'}
                    
                    **⚠️ Discipline Rules:**
                    - Risk only 1-2% of capital
                    - No averaging down
                    - Max 3 trades per symbol per day
                    - Follow 30-min cooldown after SL
                    - System will track this trade for learning
                    """)
                    
                    # Update memory (simulated entry)
                    update_ticker_memory(ticker, signals, outcome=None)
                    
                elif signals['signal'] == "SELL" and final_confidence >= 60 and not signal_blocked:
                    st.error(f"""
                    **{signals['strategy_tag']} - SELL Setup (Confidence: {final_confidence:.0f}/100):**
                    
                    **📍 Entry Strategy:**
                    - **Entry Price:** ₹{signals['entry']:.2f} (After candle close confirmation)
                    - **Entry Time:** Enter after current candle closes below VWAP + EMA-9
                    
                    **🛡️ Risk Management:**
                    - **Stop Loss:** ₹{signals['stop_loss']:.2f} (Includes ATR buffer for SL-hunt protection)
                    - **Risk:Reward:** {signals['risk_reward']:.2f}:1
                    - **Position Size:** {'50% of normal' if market_context['vix'] > 18 else '70% of normal' if session_name in ['Opening', 'Late'] else 'Full size'}
                    
                    **🎯 Profit Targets:**
                    - **Target 1:** ₹{signals['target1']:.2f} (+{signals['profit1_pct']:.2f}%) @ {target_windows['Target-1']} - Book 1/3 position, Move SL to entry
                    - **Target 2:** ₹{signals['target2']:.2f} (+{signals['profit2_pct']:.2f}%) @ {target_windows['Target-2']} - Book 1/3 position, Move SL to EMA-9
                    - **Target 3:** ₹{signals['target3']:.2f} (+{signals['profit3_pct']:.2f}%) @ {target_windows['Target-3']} - Book remaining position
                    
                    **⏱️ Signal Expiry:** {expiry_time.strftime('%H:%M IST')} ({target_candles['Target-1']} candles)
                    
                    **✅ Confirmations:**
                    - Candle closed below VWAP (₹{vwap_current:.2f})
                    - MACD bearish crossover confirmed
                    - Volume: {volume_quality} ({volume_ratio:.1f}x average)
                    - {session_name} session - {session_rules}
                    - NIFTY Bias: {market_context['nifty_bias']} ({market_context['nifty_change']:+.2f}%)
                    - {ticker} Bias: {primary_bias} ({bias_strength:.0f}% strength)
                    
                    **📊 Institutional Context:**
                    - Market Context Score: {final_confidence:.0f}/100 (includes NIFTY, VIX, memory adjustments)
                    - Directional Bias: Aligned ✅
                    - Volume Quality: {volume_quality}
                    - Historical Performance: {'Strong' if ticker in st.session_state.ticker_memory and len([t for t in st.session_state.ticker_memory[ticker].get('last_10_trades', []) if t.get('outcome') == 'TARGET_HIT']) >= 3 else 'Building track record'}
                    
                    **⚠️ Discipline Rules:**
                    - Risk only 1-2% of capital
                    - No averaging down
                    - Max 3 trades per symbol per day
                    - Follow 30-min cooldown after SL
                    - System will track this trade for learning
                    """)
                    
                    # Update memory (simulated entry)
                    update_ticker_memory(ticker, signals, outcome=None)
                
                else:
                    # Comprehensive WAIT reasoning with institutional context
                    wait_reasons = [signals['reason']]
                    
                    if final_confidence < 60:
                        wait_reasons.append(f"❌ Confidence score: {final_confidence:.0f}/100 (Need ≥ 60)")
                    if is_cooldown:
                        wait_reasons.append(f"⏸️ {cooldown_msg}")
                    if limit_reached:
                        wait_reasons.append(f"🚫 {limit_msg}")
                    if is_consolidating:
                        wait_reasons.append(f"🔒 Consolidation detected ({consolidation_range:.2f}% range)")
                    if is_exhausted:
                        wait_reasons.append(f"🚫 Move exhausted: {exhaustion_msg}")
                    if in_trap_zone:
                        wait_reasons.append(f"⚠️ {trap_msg}")
                    if volume_quality == "ISOLATED_SPIKE_TRAP":
                        wait_reasons.append("⚠️ Volume trap - Isolated spike without follow-through")
                    if is_no_trade_zone:
                        wait_reasons.append("❌ No-trade zone detected")
                    if session_name in ["Midday", "Closing"]:
                        wait_reasons.append(f"⏰ Poor session timing ({session_name})")
                    
                    st.warning(f"""
                    **🛑 WAIT for Better Setup - Institutional Safety System Active**
                    
                    **Primary Reason:** {signals['reason']}
                    
                    **Complete Block Reasons:**
                    """)
                    
                    for reason in wait_reasons:
                        st.error(f"• {reason}")
                    
                    st.info(f"""
                    **📊 Current State:**
                    - Confidence: {final_confidence:.0f}/100 (Base: {confidence_score:.0f})
                    - Session: {session_name}
                    - NIFTY: {market_context['nifty_bias']} ({market_context['nifty_change']:+.2f}%)
                    - Bias: {primary_bias} ({bias_strength:.0f}%)
                    - Volume: {volume_quality}
                    - VIX: {market_context['vix']:.1f} ({market_context['risk_level']})
                    
                    **Remember:** No trade is better than a forced trade!
                    """)
                
                st.info("⚠️ **Disclaimer:** This is decision assistance with institutional-grade safety layers, not guaranteed signals. Always manage risk and do your own analysis.")
                
                # System Status Dashboard
                st.markdown("---")
                st.markdown("### 🖥️ System Status & Memory")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    today_trades = st.session_state.daily_trade_count.get('total', 0)
                    st.metric("Today's Trades", f"{today_trades}/10", 
                             "🟢 Available" if today_trades < 8 else "⚠️ Near Limit")
                
                with col2:
                    ticker_trades = st.session_state.daily_trade_count.get('per_ticker', {}).get(ticker, 0)
                    st.metric(f"{ticker} Today", f"{ticker_trades}/3",
                             "🟢 Available" if ticker_trades < 3 else "🔴 Limit Reached")
                
                with col3:
                    losses = st.session_state.consecutive_losses
                    st.metric("Consecutive Losses", losses,
                             "🟢 Normal" if losses == 0 else "⚠️ Caution" if losses == 1 else "🔴 Break Mode")
                
                with col4:
                    tracked_tickers = len(st.session_state.ticker_memory)
                    st.metric("Tracked Tickers", tracked_tickers,
                             "Learning..." if tracked_tickers < 10 else "Database Building")
                
                # Show trade history if available
                if ticker in st.session_state.ticker_memory:
                    with st.expander(f"📊 {ticker} Historical Memory"):
                        memory = st.session_state.ticker_memory[ticker]
                        recent_trades = memory.get('last_10_trades', [])[-5:]
                        
                        if recent_trades:
                            st.markdown("**Last 5 Trades:**")
                            for i, trade in enumerate(reversed(recent_trades), 1):
                                outcome_icon = "✅" if trade.get('outcome') == 'TARGET_HIT' else "❌" if trade.get('outcome') == 'STOP_LOSS' else "⏳"
                                st.write(f"{i}. {outcome_icon} {trade['signal']} @ ₹{trade['entry']:.2f} - {trade.get('outcome', 'Pending')}")
                        else:
                            st.info("No trade history yet for this ticker")
                        
                        trap_zones = memory.get('trap_zones', {})
                        if trap_zones:
                            st.markdown("**⚠️ Known Trap Zones:**")
                            for zone, data in trap_zones.items():
                                st.warning(f"₹{zone} - {data['count']} failures")
                
                st.info("⚠️ **Disclaimer:** This is decision assistance with institutional-grade safety layers, not guaranteed signals. Always manage risk and do your own analysis.")
                
        else:
            st.error("❌ Data fetch failed. Please check ticker symbol and try again.")
            st.info("""**Common Issues:**
- **Invalid ticker symbol**: Make sure you're using the correct format
- **Indian stocks**: Add .NS (NSE) or .BO (BSE) suffix (e.g., RELIANCE.NS)
- **Indices**: Use ^ prefix (e.g., ^NSEI for NIFTY 50)
- **Network issues**: Check your internet connection
- **Market hours**: Data may be unavailable outside trading hours

**Examples of valid tickers:**
- RELIANCE.NS (Reliance Industries on NSE)
- TCS.BO (TCS on BSE)  
- ^NSEI (NIFTY 50 Index)
- AAPL (Apple - US stock)""")
    
    st.markdown("---")
    st.markdown("### 🏛️ Institutional-Grade Trading Engine Features")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **🧠 Intelligence Layers:**
        - Market context (NIFTY, VIX) integration
        - Directional bias engine (prevents flip-flop)
        - Historical memory & learning
        - Trap zone detection
        - Move exhaustion prevention
        
        **🛡️ Safety & Discipline:**
        - Trade cooldown enforcement (30 min after SL)
        - Daily limits (10 total, 3 per ticker)
        - Forced break after 2 consecutive losses
        - Consolidation lock (prevents whipsaw)
        - Volume trap detection
        
        **🕐 Time & Session Awareness:**
        - IST timezone conversion
        - Market session detection
        - Target time window calculation
        - Signal expiry tracking
        - Gap day detection
        """)
    
    with col2:
        st.markdown("""
        **📊 Technical Analysis:**
        - Multi-EMA trend detection
        - VWAP analysis with context
        - RSI & MACD confirmation
        - Support/Resistance (quantile-based)
        - Candlestick pattern recognition
        
        **🎯 Risk Management:**
        - ATR-based stop-loss with buffer
        - Risk:Reward enforcement (min 1.5:1)
        - Candle-close confirmation only
        - Partial exit strategy
        - Dynamic position sizing
        
        **🚫 Loophole Prevention:**
        - Indicator conflict resolution
        - Late entry blocking
        - Context-aware VWAP deviation
        - Regime-based strategy adjustment
        - Sustained volume validation
        """)