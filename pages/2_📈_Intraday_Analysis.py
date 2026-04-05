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
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_db import db_client
from app import check_auth, show_sidebar_user_info, inject_login_css

# Page config is set in Home.py

# ── Authentication Gate ──
if not check_auth():
    st.stop()

inject_login_css()
show_sidebar_user_info()

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
# --- V2 UPGRADE START: Additional session state for V2 features ---
if 'signal_stability_buffer' not in st.session_state:
    st.session_state.signal_stability_buffer = {}  # {ticker: {'signal': str, 'count': int}}
if 'trade_stats' not in st.session_state:
    st.session_state.trade_stats = {
        'total_wins': 0, 'total_losses': 0, 'total_trades': 0,
        'total_profit_pct': 0.0, 'total_loss_pct': 0.0,
        'hold_times': [], 'daily_pnl': [], 'max_drawdown': 0.0
    }
if 'daily_pnl_tracker' not in st.session_state:
    st.session_state.daily_pnl_tracker = {'date': None, 'pnl': 0.0, 'peak': 0.0, 'drawdown': 0.0}
# --- V2 UPGRADE END ---

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
    
    # Check 5: Calculate quality score
    quality_score = 100
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
    
    # Check consecutive losses — V2 DRAWDOWN PROTECTION: 3 losses = full day block
    if st.session_state.consecutive_losses >= 3:
        return True, "🛑 DRAWDOWN PROTECTION: 3 consecutive losses — Trading blocked for the rest of the day"
    
    return False, ""

def update_ticker_memory(ticker, signal, outcome=None):
    """
    MEMORY: Store trade outcomes and build historical context
    """
    if ticker not in st.session_state.ticker_memory:
        st.session_state.ticker_memory[ticker] = {
            'last_10_trades': [],
            'trap_zones': {},
            'session_performance': {'Opening': [], 'Best': [], 'Late': []},
            'total_trades': 0
        }
    
    memory = st.session_state.ticker_memory[ticker]
    
    # Store trade
    trade_record = {
        'timestamp': datetime.now(IST),
        'signal': signal['signal'],
        'entry': signal['entry'],
        'outcome': outcome,
        'session': signal.get('strategy_tag', 'UNKNOWN')
    }
    
    memory['last_10_trades'].append(trade_record)
    if len(memory['last_10_trades']) > 10:
        memory['last_10_trades'].pop(0)
    
    memory['total_trades'] += 1
    
    # Track trap zones (failed signals at similar price levels)
    if outcome == 'STOP_LOSS':
        price_zone = round(signal['entry'] / 10) * 10  # Round to nearest 10
        if price_zone not in memory['trap_zones']:
            memory['trap_zones'][price_zone] = {'count': 0, 'last_occurred': None}
        memory['trap_zones'][price_zone]['count'] += 1
        memory['trap_zones'][price_zone]['last_occurred'] = datetime.now(IST)

def check_trap_zones(ticker, current_price):
    """
    MEMORY: Check if current price is near known trap zones
    """
    if ticker not in st.session_state.ticker_memory:
        return False, ""
    
    memory = st.session_state.ticker_memory[ticker]
    trap_zones = memory.get('trap_zones', {})
    
    for price_zone, data in trap_zones.items():
        if abs(current_price - price_zone) < 20 and data['count'] >= 3:
            return True, f"Trap zone detected near ₹{price_zone} - {data['count']} previous failures"
    
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
    """
    V2 UPGRADE: True Intraday VWAP with daily reset at 9:15 IST
    Resets each day - only cumulates for current trading session
    """
    if df is None or len(df) == 0:
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        return (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()

    result = pd.Series(index=df.index, dtype=float)
    try:
        # Calculate VWAP per day (daily reset)
        for date in df.index.map(lambda x: x.date()).unique():
            day_mask = df.index.date == date
            day_df = df[day_mask]
            if len(day_df) == 0:
                continue
            typical_price = (day_df['High'] + day_df['Low'] + day_df['Close']) / 3
            vol = day_df['Volume']
            cum_v = vol.cumsum().replace(0, 1)  # Avoid div/0
            day_vwap = (typical_price * vol).cumsum() / cum_v
            result[day_mask] = day_vwap.values
    except Exception:
        # Fallback to original cumulative calculation
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        result = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
    return result

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

def calculate_confidence_score(df, trend, signals, support, resistance, session_name, market_regime, structure_score=50):
    """
    V2 UPGRADE: Institutional Confidence Weighting
    Trend=30 | Volume=20 | VWAP=15 | Market Context=15 | Structure=20 — Total=100
    Session and regime are applied as modifiers within the 0-100 cap.
    """
    score = 0
    reasons = []
    current_price = df['Close'].iloc[-1]

    # 1. TREND ALIGNMENT — 30 points (V2: increased from 20)
    if "UPTREND" in trend and signals['signal'] == "BUY":
        score += 30
        reasons.append("✓ Trend aligned bullish (30)")
    elif "DOWNTREND" in trend and signals['signal'] == "SELL":
        score += 30
        reasons.append("✓ Trend aligned bearish (30)")
    elif ("UPTREND" in trend and signals['signal'] == "SELL") or ("DOWNTREND" in trend and signals['signal'] == "BUY"):
        score += 0
        reasons.append("✗ Signal against trend (0)")
    else:
        score += 10
        reasons.append("△ Sideways trend - partial (10)")

    # 2. VOLUME — 20 points (V2: increased from 10)
    is_spike, volume_ratio = detect_volume_spike(df)
    vol_quality, _ = validate_volume_quality(df)
    if vol_quality == "HIGH_QUALITY_SUSTAINED":
        score += 20
        reasons.append(f"✓ High quality sustained volume (20)")
    elif is_spike and vol_quality != "ISOLATED_SPIKE_TRAP":
        score += 14
        reasons.append(f"✓ Volume spike confirmed ({volume_ratio:.1f}x) (14)")
    elif vol_quality == "ISOLATED_SPIKE_TRAP":
        score += 0
        reasons.append("✗ Isolated volume spike trap (0)")
    elif vol_quality == "MODERATE_VOLUME":
        score += 10
        reasons.append("△ Moderate volume (10)")
    else:
        score += 4
        reasons.append("✗ Low volume (4)")

    # 3. VWAP CONFIRMATION — 15 points (unchanged)
    vwap = calculate_vwap(df).iloc[-1]
    if signals['signal'] == "BUY" and current_price > vwap:
        score += 15
        reasons.append("✓ Price above VWAP (15)")
    elif signals['signal'] == "SELL" and current_price < vwap:
        score += 15
        reasons.append("✓ Price below VWAP (15)")
    else:
        reasons.append("✗ VWAP not confirming (0)")

    # 4. MARKET CONTEXT (RSI + MACD) — 15 points (V2: combined from 30)
    rsi = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
    macd_indicator = MACD(df['Close'])
    macd_line = macd_indicator.macd().iloc[-1]
    signal_line_macd = macd_indicator.macd_signal().iloc[-1]
    ctx_pts = 0
    if signals['signal'] == "BUY":
        if 30 < rsi < 70:
            ctx_pts += 7
            reasons.append("✓ RSI favorable for BUY (7)")
        if macd_line > signal_line_macd:
            ctx_pts += 8
            reasons.append("✓ MACD bullish crossover (8)")
    elif signals['signal'] == "SELL":
        if 30 < rsi < 70:
            ctx_pts += 7
            reasons.append("✓ RSI favorable for SELL (7)")
        if macd_line < signal_line_macd:
            ctx_pts += 8
            reasons.append("✓ MACD bearish crossover (8)")
    if ctx_pts == 0 and signals['signal'] in ["BUY", "SELL"]:
        reasons.append("✗ Market context (RSI+MACD) not confirming (0)")
    score += min(15, ctx_pts)

    # 5. MARKET STRUCTURE — 20 points (V2 NEW: driven by BOS/CHOCH engine)
    structure_pts = int((structure_score / 100) * 20)
    score += structure_pts
    if structure_pts >= 16:
        reasons.append(f"✓ Strong market structure - BOS/CHOCH confirmed ({structure_pts})")
    elif structure_pts >= 12:
        reasons.append(f"✓ Moderate market structure ({structure_pts})")
    else:
        reasons.append(f"△ Weak/neutral market structure ({structure_pts})")

    # SESSION MODIFIER (bonus/penalty, capped within 0-100)
    if session_name == "Best":
        score = min(100, score + 5)
        reasons.append("✓ Best trading session (+5 bonus)")
    elif session_name in ["Opening", "Late"]:
        score = min(100, score + 2)
        reasons.append(f"✓ Acceptable session {session_name} (+2)")
    elif session_name in ["Midday", "Closing"]:
        score = max(0, score - 10)
        reasons.append(f"✗ Poor session ({session_name}) (-10 penalty)")

    # MARKET REGIME MODIFIER
    if market_regime == "TREND DAY" and signals['signal'] in ["BUY", "SELL"]:
        score = min(100, score + 3)
        reasons.append("✓ Trend day confirmed (+3 bonus)")
    elif market_regime == "RANGE DAY" and signals['signal'] in ["BUY", "SELL"]:
        score = max(0, score - 8)
        reasons.append("✗ Range day - trend strategy risk (-8)")

    score = max(0, min(100, score))

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

# =============================================================================
# --- V2 UPGRADE START: INSTITUTIONAL V2.0 ENGINE FUNCTIONS ---
# =============================================================================

def detect_market_structure(df):
    """
    V2: Market Structure Engine
    Detects Swing Highs/Lows, Break of Structure (BOS), Change of Character (CHOCH)
    Bias depends on BOS — replaces primitive high[i] > high[i-5] logic.
    """
    if len(df) < 30:
        return {
            'swing_highs': [], 'swing_lows': [], 'bos': None, 'choch': None,
            'structure_bias': 'NEUTRAL', 'structure_score': 40,
            'last_bos_level': None, 'last_choch_level': None
        }

    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    lookback = 5

    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        if highs[i] == max(highs[i - lookback:i + lookback + 1]):
            swing_highs.append({'idx': i, 'price': highs[i], 'time': df.index[i]})
        if lows[i] == min(lows[i - lookback:i + lookback + 1]):
            swing_lows.append({'idx': i, 'price': lows[i], 'time': df.index[i]})

    bos = None
    choch = None
    current_price = closes[-1]

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        recent_sh = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
        recent_sl = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows

        last_sh = recent_sh[-1]['price']
        prev_sh = recent_sh[-2]['price'] if len(recent_sh) >= 2 else last_sh
        last_sl = recent_sl[-1]['price']
        prev_sl = recent_sl[-2]['price'] if len(recent_sl) >= 2 else last_sl

        # BOS Bullish: price breaks above last swing high in uptrend
        if current_price > last_sh and last_sh >= prev_sh:
            bos = {'type': 'BULLISH', 'level': round(last_sh, 2),
                   'description': f'BOS: Price broke above swing high ₹{last_sh:.2f}'}
        # BOS Bearish
        elif current_price < last_sl and last_sl <= prev_sl:
            bos = {'type': 'BEARISH', 'level': round(last_sl, 2),
                   'description': f'BOS: Price broke below swing low ₹{last_sl:.2f}'}

        # CHOCH Bearish: was making HH, now breaks below HL
        if last_sh > prev_sh and current_price < last_sl:
            choch = {'type': 'BEARISH', 'level': round(last_sl, 2),
                     'description': f'CHOCH: Trend reversal (bearish) at ₹{last_sl:.2f}'}
        # CHOCH Bullish: was making LL, now breaks above LH
        elif last_sl < prev_sl and current_price > last_sh:
            choch = {'type': 'BULLISH', 'level': round(last_sh, 2),
                     'description': f'CHOCH: Trend reversal (bullish) at ₹{last_sh:.2f}'}

    # Determine structure bias + score
    if bos and bos['type'] == 'BULLISH':
        structure_bias, structure_score = 'BULLISH', 80
    elif bos and bos['type'] == 'BEARISH':
        structure_bias, structure_score = 'BEARISH', 80
    elif choch and choch['type'] == 'BULLISH':
        structure_bias, structure_score = 'BULLISH', 70
    elif choch and choch['type'] == 'BEARISH':
        structure_bias, structure_score = 'BEARISH', 70
    else:
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            sh_p = [s['price'] for s in swing_highs[-3:]]
            sl_p = [s['price'] for s in swing_lows[-3:]]
            hh = sum(sh_p[i] > sh_p[i - 1] for i in range(1, len(sh_p)))
            hl = sum(sl_p[i] > sl_p[i - 1] for i in range(1, len(sl_p)))
            lh = sum(sh_p[i] < sh_p[i - 1] for i in range(1, len(sh_p)))
            ll = sum(sl_p[i] < sl_p[i - 1] for i in range(1, len(sl_p)))
            if hh + hl > lh + ll:
                structure_bias, structure_score = 'BULLISH', 60
            elif lh + ll > hh + hl:
                structure_bias, structure_score = 'BEARISH', 60
            else:
                structure_bias, structure_score = 'NEUTRAL', 40
        else:
            structure_bias, structure_score = 'NEUTRAL', 40

    return {
        'swing_highs': swing_highs[-5:],
        'swing_lows': swing_lows[-5:],
        'bos': bos,
        'choch': choch,
        'structure_bias': structure_bias,
        'structure_score': structure_score,
        'last_bos_level': bos['level'] if bos else None,
        'last_choch_level': choch['level'] if choch else None
    }


@st.cache_data(ttl=300)
def fetch_mtf_data(ticker, period="5d"):
    """V2: Multi-Timeframe Data Fetch — HTF=1h, LTF=5m"""
    try:
        stock = yf.Ticker(ticker)
        df_htf = stock.history(period=period, interval="1h")
        if not df_htf.empty:
            df_htf.index = df_htf.index.tz_convert(IST)
        df_ltf = stock.history(period="2d", interval="5m")
        if not df_ltf.empty:
            df_ltf.index = df_ltf.index.tz_convert(IST)
        return df_htf, df_ltf
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def get_mtf_bias(ticker, df_htf, df_ltf, selected_interval):
    """
    V2: Multi-Timeframe Confirmation
    BUY only if HTF bullish; LTF must align for entry.
    Confidence bonus if aligned.
    """
    result = {
        'htf_bias': 'NEUTRAL', 'ltf_bias': 'NEUTRAL',
        'mtf_aligned': False, 'confidence_bonus': 0,
        'recommendation': 'WAIT', 'htf_details': '', 'ltf_details': ''
    }

    if df_htf is not None and len(df_htf) >= 21:
        htf_ema9 = EMAIndicator(df_htf['Close'], window=9).ema_indicator()
        htf_ema21 = EMAIndicator(df_htf['Close'], window=21).ema_indicator()
        htf_price = df_htf['Close'].iloc[-1]
        if htf_price > htf_ema9.iloc[-1] > htf_ema21.iloc[-1]:
            result['htf_bias'] = 'BULLISH'
            result['htf_details'] = '1H: Price > EMA9 > EMA21 (Bullish)'
        elif htf_price < htf_ema9.iloc[-1] < htf_ema21.iloc[-1]:
            result['htf_bias'] = 'BEARISH'
            result['htf_details'] = '1H: Price < EMA9 < EMA21 (Bearish)'
        else:
            result['htf_details'] = '1H: Mixed EMA alignment'

    if df_ltf is not None and len(df_ltf) >= 9:
        ltf_ema9 = EMAIndicator(df_ltf['Close'], window=9).ema_indicator()
        ltf_price = df_ltf['Close'].iloc[-1]
        ltf_vwap = calculate_vwap(df_ltf).iloc[-1]
        if ltf_price > ltf_ema9.iloc[-1] and ltf_price > ltf_vwap:
            result['ltf_bias'] = 'BULLISH'
            result['ltf_details'] = '5M: Price above EMA9 + VWAP'
        elif ltf_price < ltf_ema9.iloc[-1] and ltf_price < ltf_vwap:
            result['ltf_bias'] = 'BEARISH'
            result['ltf_details'] = '5M: Price below EMA9 + VWAP'
        else:
            result['ltf_details'] = '5M: Mixed signals'

    if result['htf_bias'] == 'BULLISH' and result['ltf_bias'] == 'BULLISH':
        result['mtf_aligned'] = True
        result['confidence_bonus'] = 15
        result['recommendation'] = 'BUY — Full MTF Alignment ✅'
    elif result['htf_bias'] == 'BEARISH' and result['ltf_bias'] == 'BEARISH':
        result['mtf_aligned'] = True
        result['confidence_bonus'] = 15
        result['recommendation'] = 'SELL — Full MTF Alignment ✅'
    elif result['htf_bias'] in ['BULLISH', 'BEARISH']:
        result['confidence_bonus'] = 7
        result['recommendation'] = f"{result['htf_bias']} (HTF aligned, wait for LTF)"
    else:
        result['confidence_bonus'] = -10
        result['recommendation'] = 'WAIT — MTF not aligned'

    return result


def detect_liquidity_sweep(df):
    """
    V2: Liquidity Sweep Detection
    Equal highs/lows within 0.1%, wick beyond, close back inside = liquidity grab.
    """
    if len(df) < 10:
        return {'detected': False, 'type': None, 'level': None, 'description': '', 'confidence_boost': 0}

    recent = df.tail(20)
    highs = recent['High'].values
    lows = recent['Low'].values
    closes = recent['Close'].values
    last_high = highs[-1]
    last_low = lows[-1]
    last_close = closes[-1]

    # Sweep above equal highs (bearish)
    for i in range(max(0, len(highs) - 6), len(highs) - 1):
        if abs(highs[i] - last_high) / max(last_high, 0.0001) < 0.001:
            prev_level = highs[i]
            if last_high > prev_level and last_close < prev_level:
                return {
                    'detected': True, 'type': 'BEARISH_SWEEP', 'level': round(prev_level, 2),
                    'description': f'Liquidity grab above equal highs ₹{prev_level:.2f} — Bearish reversal likely',
                    'confidence_boost': 12
                }

    # Sweep below equal lows (bullish)
    for i in range(max(0, len(lows) - 6), len(lows) - 1):
        if abs(lows[i] - last_low) / max(last_low, 0.0001) < 0.001:
            prev_level = lows[i]
            if last_low < prev_level and last_close > prev_level:
                return {
                    'detected': True, 'type': 'BULLISH_SWEEP', 'level': round(prev_level, 2),
                    'description': f'Liquidity grab below equal lows ₹{prev_level:.2f} — Bullish reversal likely',
                    'confidence_boost': 12
                }

    return {'detected': False, 'type': None, 'level': None, 'description': '', 'confidence_boost': 0}


def classify_volatility_regime(df, vix=15):
    """
    V2: Volatility Regime Classifier
    LOW / MEDIUM / HIGH — adjusts SL multiplier, position size, confidence weight.
    """
    if len(df) < 20:
        return {'regime': 'MEDIUM', 'sl_multiplier': 1.5, 'position_size_factor': 0.75,
                'confidence_weight': 1.0, 'atr_pct': 0, 'atr': 10,
                'description': 'Insufficient data — using medium defaults'}

    atr = AverageTrueRange(df['High'], df['Low'], df['Close'], window=14).average_true_range().iloc[-1]
    current_price = df['Close'].iloc[-1]
    atr_pct = (atr / current_price) * 100 if current_price > 0 else 1.5

    if atr_pct > 2.0 or vix > 20:
        return {'regime': 'HIGH', 'sl_multiplier': 2.0, 'position_size_factor': 0.5,
                'confidence_weight': 0.8, 'atr_pct': round(atr_pct, 2), 'atr': round(atr, 2),
                'description': f'HIGH VOLATILITY: ATR={atr_pct:.2f}%, VIX={vix:.1f} — Widen SL, Reduce Size'}
    elif atr_pct < 0.8 and vix < 13:
        return {'regime': 'LOW', 'sl_multiplier': 1.2, 'position_size_factor': 1.0,
                'confidence_weight': 1.1, 'atr_pct': round(atr_pct, 2), 'atr': round(atr, 2),
                'description': f'LOW VOLATILITY: ATR={atr_pct:.2f}%, VIX={vix:.1f} — Tight SL OK, Full Size'}
    else:
        return {'regime': 'MEDIUM', 'sl_multiplier': 1.5, 'position_size_factor': 0.75,
                'confidence_weight': 1.0, 'atr_pct': round(atr_pct, 2), 'atr': round(atr, 2),
                'description': f'MEDIUM VOLATILITY: ATR={atr_pct:.2f}%, VIX={vix:.1f} — Standard parameters'}


def calculate_position_size(entry, stop_loss, capital=100000, risk_pct=1.0, volatility_factor=0.75):
    """
    V2: Dynamic Position Sizing Engine
    risk_per_trade = 1% of capital
    position_size = risk / (entry - stop_loss)
    """
    if entry <= 0 or stop_loss <= 0 or entry == stop_loss:
        return {'shares': 0, 'capital_required': 0, 'risk_amount': 0,
                'risk_pct': 0, 'recommendation': 'Cannot calculate — invalid entry/SL'}

    risk_amount = capital * (risk_pct / 100) * volatility_factor
    risk_per_share = abs(entry - stop_loss)
    shares = max(1, int(risk_amount / risk_per_share))
    capital_required = round(shares * entry, 2)
    actual_risk = round(shares * risk_per_share, 2)
    actual_risk_pct = round((actual_risk / capital) * 100, 2)

    return {
        'shares': shares,
        'capital_required': capital_required,
        'risk_amount': actual_risk,
        'risk_pct': actual_risk_pct,
        'recommendation': f'Trade {shares} shares — Capital: ₹{capital_required:,.0f} | Risk: ₹{actual_risk:,.0f} ({actual_risk_pct}%)'
    }


def check_correlation_filter(signal_direction, nifty_bias):
    """
    V2: Correlation Filter
    If NIFTY opposite bias and correlation > 0.6, block trade entirely.
    """
    estimated_correlation = 0.65  # Conservative estimate for NSE stocks
    result = {'blocked': False, 'correlation': estimated_correlation, 'reason': '', 'penalty': 0}

    signal_bias = 'BULLISH' if signal_direction == 'BUY' else 'BEARISH' if signal_direction == 'SELL' else 'NEUTRAL'

    if signal_bias != 'NEUTRAL' and nifty_bias not in ['NEUTRAL', 'UNKNOWN']:
        if signal_bias != nifty_bias and estimated_correlation > 0.6:
            result['blocked'] = True
            result['reason'] = (f'Correlation block: {signal_direction} vs NIFTY {nifty_bias} '
                                f'(corr={estimated_correlation:.2f} > 0.6)')
            result['penalty'] = -20
        elif signal_bias == nifty_bias:
            result['reason'] = f'Correlation aligned with NIFTY {nifty_bias}'
            result['penalty'] = 5

    return result


def calculate_order_flow_proxy(df):
    """
    V2: Order Flow Proxy
    Volume delta proxy, bullish candle volume vs prev-3 average, bearish volume dominance.
    """
    if len(df) < 10:
        return {'flow': 'NEUTRAL', 'delta': 0, 'bullish_ratio': 0.5,
                'bearish_ratio': 0.5, 'score': 50, 'vol_surge': False,
                'description': 'Insufficient data'}

    recent = df.tail(10)
    body = recent['Close'] - recent['Open']
    total_range = (recent['High'] - recent['Low']).replace(0, 0.0001)
    delta_proxy = (body / total_range) * recent['Volume']
    net_delta = delta_proxy.sum()

    bull_vol = recent.loc[recent['Close'] > recent['Open'], 'Volume'].sum()
    bear_vol = recent.loc[recent['Close'] < recent['Open'], 'Volume'].sum()
    total_vol = bull_vol + bear_vol if (bull_vol + bear_vol) > 0 else 1
    bull_ratio = round(bull_vol / total_vol, 3)
    bear_ratio = round(bear_vol / total_vol, 3)

    curr_vol = df['Volume'].iloc[-1]
    prev3_avg = df['Volume'].iloc[-4:-1].mean()
    vol_surge = bool(curr_vol > prev3_avg * 1.3) if prev3_avg > 0 else False

    if net_delta > 0 and bull_ratio > 0.6:
        flow, score = 'BULLISH', min(100, 55 + int(bull_ratio * 40))
        desc = f'Bullish order flow ({bull_ratio*100:.0f}% bullish vol)'
    elif net_delta < 0 and bear_ratio > 0.6:
        flow, score = 'BEARISH', min(100, 55 + int(bear_ratio * 40))
        desc = f'Bearish order flow ({bear_ratio*100:.0f}% bearish vol)'
    else:
        flow, score = 'NEUTRAL', 50
        desc = f'Mixed flow (Bull:{bull_ratio*100:.0f}% / Bear:{bear_ratio*100:.0f}%)'

    if vol_surge:
        desc += ' + Volume surge'

    return {'flow': flow, 'delta': round(net_delta, 0), 'bullish_ratio': bull_ratio,
            'bearish_ratio': bear_ratio, 'score': score, 'vol_surge': vol_surge, 'description': desc}


def simulate_slippage(entry_price, signal_direction, session_name, vix, is_gap_day):
    """
    V2: Slippage Simulation
    Opening session / gap day / high VIX → add 0.1%–0.3% slippage buffer to entry.
    """
    slippage_pct = 0.05
    factors = []

    if session_name == "Opening":
        slippage_pct += 0.15
        factors.append("Opening session (+0.15%)")
    if is_gap_day:
        slippage_pct += 0.10
        factors.append("Gap day (+0.10%)")
    if vix > 20:
        slippage_pct += 0.10
        factors.append(f"High VIX {vix:.1f} (+0.10%)")

    slippage_pct = min(0.30, slippage_pct)

    if signal_direction == 'BUY':
        adjusted = round(entry_price * (1 + slippage_pct / 100), 2)
    elif signal_direction == 'SELL':
        adjusted = round(entry_price * (1 - slippage_pct / 100), 2)
    else:
        adjusted = entry_price

    return {
        'slippage_pct': round(slippage_pct, 3),
        'adjusted_entry': adjusted,
        'original_entry': entry_price,
        'slippage_amount': round(abs(adjusted - entry_price), 2),
        'factors': factors,
        'description': f'{slippage_pct:.2f}% slippage' + (f' ({", ".join(factors)})' if factors else '')
    }


def check_signal_stability(ticker, current_signal, current_time):
    """
    V2: Signal Stability Filter
    Signal must remain valid for 2 consecutive candles before confirmed entry.
    """
    if ticker not in st.session_state.signal_stability_buffer:
        st.session_state.signal_stability_buffer[ticker] = {
            'signal': None, 'count': 0, 'first_seen': None
        }

    buf = st.session_state.signal_stability_buffer[ticker]

    if current_signal in ['BUY', 'SELL']:
        if buf['signal'] == current_signal:
            buf['count'] += 1
            if buf['count'] >= 2:
                return True, buf['count'], f'Signal stable for {buf["count"]} candles ✅ Confirmed'
            else:
                return False, buf['count'], f'1st candle seen ({buf["count"]}/2) — Waiting for 2nd confirmation'
        else:
            buf['signal'] = current_signal
            buf['count'] = 1
            buf['first_seen'] = current_time
            return False, 1, 'New signal — Waiting for 2nd candle confirmation ⏳'
    else:
        buf['signal'] = None
        buf['count'] = 0
        buf['first_seen'] = None
        return False, 0, 'No active signal'


def generate_statistics_dashboard(ticker):
    """
    V2: Statistics Dashboard
    Win rate %, Avg R:R, Max drawdown, Session performance.
    """
    stats = {'win_rate': 0, 'total_trades': 0, 'wins': 0, 'losses': 0,
             'pending': 0, 'max_drawdown': 0, 'total_pnl_pct': 0}

    ticker_trades = []
    if st.session_state.trade_history:
        ticker_trades = [t for t in st.session_state.trade_history if t.get('ticker') == ticker]
    if not ticker_trades and ticker in st.session_state.ticker_memory:
        ticker_trades = st.session_state.ticker_memory[ticker].get('last_10_trades', [])

    if ticker_trades:
        wins = [t for t in ticker_trades if t.get('outcome') == 'TARGET_HIT']
        losses = [t for t in ticker_trades if t.get('outcome') == 'STOP_LOSS']
        pending = [t for t in ticker_trades if not t.get('outcome')]
        total = len(wins) + len(losses)
        stats.update({'wins': len(wins), 'losses': len(losses), 'pending': len(pending),
                      'total_trades': len(ticker_trades),
                      'win_rate': round((len(wins) / total * 100) if total > 0 else 0, 1)})

    g = st.session_state.trade_stats
    stats['total_pnl_pct'] = round(g.get('total_profit_pct', 0) - g.get('total_loss_pct', 0), 2)
    stats['max_drawdown'] = round(g.get('max_drawdown', 0), 2)
    return stats


def generate_ai_summary(ticker, signals, final_confidence, market_context,
                         primary_bias, vol_regime, mtf_bias, market_structure,
                         order_flow, liq_sweep, signal_stable):
    """
    V2: AI Summary Engine
    Human-readable summary with risk warning, bias alignment, volatility comment.
    """
    sig = signals.get('signal', 'WAIT')
    conf_text = "HIGH" if final_confidence >= 75 else "MEDIUM" if final_confidence >= 50 else "LOW"

    if sig in ['BUY', 'SELL'] and final_confidence >= 65 and signal_stable:
        action = f"✅ {sig} — Setup Confirmed & Stable"
        action_color = "#4CAF50" if sig == 'BUY' else "#f44336"
    elif sig in ['BUY', 'SELL'] and not signal_stable:
        action = f"⏳ {sig} Signal — Awaiting 2nd Candle Confirmation"
        action_color = "#FFC107"
    else:
        action = "🛑 WAIT — No Valid Setup"
        action_color = "#FF9800"

    risk_warnings = []
    if market_context.get('vix', 15) > 20:
        risk_warnings.append(f"⚠️ High VIX ({market_context['vix']:.1f}) — Elevated risk environment")
    if vol_regime.get('regime') == 'HIGH':
        risk_warnings.append("⚠️ ATR volatility is high — Reduce position size by 50%")
    if market_context.get('nifty_bias') == 'BEARISH' and sig == 'BUY':
        risk_warnings.append("⚠️ BUY signal against NIFTY bearish trend — Higher failure risk")
    if market_context.get('nifty_bias') == 'BULLISH' and sig == 'SELL':
        risk_warnings.append("⚠️ SELL signal against NIFTY bullish trend — Higher failure risk")
    if not signal_stable:
        risk_warnings.append("⚠️ Signal not stable yet — 2nd candle confirmation required")
    if not risk_warnings:
        risk_warnings.append("✅ No critical risk warnings — Standard risk management applies")

    s_bias = market_structure.get('structure_bias', 'NEUTRAL')
    bias_comments = []
    if primary_bias == s_bias:
        bias_comments.append(f"✅ Directional bias ({primary_bias}) aligns with market structure ({s_bias})")
    else:
        bias_comments.append(f"⚠️ Bias conflict: Directional={primary_bias} vs Structure={s_bias}")

    htf = mtf_bias.get('htf_bias', 'NEUTRAL')
    expected_htf = 'BULLISH' if sig == 'BUY' else 'BEARISH'
    if htf == expected_htf:
        bias_comments.append(f"✅ Higher TF (1H) aligned: {htf}")
    else:
        bias_comments.append(f"📊 Higher TF (1H): {htf} — Partial alignment")

    if liq_sweep.get('detected'):
        bias_comments.append(f"💧 {liq_sweep.get('description', '')}")

    bos = market_structure.get('bos')
    choch = market_structure.get('choch')
    if bos:
        structure_comment = f"🏛️ {bos['description']}"
    elif choch:
        structure_comment = f"🔄 {choch['description']}"
    else:
        structure_comment = f"📐 Structure bias: {s_bias} (no active BOS/CHOCH)"

    return {
        'action': action, 'action_color': action_color, 'confidence_text': conf_text,
        'risk_warnings': risk_warnings, 'bias_comments': bias_comments,
        'volatility_comment': vol_regime.get('description', ''),
        'flow_comment': order_flow.get('description', ''),
        'structure_comment': structure_comment,
        'summary': (f"**{ticker}** | Signal: **{sig}** | Confidence: **{final_confidence:.0f}/100 ({conf_text})**\n"
                    f"NIFTY: {market_context.get('nifty_bias', 'UNKNOWN')} | "
                    f"VIX: {market_context.get('vix', 15):.1f} | "
                    f"Regime: {vol_regime.get('regime', 'MEDIUM')} | "
                    f"Structure: {s_bias} | HTF: {htf}")
    }

# =============================================================================
# --- V2 UPGRADE END ---
# =============================================================================

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

        # --- V2 UPGRADE: LOOK-AHEAD BIAS FIX ---
        # If market is currently open, the last candle is incomplete — drop it
        if df is not None and not df.empty:
            _now_chk = datetime.now(IST)
            _mkt_open = (
                _now_chk.weekday() < 5 and
                _now_chk.time() >= datetime.strptime("09:15", "%H:%M").time() and
                _now_chk.time() <= datetime.strptime("15:30", "%H:%M").time()
            )
            if _mkt_open and len(df) > 1:
                df = df.iloc[:-1]  # Use only fully closed candles
        # --- V2 UPGRADE END ---

        if df is not None and not df.empty:
            # =============================================================================
            # INSTITUTIONAL LAYER 1: DATA VALIDATION (FAIL-SAFE)
            # =============================================================================
            is_valid, quality_score, validation_msg = validate_data_integrity(df, ticker)
            
            if not is_valid:
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
                # --- V2 UPGRADE: ADDITIONAL ANALYSIS ENGINES ---
                # =============================================================================

                # V2-1: Market Structure Engine (BOS/CHOCH)
                market_structure = detect_market_structure(df)

                # V2-2: Multi-Timeframe Confirmation
                df_htf, df_ltf = fetch_mtf_data(ticker)
                mtf_bias = get_mtf_bias(ticker, df_htf, df_ltf, interval)

                # V2-3: Liquidity Sweep Detection
                liq_sweep = detect_liquidity_sweep(df)

                # V2-4: Volatility Regime Classification
                vol_regime = classify_volatility_regime(df, market_context['vix'])

                # V2-5: Order Flow Proxy
                order_flow = calculate_order_flow_proxy(df)

                # V2-6: Slippage Simulation
                slippage = simulate_slippage(
                    signals['entry'], signals['signal'],
                    session_name, market_context['vix'], is_gap_day
                )

                # V2-7: Correlation Filter
                corr_filter = check_correlation_filter(signals['signal'], market_context['nifty_bias'])

                # V2-8: Signal Stability Check (2 candle confirmation)
                signal_stable, stability_count, stability_msg = check_signal_stability(
                    ticker, signals['signal'], current_ist_time
                )

                # V2-9: Dynamic Position Sizing
                pos_size = calculate_position_size(
                    entry=slippage['adjusted_entry'],
                    stop_loss=signals['stop_loss'],
                    capital=100000,
                    risk_pct=1.0,
                    volatility_factor=vol_regime['position_size_factor']
                )

                # =============================================================================
                # INSTITUTIONAL LAYER 6: INTELLIGENT CONFIDENCE ADJUSTMENT (V2 UPGRADED)
                # =============================================================================

                # Base confidence from V2 institutional weighting (with structure)
                confidence_score, confidence_level, confidence_color, score_reasons = calculate_confidence_score(
                    df, trend[0], signals, support, resistance, session_name, market_regime,
                    structure_score=market_structure.get('structure_score', 50)
                )
                
                # Adjust for market context and memory
                adjusted_confidence, context_adjustments = adjust_confidence_for_market_context(
                    confidence_score, ticker, signals['signal'], market_context
                )
                
                # Apply final confidence
                final_confidence = adjusted_confidence
                all_reasons = score_reasons + context_adjustments

                # --- V2 UPGRADE: Additional confidence adjustments ---
                # MTF alignment bonus
                mtf_bonus = mtf_bias.get('confidence_bonus', 0)
                final_confidence = max(0, min(100, final_confidence + mtf_bonus))
                if mtf_bonus > 0:
                    all_reasons.append(f"✅ MTF aligned (1H+5M) confidence bonus (+{mtf_bonus})")
                elif mtf_bonus < 0:
                    all_reasons.append(f"⚠️ MTF not aligned confidence penalty ({mtf_bonus})")

                # Correlation filter adjustment
                if not corr_filter['blocked']:
                    corr_pen = corr_filter.get('penalty', 0)
                    final_confidence = max(0, min(100, final_confidence + corr_pen))
                    if corr_pen > 0:
                        all_reasons.append(f"✅ {corr_filter['reason']} (+{corr_pen})")

                # Liquidity sweep boost
                if liq_sweep.get('detected'):
                    liq_boost = liq_sweep.get('confidence_boost', 0)
                    final_confidence = max(0, min(100, final_confidence + liq_boost))
                    all_reasons.append(f"💧 Liquidity sweep detected (+{liq_boost})")

                # Volatility regime weight
                final_confidence = int(final_confidence * vol_regime.get('confidence_weight', 1.0))
                final_confidence = max(0, min(100, final_confidence))
                # --- V2 UPGRADE END ---

                # V2-10: AI Summary
                ai_summary = generate_ai_summary(
                    ticker, signals, final_confidence, market_context,
                    primary_bias, vol_regime, mtf_bias, market_structure,
                    order_flow, liq_sweep, signal_stable
                )

                # V2-11: Statistics Dashboard
                stats_dash = generate_statistics_dashboard(ticker)

                # =============================================================================
                # 💾 MONGODB: Save complete analysis to database
                # =============================================================================
                # Calculate VWAP early so it's available for DB save
                vwap_current = calculate_vwap(df).iloc[-1]

                if db_client.connected:
                    rsi_current_val = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
                    analysis_data = {
                        'current_price': float(current_price),
                        'trend': trend[0],
                        'signal': signals.get('signal', 'WAIT'),
                        'signal_reason': signals.get('reason', ''),
                        'entry_price': float(signals.get('entry', 0)),
                        'stop_loss': float(signals.get('stop_loss', 0)),
                        'target1': float(signals.get('target1', 0)),
                        'target2': float(signals.get('target2', 0)),
                        'target3': float(signals.get('target3', 0)),
                        'risk_reward': float(signals.get('risk_reward', 0)),
                        'confidence_score': float(final_confidence),
                        'confidence_level': confidence_level if final_confidence >= 75 else ('MEDIUM' if final_confidence >= 50 else 'LOW'),
                        'strategy_tag': signals.get('strategy_tag', ''),
                        'rsi': float(rsi_current_val),
                        'vwap': float(vwap_current),
                        'support': float(support),
                        'resistance': float(resistance),
                        'market_regime': market_regime,
                        'session_name': session_name,
                        'primary_bias': primary_bias,
                        'bias_strength': float(bias_strength),
                        'structure_bias': market_structure.get('structure_bias', ''),
                        'structure_score': int(market_structure.get('structure_score', 0)),
                        'bos_type': market_structure.get('bos', {}).get('type', '') if market_structure.get('bos') else '',
                        'choch_type': market_structure.get('choch', {}).get('type', '') if market_structure.get('choch') else '',
                        'htf_bias': mtf_bias.get('htf_bias', ''),
                        'ltf_bias': mtf_bias.get('ltf_bias', ''),
                        'mtf_aligned': mtf_bias.get('mtf_aligned', False),
                        'volatility_regime': vol_regime.get('regime', ''),
                        'order_flow': order_flow.get('flow', ''),
                        'liquidity_sweep': liq_sweep.get('detected', False),
                        'signal_stable': signal_stable,
                        'position_size': pos_size.get('shares', 0),
                        'slippage_pct': float(slippage.get('slippage_pct', 0)),
                        'nifty_bias': market_context.get('nifty_bias', ''),
                        'vix': float(market_context.get('vix', 15)),
                        'volume_quality': volume_quality,
                        'volume_ratio': float(volume_ratio) if volume_quality != 'INDEX_NO_VOLUME' else 0,
                    }
                    db_client.save_analysis_result(ticker, analysis_data, username=st.session_state.get('username', 'unknown'))
                    db_client.save_signal_log(ticker, {
                        'signal': signals.get('signal', 'WAIT'),
                        'entry': float(signals.get('entry', 0)),
                        'stop_loss': float(signals.get('stop_loss', 0)),
                        'target1': float(signals.get('target1', 0)),
                        'target2': float(signals.get('target2', 0)),
                        'target3': float(signals.get('target3', 0)),
                        'risk_reward': float(signals.get('risk_reward', 0)),
                        'strategy_tag': signals.get('strategy_tag', ''),
                        'confidence': float(final_confidence),
                        'reason': signals.get('reason', ''),
                    }, username=st.session_state.get('username', 'unknown'))
                    db_client.log_search(st.session_state.get('username', 'unknown'), ticker, {
                        'signal': signals.get('signal', 'WAIT'),
                        'confidence': float(final_confidence),
                        'trend': trend[0],
                    })
                    # Save daily stats
                    db_client.save_daily_stats({
                        'total_trades': stats_dash.get('total_trades', 0),
                        'wins': stats_dash.get('wins', 0),
                        'losses': stats_dash.get('losses', 0),
                        'win_rate': stats_dash.get('win_rate', 0),
                        'total_pnl_pct': stats_dash.get('total_pnl_pct', 0),
                        'max_drawdown': stats_dash.get('max_drawdown', 0),
                        'consecutive_losses': st.session_state.consecutive_losses,
                    })

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

                # --- V2 UPGRADE: DRAWDOWN PROTECTION ALERT (3 losses) ---
                if st.session_state.consecutive_losses >= 3:
                    st.error("""
                    ### 🛑 V2 DRAWDOWN PROTECTION ACTIVE
                    **3 Consecutive Losses — ALL Trading Blocked for Today**

                    This is an institutional-grade drawdown protection.
                    Your account needs to be protected before losses compound.
                    Resume tomorrow with fresh mindset.
                    """)
                    st.stop()
                # --- V2 UPGRADE END ---
                
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

                # =============================================================================
                # --- V2 UPGRADE: INSTITUTIONAL ANALYSIS PANELS ---
                # =============================================================================

                # V2 Panel 1: Market Structure (BOS/CHOCH)
                st.markdown("### 🏛️ V2: Market Structure Engine (BOS/CHOCH)")
                col_ms1, col_ms2, col_ms3, col_ms4 = st.columns(4)
                with col_ms1:
                    sb_col = "🟢" if market_structure['structure_bias'] == 'BULLISH' else "🔴" if market_structure['structure_bias'] == 'BEARISH' else "🟡"
                    st.metric("Structure Bias", f"{sb_col} {market_structure['structure_bias']}",
                             f"{market_structure['structure_score']}/100")
                with col_ms2:
                    bos = market_structure.get('bos')
                    st.metric("Break of Structure", f"{'✅ ' + bos['type'] if bos else '❌ None'}",
                             f"₹{bos['level']:,.2f}" if bos else "─")
                with col_ms3:
                    choch = market_structure.get('choch')
                    st.metric("Change of Character", f"{'🔄 ' + choch['type'] if choch else '─'}",
                             f"₹{choch['level']:,.2f}" if choch else "No CHOCH")
                with col_ms4:
                    st.metric("Swing Points",
                             f"{len(market_structure['swing_highs'])}H / {len(market_structure['swing_lows'])}L",
                             "Detected")
                if bos:
                    st.info(f"🏛️ **BOS:** {bos['description']}")
                if choch:
                    st.warning(f"🔄 **CHOCH:** {choch['description']}")

                st.markdown("---")

                # V2 Panel 2: Multi-Timeframe Confirmation
                st.markdown("### 📈 V2: Multi-Timeframe Confirmation (HTF=1H | LTF=5M)")
                col_mtf1, col_mtf2, col_mtf3, col_mtf4 = st.columns(4)
                htf_col = "🟢" if mtf_bias['htf_bias'] == 'BULLISH' else "🔴" if mtf_bias['htf_bias'] == 'BEARISH' else "🟡"
                ltf_col = "🟢" if mtf_bias['ltf_bias'] == 'BULLISH' else "🔴" if mtf_bias['ltf_bias'] == 'BEARISH' else "🟡"
                with col_mtf1:
                    st.metric("1H Bias (HTF)", f"{htf_col} {mtf_bias['htf_bias']}", mtf_bias['htf_details'])
                with col_mtf2:
                    st.metric("5M Bias (LTF)", f"{ltf_col} {mtf_bias['ltf_bias']}", mtf_bias['ltf_details'])
                with col_mtf3:
                    aligned_val = "✅ Aligned" if mtf_bias['mtf_aligned'] else "❌ Not Aligned"
                    st.metric("MTF Alignment", aligned_val, f"+{mtf_bias['confidence_bonus']} confidence")
                with col_mtf4:
                    st.metric("MTF Recommendation", mtf_bias['recommendation'][:20] + "..."
                             if len(mtf_bias['recommendation']) > 20 else mtf_bias['recommendation'])

                st.markdown("---")

                # V2 Panel 3: Liquidity Sweep + Volatility Regime + Order Flow
                st.markdown("### 📊 V2: Advanced Market Analytics")
                col_v1, col_v2, col_v3 = st.columns(3)

                with col_v1:
                    st.markdown("**💧 Liquidity Sweep**")
                    if liq_sweep['detected']:
                        sweep_col = "🔴" if liq_sweep['type'] == 'BEARISH_SWEEP' else "🟢"
                        st.success(f"{sweep_col} **DETECTED: {liq_sweep['type']}**")
                        st.caption(liq_sweep['description'])
                        st.caption(f"Confidence boost: +{liq_sweep['confidence_boost']}")
                    else:
                        st.info("— No liquidity sweep detected")

                with col_v2:
                    st.markdown("**🌡️ Volatility Regime**")
                    v_color = "🔴" if vol_regime['regime'] == 'HIGH' else "🟢" if vol_regime['regime'] == 'LOW' else "🟡"
                    st.markdown(f"{v_color} **{vol_regime['regime']}**")
                    st.caption(vol_regime['description'])
                    st.caption(f"SL Multiplier: {vol_regime['sl_multiplier']}x | Size Factor: {vol_regime['position_size_factor']}")

                with col_v3:
                    st.markdown("**📆 Order Flow Proxy**")
                    of_col = "🟢" if order_flow['flow'] == 'BULLISH' else "🔴" if order_flow['flow'] == 'BEARISH' else "🟡"
                    st.markdown(f"{of_col} **{order_flow['flow']}** (Score: {order_flow['score']}/100)")
                    st.caption(order_flow['description'])
                    if order_flow['vol_surge']:
                        st.caption("🔥 Volume surge vs prev 3 candles!")

                st.markdown("---")

                # V2 Panel 4: Signal Stability + Slippage + Position Sizing
                st.markdown("### 🛡️ V2: Signal Stability | Position Sizing | Slippage")
                col_p1, col_p2, col_p3 = st.columns(3)

                with col_p1:
                    st.markdown("**⏳ Signal Stability Filter**")
                    if signal_stable:
                        st.success(f"✅ {stability_msg}")
                    else:
                        st.warning(f"⚠️ {stability_msg}")
                    st.caption(f"Count: {stability_count}/2 candles required")

                with col_p2:
                    st.markdown("**💰 Dynamic Position Sizing**")
                    if pos_size['shares'] > 0:
                        st.metric("Recommended Shares", pos_size['shares'],
                                  f"Risk: ₹{pos_size['risk_amount']:,.0f} ({pos_size['risk_pct']}%)")
                        st.caption(f"Capital Required: ₹{pos_size['capital_required']:,.0f}")
                        st.caption("Based on 1% capital risk rule")
                    else:
                        st.info("Cannot calculate — check entry/SL")

                with col_p3:
                    st.markdown("**📉 Slippage Simulation**")
                    slip_color = "🔴" if slippage['slippage_pct'] >= 0.2 else "🟡" if slippage['slippage_pct'] >= 0.1 else "🟢"
                    st.metric("Adjusted Entry", f"₹{slippage['adjusted_entry']:.2f}",
                              f"{slip_color} +{slippage['slippage_pct']:.2f}% slippage")
                    if slippage['factors']:
                        st.caption(f"Factors: {', '.join(slippage['factors'])}")
                    else:
                        st.caption("Normal conditions — minimal slippage")

                st.markdown("---")

                # V2 Panel 5: Correlation Filter Alert
                if corr_filter['blocked']:
                    st.error(f"""
                    ### 🚫 V2: CORRELATION FILTER — TRADE BLOCKED

                    {corr_filter['reason']}

                    **Rule:** NSE stocks correlation with NIFTY ≈ {corr_filter['correlation']:.2f}
                    Trading against index with high correlation = very high failure rate.
                    Wait for NIFTY to align or trade a different direction.
                    """)
                # =============================================================================
                # --- V2 UPGRADE END ---
                # =============================================================================
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
                
                # Determine if signal should be blocked based on institutional checks (V2 updated)
                signal_blocked = (is_cooldown or limit_reached or is_consolidating or
                                is_exhausted or final_confidence < 60 or is_no_trade_zone or
                                (in_trap_zone and final_confidence < 85) or
                                (volume_quality == "ISOLATED_SPIKE_TRAP") or
                                corr_filter['blocked'] or          # V2: correlation filter
                                not signal_stable)                 # V2: signal stability (2-candle confirmation)
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
                    # 💾 Save BUY trade to MongoDB
                    if db_client.connected:
                        db_client.save_trade({
                            'ticker': ticker,
                            'signal': 'BUY',
                            'entry': float(signals['entry']),
                            'stop_loss': float(signals['stop_loss']),
                            'target1': float(signals['target1']),
                            'target2': float(signals['target2']),
                            'target3': float(signals['target3']),
                            'risk_reward': float(signals['risk_reward']),
                            'confidence': float(final_confidence),
                            'strategy_tag': signals.get('strategy_tag', ''),
                            'session': session_name,
                            'nifty_bias': market_context.get('nifty_bias', ''),
                            'vix': float(market_context.get('vix', 15)),
                            'volume_quality': volume_quality,
                            'primary_bias': primary_bias,
                            'outcome': None,
                        }, username=st.session_state.get('username', 'unknown'))
                        db_client.update_ticker_memory(ticker, st.session_state.ticker_memory.get(ticker, {}))
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
                    # 💾 Save SELL trade to MongoDB
                    if db_client.connected:
                        db_client.save_trade({
                            'ticker': ticker,
                            'signal': 'SELL',
                            'entry': float(signals['entry']),
                            'stop_loss': float(signals['stop_loss']),
                            'target1': float(signals['target1']),
                            'target2': float(signals['target2']),
                            'target3': float(signals['target3']),
                            'risk_reward': float(signals['risk_reward']),
                            'confidence': float(final_confidence),
                            'strategy_tag': signals.get('strategy_tag', ''),
                            'session': session_name,
                            'nifty_bias': market_context.get('nifty_bias', ''),
                            'vix': float(market_context.get('vix', 15)),
                            'volume_quality': volume_quality,
                            'primary_bias': primary_bias,
                            'outcome': None,
                        }, username=st.session_state.get('username', 'unknown'))
                        db_client.update_ticker_memory(ticker, st.session_state.ticker_memory.get(ticker, {}))
                
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
                    # --- V2 UPGRADE: Additional block reasons ---
                    if corr_filter['blocked']:
                        wait_reasons.append(f"🚫 {corr_filter['reason']}")
                    if not signal_stable and signals['signal'] in ['BUY', 'SELL']:
                        wait_reasons.append(f"⏳ {stability_msg}")
                    if vol_regime['regime'] == 'HIGH':
                        wait_reasons.append(f"⚠️ High volatility regime — use caution")
                    # --- V2 UPGRADE END ---
                    
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

                # =============================================================================
                # --- V2 UPGRADE: AI SUMMARY ENGINE & STATISTICS DASHBOARD ---
                # =============================================================================

                st.markdown("---")
                st.markdown("### 🤖 V2: AI Summary Engine")
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, rgba(30,33,48,0.9), rgba(20,23,38,0.95));
                            padding: 20px; border-radius: 12px;
                            border-left: 4px solid {ai_summary['action_color']}; margin-bottom: 10px;">
                    <h3 style="color: {ai_summary['action_color']}; margin: 0 0 10px 0;">{ai_summary['action']}</h3>
                    <p style="margin: 5px 0; color: #ccc;">{ai_summary['summary']}</p>
                </div>
                """, unsafe_allow_html=True)

                col_ai1, col_ai2 = st.columns(2)
                with col_ai1:
                    st.markdown("**🛑 Risk Warnings:**")
                    for w in ai_summary['risk_warnings']:
                        if "✅" in w:
                            st.success(w)
                        else:
                            st.warning(w)
                    st.markdown("**🏛️ Market Structure:**")
                    st.info(ai_summary['structure_comment'])

                with col_ai2:
                    st.markdown("**📌 Bias Alignment:**")
                    for c in ai_summary['bias_comments']:
                        if "✅" in c:
                            st.success(c)
                        else:
                            st.warning(c)
                    st.markdown("**🌡️ Volatility:**")
                    st.info(ai_summary['volatility_comment'])
                    st.markdown("**📆 Order Flow:**")
                    st.info(ai_summary['flow_comment'])

                st.markdown("---")

                # V2: Statistics Dashboard
                st.markdown("### 📊 V2: Statistics Dashboard")
                col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
                with col_s1:
                    st.metric("Win Rate", f"{stats_dash['win_rate']}%",
                             f"{stats_dash['wins']}W / {stats_dash['losses']}L")
                with col_s2:
                    st.metric("Total Trades", stats_dash['total_trades'],
                             f"{stats_dash['pending']} pending")
                with col_s3:
                    pnl_color = "🟢" if stats_dash['total_pnl_pct'] >= 0 else "🔴"
                    st.metric("Total P&L", f"{pnl_color} {stats_dash['total_pnl_pct']:+.2f}%")
                with col_s4:
                    st.metric("Max Drawdown", f"{stats_dash['max_drawdown']:.2f}%",
                             "🟢 Healthy" if stats_dash['max_drawdown'] < 3 else "🔴 Watch")
                with col_s5:
                    cons_losses = st.session_state.consecutive_losses
                    st.metric("Consecutive Losses", cons_losses,
                             "🟢 Clear" if cons_losses == 0 else "⚠️ Caution" if cons_losses < 3 else "🛑 BLOCKED")

                # =============================================================================
                # --- V2 UPGRADE END ---
                # =============================================================================

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

elif not ticker:
    st.info("👆 Enter a stock ticker to begin institutional-grade analysis")
    
    st.markdown("---")
    st.markdown("### 🏛️ Institutional-Grade Trading Engine Features")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **🧠 Intelligence Layers (V1 + V2):**
        - Market context (NIFTY, VIX) integration
        - Directional bias engine (prevents flip-flop)
        - 🆕 Market Structure Engine (BOS/CHOCH)
        - 🆕 Multi-Timeframe Confirmation (1H/5M)
        - 🆕 Liquidity Sweep Detection
        - Historical memory & trap zone detection
        
        **🛡️ Safety & Discipline (V1 + V2):**
        - Trade cooldown enforcement (30 min after SL)
        - Daily limits (10 total, 3 per ticker)
        - 🆕 Drawdown Protection (3 losses = full day block)
        - 🆕 Signal Stability Filter (2-candle confirmation)
        - 🆕 Correlation Filter (blocks counter-trend trades)
        - Consolidation lock (prevents whipsaw)
        
        **🕐 Time & Session Awareness:**
        - IST timezone conversion
        - 🆕 Look-Ahead Bias Fix (incomplete candle dropped)
        - 🆕 True Intraday VWAP (daily reset at 9:15)
        - Target time window calculation
        - Gap day detection
        """)
    
    with col2:
        st.markdown("""
        **📊 Technical Analysis (V1 + V2):**
        - Multi-EMA trend detection
        - 🆕 Institutional VWAP (true daily reset)
        - RSI & MACD confirmation
        - Support/Resistance (quantile-based)
        - Candlestick pattern recognition
        
        **🎯 Risk Management (V1 + V2):**
        - ATR-based stop-loss with buffer
        - Risk:Reward enforcement (min 1.5:1)
        - 🆕 Dynamic Position Sizing (1% risk rule)
        - 🆕 Slippage Simulation (session/VIX/gap)
        - 🆕 Volatility Regime Classifier (LOW/MED/HIGH)
        - 🆕 Order Flow Proxy (volume delta)
        
        **📈 Analytics (V2 New):**
        - 🆕 Institutional Confidence Weighting (T30/V20/VWAP15/CTX15/STR20)
        - 🆕 AI Summary Engine
        - 🆕 Statistics Dashboard (win rate, drawdown)
        - 🆕 Multi-Timeframe Bias (HTF+LTF alignment)
        """)
