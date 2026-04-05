import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings('ignore')
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mongo_db import db_client
from app import check_auth, show_sidebar_user_info, inject_login_css

# Page configuration
# Page config is set in Home.py

# ── Authentication Gate ──
if not check_auth():
    st.stop()

inject_login_css()
show_sidebar_user_info()

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        text-align: center;
        color: var(--text-color);
        opacity: 0.7;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: rgba(128, 128, 128, 0.1);
        padding: 1.5rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .metric-card h4 {
        margin: 0 0 0.5rem 0;
        color: var(--text-color);
        opacity: 0.8;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-card p {
        margin: 0;
        font-size: 1.8rem;
        font-weight: bold;
        color: var(--text-color);
    }
    .bullish { color: #00c853; font-weight: bold; }
    .bearish { color: #ff1744; font-weight: bold; }
    .neutral { color: #ffa726; font-weight: bold; }
    .info-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

class IntradayAnalyzer:
    def __init__(self):
        self.stock_universe = []  # Will be populated dynamically
        self.indices = ['^NSEI', '^NSEBANK']  # NIFTY 50 and BANK NIFTY
    
    def fetch_nse_stocks(self):
        """Fetch all NSE stocks from multiple sources"""
        try:
            st.info("🔄 Fetching live stock list from NSE...")
            
            # Method 1: Fetch NIFTY 500 constituents (most liquid stocks)
            stocks = []
            
            # Get NIFTY 50 stocks
            nifty50_url = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
            try:
                df_nifty50 = pd.read_csv(nifty50_url)
                stocks.extend([symbol + '.NS' for symbol in df_nifty50['Symbol'].tolist()])
            except:
                pass
            
            # Get NIFTY Next 50
            niftynext50_url = "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv"
            try:
                df_next50 = pd.read_csv(niftynext50_url)
                stocks.extend([symbol + '.NS' for symbol in df_next50['Symbol'].tolist()])
            except:
                pass
            
            # Get NIFTY 100
            nifty100_url = "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
            try:
                df_nifty100 = pd.read_csv(nifty100_url)
                stocks.extend([symbol + '.NS' for symbol in df_nifty100['Symbol'].tolist()])
            except:
                pass
            
            # Get NIFTY 200
            nifty200_url = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
            try:
                df_nifty200 = pd.read_csv(nifty200_url)
                stocks.extend([symbol + '.NS' for symbol in df_nifty200['Symbol'].tolist()])
            except:
                pass
            
            # Get NIFTY 500
            nifty500_url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
            try:
                df_nifty500 = pd.read_csv(nifty500_url)
                stocks.extend([symbol + '.NS' for symbol in df_nifty500['Symbol'].tolist()])
            except:
                pass
            
            # Get NIFTY Midcap 150
            midcap_url = "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
            try:
                df_midcap = pd.read_csv(midcap_url)
                stocks.extend([symbol + '.NS' for symbol in df_midcap['Symbol'].tolist()])
            except:
                pass
            
            # Get NIFTY Smallcap 250
            smallcap_url = "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"
            try:
                df_smallcap = pd.read_csv(smallcap_url)
                stocks.extend([symbol + '.NS' for symbol in df_smallcap['Symbol'].tolist()])
            except:
                pass
            
            # Remove duplicates
            stocks = list(set(stocks))
            
            if len(stocks) > 0:
                st.success(f"✅ Fetched {len(stocks)} stocks from NSE indices")
                return stocks
            else:
                # Fallback to comprehensive list
                st.warning("⚠️ Using fallback comprehensive stock list")
                return self.get_fallback_stock_list()
                
        except Exception as e:
            st.warning(f"⚠️ Using fallback stock list: {str(e)}")
            return self.get_fallback_stock_list()
    
    def get_fallback_stock_list(self):
        """Comprehensive fallback list of liquid NSE stocks"""
        return [
            'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS', 'HINDUNILVR.NS', 'ITC.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'KOTAKBANK.NS',
            'LT.NS', 'AXISBANK.NS', 'ASIANPAINT.NS', 'MARUTI.NS', 'TITAN.NS', 'SUNPHARMA.NS', 'ULTRACEMCO.NS', 'BAJFINANCE.NS', 'NESTLEIND.NS', 'WIPRO.NS',
            'HCLTECH.NS', 'TATAMOTORS.NS', 'TATASTEEL.NS', 'POWERGRID.NS', 'NTPC.NS', 'ONGC.NS', 'M&M.NS', 'TECHM.NS', 'ADANIPORTS.NS', 'COALINDIA.NS',
            'BAJAJFINSV.NS', 'DIVISLAB.NS', 'DRREDDY.NS', 'INDUSINDBK.NS', 'JSWSTEEL.NS', 'GRASIM.NS', 'CIPLA.NS', 'EICHERMOT.NS', 'HEROMOTOCO.NS', 'BRITANNIA.NS',
            'BPCL.NS', 'HINDALCO.NS', 'TATACONSUM.NS', 'ADANIENT.NS', 'ADANIGREEN.NS', 'BAJAJ-AUTO.NS', 'TRENT.NS', 'HAL.NS', 'BEL.NS', 'SIEMENS.NS',

            'ABB.NS', 'AUROPHARMA.NS', 'BALKRISIND.NS', 'BATAINDIA.NS', 'BERGEPAINT.NS', 'BIOCON.NS', 'CANBK.NS', 'CHOLAFIN.NS', 'COFORGE.NS', 'CONCOR.NS',
            'CUMMINSIND.NS', 'ESCORTS.NS', 'FEDERALBNK.NS', 'FORTIS.NS', 'GODREJCP.NS', 'GODREJPROP.NS', 'GUJGASLTD.NS', 'HAVELLS.NS', 'IDFCFIRSTB.NS', 'INDHOTEL.NS',
            'INDIAMART.NS', 'IRCTC.NS', 'JINDALSTEL.NS', 'JUBLFOOD.NS', 'LICHSGFIN.NS', 'LUPIN.NS', 'M&MFIN.NS', 'MANAPPURAM.NS', 'MAXHEALTH.NS', 'METROPOLIS.NS',
            'MPHASIS.NS', 'MRF.NS', 'MUTHOOTFIN.NS', 'NATIONALUM.NS', 'NAVINFLUOR.NS', 'OBEROIRLTY.NS', 'PAGEIND.NS', 'PEL.NS', 'PERSISTENT.NS', 'PETRONET.NS',
            'PIIND.NS', 'POLYCAB.NS', 'PFC.NS', 'RECLTD.NS', 'SAIL.NS', 'SRF.NS', 'SHREECEM.NS', 'SYNGENE.NS', 'TATACHEM.NS', 'TATACOMM.NS',
            'TATAELXSI.NS', 'TATAPOWER.NS', 'TVSMOTOR.NS', 'UBL.NS', 'UNIONBANK.NS', 'VOLTAS.NS', 'ZEEL.NS', 'ZOMATO.NS', 'NYKAA.NS', 'PAYTM.NS',

            'AARTIIND.NS', 'ABFRL.NS', 'ADANIPOWER.NS', 'ALOKINDS.NS', 'AMBUJACEM.NS', 'APOLLOTYRE.NS', 'ASHOKLEY.NS', 'ASTRAL.NS', 'ATUL.NS', 'BANDHANBNK.NS',
            'BANKBARODA.NS', 'BHEL.NS', 'BSOFT.NS', 'CANFINHOME.NS', 'CESC.NS', 'CHAMBLFERT.NS', 'COROMANDEL.NS', 'DEEPAKNTR.NS', 'DELTACORP.NS', 'DIXON.NS',
            'EXIDEIND.NS', 'GLENMARK.NS', 'GMRINFRA.NS', 'GNFC.NS', 'GRANULES.NS', 'GSPL.NS', 'HDFCLIFE.NS', 'HINDPETRO.NS', 'IBULHSGFIN.NS', 'IDBI.NS',
            'IDEA.NS', 'IEX.NS', 'IGL.NS', 'INDIACEM.NS', 'INDIGO.NS', 'INDUSTOWER.NS', 'IPCALAB.NS', 'JBMA.NS', 'JKCEMENT.NS', 'KPRMILL.NS',
            'L&TFH.NS', 'LAURUSLABS.NS', 'LTTS.NS', 'MAHABANK.NS', 'MAHINDCIE.NS', 'MASTEK.NS', 'MCX.NS', 'METROBRAND.NS', 'MGL.NS', 'MOTILALOFS.NS',
            'MRPL.NS', 'NATCOPHARM.NS', 'NBCC.NS', 'NHPC.NS', 'NLCINDIA.NS', 'NMDC.NS', 'OIL.NS', 'OFSS.NS', 'PAGEIND.NS', 'PATANJALI.NS',
            'PHOENIXLTD.NS', 'POONAWALLA.NS', 'PRESTIGE.NS', 'PVRINOX.NS', 'RADICO.NS', 'RVNL.NS', 'RAIN.NS', 'RAJESHEXPO.NS', 'RAMCOCEM.NS', 'RAYMOND.NS',
            'RELAXO.NS', 'RITES.NS', 'ROLEXRINGS.NS', 'SJVN.NS', 'SKFINDIA.NS', 'SONACOMS.NS', 'SOUTHBANK.NS', 'STARHEALTH.NS', 'SULA.NS', 'SUNTECK.NS',
            'SUPREMEIND.NS', 'SUZLON.NS', 'TATAINVEST.NS', 'TATAMTRDVR.NS', 'TEJASNET.NS', 'TIINDIA.NS', 'TIMKEN.NS', 'TRIDENT.NS', 'TRITURBINE.NS', 'UCOBANK.NS',
            'UNOMINDA.NS', 'USHAMART.NS', 'VGUARD.NS', 'VIPIND.NS', 'VTL.NS', 'WELCORP.NS', 'WESTLIFE.NS', 'WHIRLPOOL.NS', 'ZENSARTECH.NS',

            '3MINDIA.NS', 'AAVAS.NS', 'ABBOTINDIA.NS', 'ACE.NS', 'ADANITRANS.NS', 'AEGISCHEM.NS', 'AFFLE.NS', 'AJANTPHARM.NS', 'AKZOINDIA.NS', 'ALEMBICLTD.NS',
            'ALKEM.NS', 'ALKYLAMINE.NS', 'AMARAJABAT.NS', 'ANANTRAJ.NS', 'APLLTD.NS', 'APLAPOLLO.NS', 'APOLLOHOSP.NS', 'APOLLOPIPE.NS', 'APTUS.NS', 'ASAHIINDIA.NS',
            'ASTERDM.NS', 'ASTEC.NS', 'ATGL.NS', 'ATULAUTO.NS', 'AVANTIFEED.NS', 'AXITA.NS', 'BALAMINES.NS', 'BALRAMCHIN.NS', 'BANCOINDIA.NS', 'BASF.NS',
            'BAYERCROP.NS', 'BBTC.NS', 'BDL.NS', 'BEPL.NS', 'BHAGERIA.NS', 'BHARATRAS.NS', 'BIRLACORPN.NS', 'BLISSGVS.NS', 'BLUEDART.NS', 'BLUESTARCO.NS',
            'BORORENEW.NS', 'BOSCHLTD.NS', 'BRIGADE.NS', 'CAPLIPOINT.NS', 'CARBORUNIV.NS', 'CASTROLIND.NS', 'CCL.NS', 'CEATLTD.NS', 'CENTURYPLY.NS', 'CENTURYTEX.NS',
            'CERA.NS', 'CGCL.NS', 'CHALET.NS', 'CHEMPLASTS.NS', 'CHENNPETRO.NS', 'CHOLAHLDNG.NS', 'CLEAN.NS', 'CMI.NS', 'CMSINFO.NS', 'COCHINSHIP.NS',
            'COOLCAPS.NS', 'CREDITACC.NS', 'CRISIL.NS', 'CROMPTON.NS', 'CSBBANK.NS', 'CYIENT.NS', 'DCBBANK.NS', 'DCMSHRIRAM.NS', 'DECCANCE.NS', 'DEEPAKFERT.NS',
            'DHANI.NS', 'DISHTV.NS', 'DOLLAR.NS', 'DPSCLTD.NS', 'DREDGECORP.NS', 'ECLERX.NS', 'EDELWEISS.NS', 'EIDPARRY.NS', 'EIHOTEL.NS', 'ELGIEQUIP.NS',
            'EMAMILTD.NS', 'ENDURANCE.NS', 'ENGINERSIN.NS', 'EPL.NS', 'ERIS.NS', 'ESABINDIA.NS', 'EVEREADY.NS', 'EXPLEOSOL.NS', 'FCONSUMER.NS', 'FIEMIND.NS',
            'FINCABLES.NS', 'FINEORG.NS', 'FINPIPE.NS', 'FLUOROCHEM.NS', 'FSL.NS', 'GABRIEL.NS', 'GAIL.NS', 'GALAXYSURF.NS', 'GARFIBRES.NS', 'GATEWAY.NS',
            'GEPIL.NS', 'GHCL.NS', 'GICRE.NS', 'GILLETTE.NS', 'GLAXO.NS', 'GLS.NS', 'GNA.NS', 'GOCOLORS.NS', 'GODFRYPHLP.NS', 'GOODYEAR.NS',
            'GPIL.NS', 'GRAPHITE.NS', 'GREENLAM.NS', 'GRINDWELL.NS', 'GUFICBIO.NS', 'GULFOILLUB.NS', 'HAPPSTMNDS.NS', 'HATSUN.NS', 'HEG.NS', 'HEIDELBERG.NS',
            'HEMIPROP.NS', 'HFCL.NS', 'HIKAL.NS', 'HIMATSEIDE.NS', 'HONAUT.NS', 'HSCL.NS', 'HUDCO.NS', 'ICIL.NS', 'ICRA.NS', 'IDFC.NS',
            'IIFL.NS', 'IIFLWAM.NS', 'IOLCP.NS', 'IRB.NS', 'IRCON.NS', 'ISEC.NS', 'JBCHEPHARM.NS', 'JINDWORLD.NS', 'JKLAKSHMI.NS', 'JKPAPER.NS',
            'JSL.NS', 'JTEKTINDIA.NS', 'JYOTHYLAB.NS', 'KALPATPOWR.NS', 'KANSAINER.NS', 'KARURVYSYA.NS', 'KEC.NS', 'KIRLOSENG.NS', 'KNRCON.NS', 'KPITTECH.NS',
            'KRBL.NS', 'LALPATHLAB.NS', 'LEMONTREE.NS', 'LINDEINDIA.NS', 'LUXIND.NS', 'MAHSCOOTER.NS', 'MAITHANALL.NS', 'MANINFRA.NS', 'MARKSANS.NS', 'MAZDOCK.NS',
            'MEGH.NS', 'MIDHANI.NS', 'MINDACORP.NS', 'MMTC.NS', 'MOIL.NS', 'MOREPENLAB.NS', 'MPSLTD.NS', 'MTARTECH.NS', 'NESCO.NS', 'NETWORK18.NS',
            'NILKAMAL.NS', 'NOCIL.NS', 'OCCL.NS', 'OMAXE.NS', 'ORIENTELEC.NS', 'ORIENTREF.NS', 'PAGEIND.NS', 'PARAGMILK.NS', 'PCBL.NS', 'PDSL.NS',
            'PNBHOUSING.NS', 'PNCINFRA.NS', 'PPLPHARMA.NS', 'PRAJIND.NS', 'PRINCEPIPE.NS', 'PSPPROJECT.NS', 'PTC.NS', 'QUESS.NS', 'RALLIS.NS', 'RBLBANK.NS',
            'REDINGTON.NS', 'RICOAUTO.NS', 'ROSSARI.NS', 'ROUTE.NS', 'RTNPOWER.NS', 'SAGCEM.NS', 'SANOFI.NS', 'SCHAEFFLER.NS', 'SEQUENT.NS', 'SHILPAMED.NS',
            'SHOPERSTOP.NS', 'SHRIRAMCIT.NS', 'SIS.NS', 'SOBHA.NS', 'SOLARA.NS', 'SPARC.NS', 'SPICEJET.NS', 'STARCEMENT.NS', 'STLTECH.NS', 'SUBEXLTD.NS',
            'SUDARSCHEM.NS', 'SUMICHEM.NS', 'SUNDRMFAST.NS', 'SUNFLAG.NS', 'SUPRAJIT.NS', 'SUVENPHAR.NS', 'SWANENERGY.NS', 'SYMPHONY.NS', 'TANLA.NS', 'TCI.NS',
            'TCNSBRANDS.NS', 'TEAMLEASE.NS', 'THERMAX.NS', 'THYROCARE.NS', 'TIIL.NS', 'TIPSINDLTD.NS', 'TMB.NS', 'TORNTPOWER.NS', 'TRIVENI.NS', 'TTKPRESTIG.NS',
            'UJJIVANSFB.NS', 'ULTRACAB.NS', 'UNICHEMLAB.NS', 'UTIAMC.NS', 'VAIBHAVGBL.NS', 'VARROC.NS', 'VENKEYS.NS', 'VINDHYATEL.NS', 'VINYLINDIA.NS', 'VSTIND.NS',
            'WABCOINDIA.NS', 'WELSPUNIND.NS', 'WSTCSTPAPR.NS', 'YESBANK.NS', 'ZFCVINDIA.NS', 'ZUARI.NS'
        ]
        
    def fetch_data(self, symbol, period='5d', interval='5m'):
        """Fetch stock data with error handling"""
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period=period, interval=interval)
            if df.empty:
                return None
            return df
        except Exception as e:
            return None
    
    def calculate_ema(self, data, period):
        """Calculate Exponential Moving Average"""
        return data['Close'].ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, data, period=14):
        """Calculate Relative Strength Index"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_macd(self, data):
        """Calculate MACD"""
        exp1 = data['Close'].ewm(span=12, adjust=False).mean()
        exp2 = data['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd, signal
    
    def calculate_vwap(self, data):
        """Calculate Volume Weighted Average Price"""
        typical_price = (data['High'] + data['Low'] + data['Close']) / 3
        vwap = (typical_price * data['Volume']).cumsum() / data['Volume'].cumsum()
        return vwap
    
    def calculate_atr(self, data, period=14):
        """Calculate Average True Range"""
        high_low = data['High'] - data['Low']
        high_close = np.abs(data['High'] - data['Close'].shift())
        low_close = np.abs(data['Low'] - data['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean()
        return atr
    
    def detect_support_resistance(self, data, window=20):
        """Detect support and resistance levels"""
        highs = data['High'].rolling(window=window, center=True).max()
        lows = data['Low'].rolling(window=window, center=True).min()
        
        resistance = highs[data['High'] == highs].dropna().unique()
        support = lows[data['Low'] == lows].dropna().unique()
        
        return support[-3:] if len(support) > 0 else [], resistance[-3:] if len(resistance) > 0 else []
    
    def analyze_market_context(self):
        """Analyze overall market trend with enhanced display"""
        nifty_data = self.fetch_data('^NSEI', period='5d', interval='15m')
        banknifty_data = self.fetch_data('^NSEBANK', period='5d', interval='15m')
        
        if nifty_data is None or nifty_data.empty:
            return {'bias': 'NEUTRAL', 'score': 0, 'strength': 'UNKNOWN', 'nifty_price': 0, 'nifty_change': 0}
        
        # Calculate NIFTY indicators
        current_price = nifty_data['Close'].iloc[-1]
        prev_close = nifty_data['Close'].iloc[0]
        ema_20 = self.calculate_ema(nifty_data, 20).iloc[-1]
        ema_50 = self.calculate_ema(nifty_data, 50).iloc[-1]
        vwap = self.calculate_vwap(nifty_data).iloc[-1]
        rsi = self.calculate_rsi(nifty_data).iloc[-1]
        atr = self.calculate_atr(nifty_data).iloc[-1]
        
        # Bank NIFTY data
        bank_current = banknifty_data['Close'].iloc[-1] if banknifty_data is not None else 0
        bank_prev = banknifty_data['Close'].iloc[0] if banknifty_data is not None else 0
        
        # Market bias scoring
        score = 0
        
        # Price vs EMAs
        if current_price > ema_20:
            score += 2
        if current_price > ema_50:
            score += 2
        
        # Price vs VWAP
        if current_price > vwap:
            score += 1
        
        # RSI
        if rsi > 55:
            score += 1
        elif rsi < 45:
            score -= 1
        
        # Recent trend
        recent_change = ((current_price - prev_close) / prev_close) * 100
        if recent_change > 0.5:
            score += 2
        elif recent_change < -0.5:
            score -= 2
        
        # Determine bias
        if score >= 4:
            bias = 'BULLISH'
            strength = 'STRONG' if score >= 6 else 'MODERATE'
        elif score <= -4:
            bias = 'BEARISH'
            strength = 'STRONG' if score <= -6 else 'MODERATE'
        else:
            bias = 'NEUTRAL'
            strength = 'WEAK'
        
        bank_change = ((bank_current - bank_prev) / bank_prev * 100) if bank_prev != 0 else 0
        
        return {
            'bias': bias,
            'score': score,
            'strength': strength,
            'nifty_price': current_price,
            'nifty_change': recent_change,
            'nifty_ema20': ema_20,
            'nifty_ema50': ema_50,
            'nifty_vwap': vwap,
            'nifty_rsi': rsi,
            'nifty_atr': atr,
            'banknifty_price': bank_current,
            'banknifty_change': bank_change
        }
    
    def calculate_stock_score(self, symbol, market_context):
        """Calculate comprehensive score for a stock"""
        try:
            # Fetch data
            data_5m = self.fetch_data(symbol, period='5d', interval='5m')
            data_daily = self.fetch_data(symbol, period='60d', interval='1d')
            
            if data_5m is None or data_5m.empty or data_daily is None or data_daily.empty:
                return None
            
            if len(data_5m) < 50 or len(data_daily) < 20:
                return None
            
            # Current price and volume
            current_price = data_5m['Close'].iloc[-1]
            avg_volume = data_5m['Volume'].mean()
            current_volume = data_5m['Volume'].iloc[-1]
            
            # Liquidity filter
            if avg_volume < 100000 or current_price < 50 or current_price > 5000:
                return None
            
            # Calculate technical indicators
            ema_9 = self.calculate_ema(data_5m, 9).iloc[-1]
            ema_21 = self.calculate_ema(data_5m, 21).iloc[-1]
            ema_50 = self.calculate_ema(data_5m, 50).iloc[-1]
            ema_200_daily = self.calculate_ema(data_daily, 200).iloc[-1]
            
            rsi = self.calculate_rsi(data_5m, 14).iloc[-1]
            macd, signal = self.calculate_macd(data_5m)
            vwap = self.calculate_vwap(data_5m).iloc[-1]
            atr = self.calculate_atr(data_5m).iloc[-1]
            
            # Initialize score
            total_score = 0
            
            # 1. Market Bias Score (0-20 points)
            market_bias_score = 0
            if market_context['bias'] == 'BULLISH':
                market_bias_score = 15 if market_context['strength'] == 'STRONG' else 10
            elif market_context['bias'] == 'BEARISH':
                market_bias_score = -15 if market_context['strength'] == 'STRONG' else -10
            
            total_score += market_bias_score
            
            # 2. Technical Momentum Score (0-25 points)
            momentum_score = 0
            
            # EMA alignment
            if current_price > ema_9 > ema_21 > ema_50:
                momentum_score += 8
            elif current_price < ema_9 < ema_21 < ema_50:
                momentum_score -= 8
            elif current_price > ema_21:
                momentum_score += 3
            
            # RSI
            if 40 < rsi < 60:
                momentum_score += 3
            elif rsi > 70:
                momentum_score -= 2
            elif rsi < 30:
                momentum_score -= 2
            elif rsi > 55:
                momentum_score += 2
            
            # MACD
            if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
                momentum_score += 5
            elif macd.iloc[-1] > signal.iloc[-1]:
                momentum_score += 2
            
            # Daily trend alignment
            if current_price > ema_200_daily:
                momentum_score += 4
            
            total_score += momentum_score
            
            # 3. Chart Pattern Score (0-20 points)
            pattern_score = 0
            
            # VWAP position
            if current_price > vwap * 1.002:
                pattern_score += 5
            elif current_price < vwap * 0.998:
                pattern_score -= 5
            
            # Price action
            recent_bars = data_5m.tail(10)
            higher_lows = sum(recent_bars['Low'].diff() > 0) >= 6
            higher_highs = sum(recent_bars['High'].diff() > 0) >= 6
            
            if higher_lows and higher_highs:
                pattern_score += 6
            
            # Opening range
            if len(data_5m) > 12:
                opening_high = data_5m.head(12)['High'].max()
                opening_low = data_5m.head(12)['Low'].min()
                if current_price > opening_high:
                    pattern_score += 4
                elif current_price < opening_low:
                    pattern_score -= 4
            
            total_score += pattern_score
            
            # 4. Volume & Liquidity Score (0-15 points)
            volume_score = 0
            
            volume_ratio = current_volume / avg_volume
            if volume_ratio > 1.5:
                volume_score += 8
            elif volume_ratio > 1.2:
                volume_score += 5
            elif volume_ratio < 0.5:
                volume_score -= 3
            
            # Volume trend
            volume_increasing = data_5m['Volume'].tail(5).is_monotonic_increasing
            if volume_increasing and current_price > data_5m['Close'].iloc[-5]:
                volume_score += 4
            
            total_score += volume_score
            
            # 5. Volatility & Risk Penalty (0 to -10 points)
            volatility_penalty = 0
            
            atr_percent = (atr / current_price) * 100
            if atr_percent > 3:
                volatility_penalty -= 5
            elif atr_percent > 2:
                volatility_penalty -= 2
            
            total_score += volatility_penalty
            
            # Calculate expected move and confidence
            expected_move_low = atr * 0.8
            expected_move_high = atr * 1.5
            
            expected_pct_low = (expected_move_low / current_price) * 100
            expected_pct_high = (expected_move_high / current_price) * 100
            
            # Determine bias
            if total_score > 15:
                bias = 'BULLISH'
                confidence = 'HIGH' if total_score > 30 else 'MEDIUM'
            elif total_score < -15:
                bias = 'BEARISH'
                confidence = 'HIGH' if total_score < -30 else 'MEDIUM'
            else:
                bias = 'NEUTRAL'
                confidence = 'LOW'
            
            # Calculate stop loss and target
            stop_loss = atr * 1.5
            target = atr * 2.5
            
            return {
                'symbol': symbol.replace('.NS', ''),
                'current_price': round(current_price, 2),
                'total_score': round(total_score, 2),
                'bias': bias,
                'confidence': confidence,
                'expected_pct_low': round(expected_pct_low, 2),
                'expected_pct_high': round(expected_pct_high, 2),
                'expected_move_low': round(expected_move_low, 2),
                'expected_move_high': round(expected_move_high, 2),
                'stop_loss': round(stop_loss, 2),
                'target': round(target, 2),
                'atr': round(atr, 2),
                'rsi': round(rsi, 2),
                'volume_ratio': round(volume_ratio, 2),
                'market_bias_score': market_bias_score,
                'momentum_score': momentum_score,
                'pattern_score': pattern_score,
                'volume_score': volume_score
            }
            
        except Exception as e:
            return None
    
    def scan_all_stocks(self, market_context):
        """Scan all stocks and return top 10"""
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, symbol in enumerate(self.stock_universe):
            status_text.text(f"Analyzing {symbol.replace('.NS', '')}... ({idx+1}/{len(self.stock_universe)})")
            progress_bar.progress((idx + 1) / len(self.stock_universe))
            
            score_data = self.calculate_stock_score(symbol, market_context)
            if score_data:
                results.append(score_data)
        
        progress_bar.empty()
        status_text.empty()
        
        # Sort by total score
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values('total_score', ascending=False).head(10)
        results_df['rank'] = range(1, len(results_df) + 1)
        
        return results_df

# Main application
def main():
    st.markdown('<div class="main-header">📈 AUTOMATIC INTRADAY STOCK ANALYSIS SYSTEM</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">AI-Powered Stock Scanner for Next Trading Session | Live NSE Data</div>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ System Info")
        st.info("""
        **System Features:**
        - Live NSE stock fetching
        - Multi-timeframe analysis
        - Market context filtering
        - Risk management
        - Probability-based scoring
        """)
        
        st.warning("""
        **⚠️ Disclaimer:**
        - No profit guarantee
        - News can override signals
        - Gap risk exists
        - For decision support only
        """)
        
        scan_button = st.button("🚀 START ANALYSIS", type="primary", use_container_width=True)
    
    # Main content
    if scan_button:
        analyzer = IntradayAnalyzer()
        
        # Fetch stocks from NSE
        with st.spinner("Fetching live stock universe from NSE..."):
            analyzer.stock_universe = analyzer.fetch_nse_stocks()
        
        st.markdown(f"""
        <div class="info-box">
            <strong>📊 Stock Universe Loaded</strong><br>
            Total Stocks to Scan: <strong>{len(analyzer.stock_universe)}</strong> liquid NSE stocks
        </div>
        """, unsafe_allow_html=True)
        
        # Market Context Analysis
        st.header("📊 Market Context Analysis")
        with st.spinner("Analyzing live market conditions from NSE..."):
            market_context = analyzer.analyze_market_context()
        
        # 💾 Save market context to MongoDB
        if db_client.connected:
            db_client.save_market_context(market_context)
            st.caption("💾 Market context saved to database")
        
        # Enhanced Market Context Display
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            bias_class = market_context['bias'].lower()
            st.markdown(f"""
            <div class="metric-card">
                <h4>🎯 Market Bias</h4>
                <p class="{bias_class}">{market_context['bias']}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="metric-card">
                <h4>💪 Strength</h4>
                <p>{market_context['strength']}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="metric-card">
                <h4>📈 Market Score</h4>
                <p>{market_context['score']}/10</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            change_color = "bullish" if market_context.get('nifty_change', 0) > 0 else "bearish"
            st.markdown(f"""
            <div class="metric-card">
                <h4>📊 NIFTY Change</h4>
                <p class="{change_color}">{market_context.get('nifty_change', 0):.2f}%</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Additional Market Metrics
        st.markdown("### 🔍 Detailed Market Metrics")
        col5, col6, col7, col8 = st.columns(4)
        
        with col5:
            st.markdown(f"""
            <div class="metric-card">
                <h4>NIFTY 50 Price</h4>
                <p>₹{market_context.get('nifty_price', 0):.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col6:
            st.markdown(f"""
            <div class="metric-card">
                <h4>NIFTY RSI</h4>
                <p>{market_context.get('nifty_rsi', 0):.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col7:
            bank_change_color = "bullish" if market_context.get('banknifty_change', 0) > 0 else "bearish"
            st.markdown(f"""
            <div class="metric-card">
                <h4>Bank NIFTY Change</h4>
                <p class="{bank_change_color}">{market_context.get('banknifty_change', 0):.2f}%</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col8:
            st.markdown(f"""
            <div class="metric-card">
                <h4>NIFTY ATR</h4>
                <p>₹{market_context.get('nifty_atr', 0):.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        
        st.divider()
        
        # Stock Scanning
        st.header("🔍 Scanning Stock Universe")
        st.info(f"Analyzing {len(analyzer.stock_universe)} high-liquidity stocks from live NSE data...")
        
        with st.spinner("Running comprehensive analysis on all stocks..."):
            results_df = analyzer.scan_all_stocks(market_context)
        
        if not results_df.empty:
            st.success(f"✅ Analysis Complete! Found {len(results_df)} high-probability opportunities")
            
            # 💾 Save scan results to MongoDB
            if db_client.connected:
                _user = st.session_state.get('username', 'unknown')
                results_list = results_df.to_dict('records')
                db_client.save_scan_results(results_list, market_context, username=_user)
                db_client.save_scanner_run(
                    total_stocks_scanned=len(analyzer.stock_universe),
                    results_count=len(results_df),
                    market_bias=market_context.get('bias', 'UNKNOWN'),
                    username=_user
                )
                st.caption("💾 Scan results saved to database")
            
            st.header("🏆 TOP 10 INTRADAY STOCKS")
            
            # Display table
            display_df = results_df[[
                'rank', 'symbol', 'bias', 'expected_pct_low', 'expected_pct_high',
                'expected_move_low', 'expected_move_high', 'confidence', 'total_score'
            ]].copy()
            
            display_df.columns = [
                'Rank', 'Stock', 'Bias', 'Expected % (Low)', 'Expected % (High)',
                'Expected Points (Low)', 'Expected Points (High)', 'Confidence', 'Score'
            ]
            
            st.dataframe(
                display_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    'Rank': st.column_config.NumberColumn(format="%d"),
                    'Expected % (Low)': st.column_config.NumberColumn(format="%.2f%%"),
                    'Expected % (High)': st.column_config.NumberColumn(format="%.2f%%"),
                    'Expected Points (Low)': st.column_config.NumberColumn(format="₹%.2f"),
                    'Expected Points (High)': st.column_config.NumberColumn(format="₹%.2f"),
                    'Score': st.column_config.NumberColumn(format="%.2f")
                }
            )
            
            # Detailed view
            st.header("📋 Detailed Analysis")
            
            for idx, row in results_df.iterrows():
                with st.expander(f"#{row['rank']} - {row['symbol']} | {row['bias']} | Score: {row['total_score']:.2f}"):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Current Price", f"₹{row['current_price']:.2f}")
                        st.metric("Expected Move", f"₹{row['expected_move_low']:.2f} - ₹{row['expected_move_high']:.2f}")
                        st.metric("RSI", f"{row['rsi']:.2f}")
                    
                    with col2:
                        st.metric("Stop Loss", f"₹{row['stop_loss']:.2f}")
                        st.metric("Target", f"₹{row['target']:.2f}")
                        st.metric("ATR", f"₹{row['atr']:.2f}")
                    
                    with col3:
                        st.metric("Confidence", row['confidence'])
                        st.metric("Volume Ratio", f"{row['volume_ratio']:.2f}x")
                        rr_ratio = row['target'] / row['stop_loss']
                        st.metric("Risk:Reward", f"1:{rr_ratio:.2f}")
                    
                    st.markdown("**Score Breakdown:**")
                    breakdown_col1, breakdown_col2 = st.columns(2)
                    with breakdown_col1:
                        st.write(f"- Market Bias: {row['market_bias_score']}")
                        st.write(f"- Momentum: {row['momentum_score']}")
                    with breakdown_col2:
                        st.write(f"- Pattern: {row['pattern_score']}")
                        st.write(f"- Volume: {row['volume_score']}")
        else:
            st.warning("No qualifying stocks found. Market conditions may not be favorable.")
    
    else:
        st.info("👈 Click 'START ANALYSIS' in the sidebar to begin scanning")
        
        # Show scan history from MongoDB
        if db_client.connected:
            st.markdown("### 📜 Recent Scan History")
            scan_history = db_client.get_scan_history(limit=5)
            if scan_history:
                for run in scan_history:
                    ts = run.get('timestamp', '')
                    if hasattr(ts, 'strftime'):
                        ts = ts.strftime('%Y-%m-%d %H:%M UTC')
                    st.markdown(
                        f"- **{ts}** — Scanned {run.get('total_stocks_scanned', 0)} stocks, "
                        f"Found {run.get('qualifying_results', 0)} results, "
                        f"Market: {run.get('market_bias', 'N/A')}"
                    )
            else:
                st.info("No scan history yet. Run your first scan!")
            
            # Show latest results
            latest_results = db_client.get_latest_scan_results(limit=10)
            if latest_results:
                st.markdown("### 🏆 Latest Scan Results (from DB)")
                latest_data = []
                for r in latest_results:
                    latest_data.append({
                        'Rank': r.get('rank', 0),
                        'Symbol': r.get('symbol', ''),
                        'Score': round(r.get('total_score', 0), 2),
                        'Bias': r.get('bias', ''),
                        'Confidence': r.get('confidence', ''),
                        'Price': f"₹{r.get('current_price', 0):.2f}",
                    })
                st.dataframe(pd.DataFrame(latest_data), hide_index=True, use_container_width=True)
            
            # DB connection status
            st.sidebar.success("🟢 MongoDB Connected")
            stats = db_client.get_dashboard_stats()
            st.sidebar.metric("Total Scans", stats.get('total_scans', 0))
            st.sidebar.metric("Unique Stocks Scanned", stats.get('unique_tickers_scanned', 0))
        else:
            st.sidebar.error("🔴 MongoDB Disconnected")
        
        st.markdown("""
        ### 🎯 System Overview
        
        This professional intraday analysis system automatically:
        
        1. **Fetches live NSE stock universe** from official sources
        2. **Scans 150+ high-liquidity stocks** without manual input
        3. **Analyzes market context** (NIFTY trend, volatility, bias)
        4. **Calculates multi-factor scores** using:
           - Technical indicators (EMA, RSI, MACD, VWAP, ATR)
           - Chart patterns (breakouts, VWAP reclaim, trends)
           - Volume analysis and liquidity filters
           - Market alignment and momentum
        5. **Ranks stocks** by probability and confidence
        6. **Provides risk management** (stop-loss, targets, R:R ratios)
        7. **Outputs realistic expectations** (% range, point moves)
        
        ### 📊 Scoring Model
        
        Each stock receives a composite score based on:
        - **Market Bias Score** (0-20 points)
        - **Technical Momentum Score** (0-25 points)
        - **Chart Pattern Score** (0-20 points)
        - **Volume & Liquidity Score** (0-15 points)
        - **Volatility Penalty** (0 to -10 points)
        
        **Total Score Range:** -40 to +80 points
        
        ### ⚠️ Important Notes
        
        - This system provides **probability-based analysis**, not predictions
        - News events and gaps can override technical signals
        - Always use proper position sizing and risk management
        - Past performance does not guarantee future results
        - Designed as **decision support**, not trading certainty
        """)

if __name__ == "__main__":
    main()