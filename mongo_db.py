import pymongo
from pymongo.server_api import ServerApi
import datetime

MONGO_URI = "mongodb+srv://Trading:Trading2026@trading.xawhtqs.mongodb.net/?appName=Trading"

class TradingDB:
    def __init__(self):
        try:
            self.client = pymongo.MongoClient(MONGO_URI, server_api=ServerApi('1'))
            self.db = self.client['intraday_trading_engine']
            
            # ===== SHARED COLLECTIONS =====
            self.users_collection = self.db['users']
            self.login_history_collection = self.db['login_history']       # Login audit trail
            
            # ===== STOCK SCANNER (app.py) COLLECTIONS =====
            self.scan_results_collection = self.db['scan_results']          # Top 10 scan results per run
            self.market_context_collection = self.db['market_context']      # Market bias, NIFTY, Bank NIFTY snapshots
            self.scanner_history_collection = self.db['scanner_history']    # Full scan run metadata (timestamp, stock count, etc.)
            
            # ===== INTRADAY ANALYSIS (intraday.py) COLLECTIONS =====
            self.trades_collection = self.db['trade_history']              # All trade signals generated
            self.memory_collection = self.db['ticker_memory']              # Per-ticker learning memory
            self.searches_collection = self.db['search_history']           # User search logs
            self.signals_collection = self.db['signals_log']               # Full signal snapshots
            self.analysis_collection = self.db['analysis_results']         # Complete analysis results
            self.daily_stats_collection = self.db['daily_statistics']      # Daily P&L, win rate, drawdown
            
            # Test connection
            self.client.admin.command('ping')
            print("✅ MongoDB Connected Successfully!")
            self.connected = True
            
            # Seed default admin user
            admin_user = self.users_collection.find_one({'username': 'admin'})
            if not admin_user:
                self.create_user("admin", "admin123", is_admin=True)
            elif admin_user.get('password') != 'admin123':
                self.users_collection.update_one(
                    {'username': 'admin'},
                    {'$set': {'password': 'admin123', 'is_admin': True}}
                )
            
            # Create indexes for performance
            self._create_indexes()
                
        except Exception as e:
            print(f"❌ MongoDB connection failed: {e}")
            self.connected = False

    def _create_indexes(self):
        """Create database indexes for query performance"""
        try:
            self.login_history_collection.create_index([("timestamp", -1)])
            self.login_history_collection.create_index([("username", 1), ("timestamp", -1)])
            self.scan_results_collection.create_index([("scan_timestamp", -1)])
            self.scan_results_collection.create_index([("symbol", 1), ("scan_timestamp", -1)])
            self.scan_results_collection.create_index([("username", 1), ("scan_timestamp", -1)])
            self.market_context_collection.create_index([("timestamp", -1)])
            self.scanner_history_collection.create_index([("timestamp", -1)])
            self.scanner_history_collection.create_index([("username", 1), ("timestamp", -1)])
            self.trades_collection.create_index([("created_at", -1)])
            self.trades_collection.create_index([("ticker", 1), ("created_at", -1)])
            self.signals_collection.create_index([("timestamp", -1)])
            self.signals_collection.create_index([("ticker", 1), ("timestamp", -1)])
            self.signals_collection.create_index([("username", 1), ("timestamp", -1)])
            self.analysis_collection.create_index([("timestamp", -1)])
            self.analysis_collection.create_index([("ticker", 1), ("timestamp", -1)])
            self.analysis_collection.create_index([("username", 1), ("timestamp", -1)])
            self.searches_collection.create_index([("timestamp", -1)])
            self.searches_collection.create_index([("username", 1), ("timestamp", -1)])
            self.daily_stats_collection.create_index([("date", -1)])
        except Exception as e:
            print(f"⚠️ Index creation error (non-critical): {e}")

    # =========================================================================
    # SHARED — USER MANAGEMENT
    # =========================================================================

    def create_user(self, username, password, is_admin=False):
        """Create a new user"""
        if not self.connected: return False
        try:
            if self.users_collection.find_one({'username': username}):
                return False
            self.users_collection.insert_one({
                'username': username,
                'password': password,
                'is_admin': is_admin,
                'created_at': datetime.datetime.utcnow()
            })
            return True
        except Exception as e:
            print(f"Error creating user: {e}")
            return False

    def verify_user(self, username, password):
        """Verify user credentials"""
        if not self.connected: return None
        try:
            return self.users_collection.find_one({'username': username, 'password': password})
        except Exception as e:
            print(f"Error verifying user: {e}")
            return None

    def get_all_users(self):
        """Get all users (for admin panel)"""
        if not self.connected: return []
        try:
            users = list(self.users_collection.find({}, {'password': 0}))
            for u in users:
                u['_id'] = str(u['_id'])
            return users
        except Exception as e:
            print(f"Error fetching users: {e}")
            return []

    def update_user(self, username, update_data):
        """Update a user's details"""
        if not self.connected: return False
        try:
            update_fields = {}
            if 'password' in update_data and update_data['password']:
                update_fields['password'] = update_data['password']
            if 'is_admin' in update_data:
                update_fields['is_admin'] = update_data['is_admin']
            if not update_fields:
                return False
            self.users_collection.update_one(
                {'username': username},
                {'$set': update_fields}
            )
            return True
        except Exception as e:
            print(f"Error updating user: {e}")
            return False

    def delete_user(self, username):
        """Delete a user (cannot delete the primary admin)"""
        if not self.connected: return False
        if username == 'admin':
            return False
        try:
            result = self.users_collection.delete_one({'username': username})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting user: {e}")
            return False

    # =========================================================================
    # STOCK SCANNER (app.py) — DATABASE OPERATIONS
    # =========================================================================

    def save_scan_results(self, results_list, market_context_data, username='unknown'):
        """Save the top 10 scan results from a stock scanner run"""
        if not self.connected: return False
        try:
            scan_timestamp = datetime.datetime.utcnow()
            
            # Save each stock result
            for result in results_list:
                doc = {
                    'scan_timestamp': scan_timestamp,
                    'username': username,
                    'symbol': result.get('symbol', ''),
                    'rank': result.get('rank', 0),
                    'current_price': result.get('current_price', 0),
                    'total_score': result.get('total_score', 0),
                    'bias': result.get('bias', ''),
                    'confidence': result.get('confidence', ''),
                    'expected_pct_low': result.get('expected_pct_low', 0),
                    'expected_pct_high': result.get('expected_pct_high', 0),
                    'expected_move_low': result.get('expected_move_low', 0),
                    'expected_move_high': result.get('expected_move_high', 0),
                    'stop_loss': result.get('stop_loss', 0),
                    'target': result.get('target', 0),
                    'atr': result.get('atr', 0),
                    'rsi': result.get('rsi', 0),
                    'volume_ratio': result.get('volume_ratio', 0),
                    'market_bias_score': result.get('market_bias_score', 0),
                    'momentum_score': result.get('momentum_score', 0),
                    'pattern_score': result.get('pattern_score', 0),
                    'volume_score': result.get('volume_score', 0),
                    'market_context': {
                        'bias': market_context_data.get('bias', ''),
                        'nifty_price': market_context_data.get('nifty_price', 0),
                        'nifty_change': market_context_data.get('nifty_change', 0),
                    }
                }
                self.scan_results_collection.insert_one(doc)
            
            return True
        except Exception as e:
            print(f"Error saving scan results: {e}")
            return False

    def save_market_context(self, context_data):
        """Save a market context snapshot (NIFTY, Bank NIFTY, VIX, etc.)"""
        if not self.connected: return False
        try:
            doc = {
                'timestamp': datetime.datetime.utcnow(),
                'bias': context_data.get('bias', ''),
                'score': context_data.get('score', 0),
                'strength': context_data.get('strength', ''),
                'nifty_price': context_data.get('nifty_price', 0),
                'nifty_change': context_data.get('nifty_change', 0),
                'nifty_ema20': context_data.get('nifty_ema20', 0),
                'nifty_ema50': context_data.get('nifty_ema50', 0),
                'nifty_vwap': context_data.get('nifty_vwap', 0),
                'nifty_rsi': context_data.get('nifty_rsi', 0),
                'nifty_atr': context_data.get('nifty_atr', 0),
                'banknifty_price': context_data.get('banknifty_price', 0),
                'banknifty_change': context_data.get('banknifty_change', 0),
            }
            self.market_context_collection.insert_one(doc)
            return True
        except Exception as e:
            print(f"Error saving market context: {e}")
            return False

    def save_scanner_run(self, total_stocks_scanned, results_count, market_bias, username='unknown'):
        """Save metadata about a scanner run"""
        if not self.connected: return False
        try:
            doc = {
                'timestamp': datetime.datetime.utcnow(),
                'username': username,
                'total_stocks_scanned': total_stocks_scanned,
                'qualifying_results': results_count,
                'market_bias': market_bias,
            }
            self.scanner_history_collection.insert_one(doc)
            return True
        except Exception as e:
            print(f"Error saving scanner run: {e}")
            return False

    def get_scan_history(self, limit=20):
        """Get recent scan history runs"""
        if not self.connected: return []
        try:
            return list(self.scanner_history_collection.find().sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching scan history: {e}")
            return []

    def get_latest_scan_results(self, limit=10):
        """Get the most recent scan results"""
        if not self.connected: return []
        try:
            # Get latest scan timestamp
            latest = self.scan_results_collection.find_one(sort=[('scan_timestamp', -1)])
            if not latest:
                return []
            return list(self.scan_results_collection.find(
                {'scan_timestamp': latest['scan_timestamp']}
            ).sort('rank', 1).limit(limit))
        except Exception as e:
            print(f"Error fetching scan results: {e}")
            return []

    def get_symbol_scan_history(self, symbol, limit=10):
        """Get scan history for a specific symbol"""
        if not self.connected: return []
        try:
            return list(self.scan_results_collection.find(
                {'symbol': symbol}
            ).sort('scan_timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching symbol history: {e}")
            return []

    def get_market_context_history(self, limit=50):
        """Get recent market context snapshots"""
        if not self.connected: return []
        try:
            return list(self.market_context_collection.find().sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching market context history: {e}")
            return []

    # =========================================================================
    # INTRADAY ANALYSIS (intraday.py) — DATABASE OPERATIONS
    # =========================================================================

    def save_trade(self, trade_data, username='unknown'):
        """Save a trade signal to trade_history"""
        if not self.connected: return False
        try:
            trade_data['created_at'] = datetime.datetime.utcnow()
            trade_data['username'] = username
            self.trades_collection.insert_one(trade_data)
            return True
        except Exception as e:
            print(f"Error saving trade: {e}")
            return False

    def save_analysis_result(self, ticker, analysis_data, username='unknown'):
        """Save complete analysis result for a ticker"""
        if not self.connected: return False
        try:
            doc = {
                'timestamp': datetime.datetime.utcnow(),
                'username': username,
                'ticker': ticker,
                'current_price': analysis_data.get('current_price', 0),
                'trend': analysis_data.get('trend', ''),
                'signal': analysis_data.get('signal', ''),
                'signal_reason': analysis_data.get('signal_reason', ''),
                'entry_price': analysis_data.get('entry_price', 0),
                'stop_loss': analysis_data.get('stop_loss', 0),
                'target1': analysis_data.get('target1', 0),
                'target2': analysis_data.get('target2', 0),
                'target3': analysis_data.get('target3', 0),
                'risk_reward': analysis_data.get('risk_reward', 0),
                'confidence_score': analysis_data.get('confidence_score', 0),
                'confidence_level': analysis_data.get('confidence_level', ''),
                'strategy_tag': analysis_data.get('strategy_tag', ''),
                'rsi': analysis_data.get('rsi', 0),
                'vwap': analysis_data.get('vwap', 0),
                'support': analysis_data.get('support', 0),
                'resistance': analysis_data.get('resistance', 0),
                'market_regime': analysis_data.get('market_regime', ''),
                'session_name': analysis_data.get('session_name', ''),
                'primary_bias': analysis_data.get('primary_bias', ''),
                'bias_strength': analysis_data.get('bias_strength', 0),
                # V2 fields
                'structure_bias': analysis_data.get('structure_bias', ''),
                'structure_score': analysis_data.get('structure_score', 0),
                'bos_type': analysis_data.get('bos_type', ''),
                'choch_type': analysis_data.get('choch_type', ''),
                'htf_bias': analysis_data.get('htf_bias', ''),
                'ltf_bias': analysis_data.get('ltf_bias', ''),
                'mtf_aligned': analysis_data.get('mtf_aligned', False),
                'volatility_regime': analysis_data.get('volatility_regime', ''),
                'order_flow': analysis_data.get('order_flow', ''),
                'liquidity_sweep': analysis_data.get('liquidity_sweep', False),
                'signal_stable': analysis_data.get('signal_stable', False),
                'position_size': analysis_data.get('position_size', 0),
                'slippage_pct': analysis_data.get('slippage_pct', 0),
                'nifty_bias': analysis_data.get('nifty_bias', ''),
                'vix': analysis_data.get('vix', 0),
                'volume_quality': analysis_data.get('volume_quality', ''),
                'volume_ratio': analysis_data.get('volume_ratio', 0),
            }
            self.analysis_collection.insert_one(doc)
            return True
        except Exception as e:
            print(f"Error saving analysis: {e}")
            return False

    def save_signal_log(self, ticker, signal_data, username='unknown'):
        """Save a signal snapshot for audit trail"""
        if not self.connected: return False
        try:
            doc = {
                'timestamp': datetime.datetime.utcnow(),
                'username': username,
                'ticker': ticker,
                'signal': signal_data.get('signal', ''),
                'entry': signal_data.get('entry', 0),
                'stop_loss': signal_data.get('stop_loss', 0),
                'target1': signal_data.get('target1', 0),
                'target2': signal_data.get('target2', 0),
                'target3': signal_data.get('target3', 0),
                'risk_reward': signal_data.get('risk_reward', 0),
                'strategy_tag': signal_data.get('strategy_tag', ''),
                'confidence': signal_data.get('confidence', 0),
                'reason': signal_data.get('reason', ''),
            }
            self.signals_collection.insert_one(doc)
            return True
        except Exception as e:
            print(f"Error saving signal log: {e}")
            return False

    def update_ticker_memory(self, ticker, memory_data):
        """Update tracking memory for a ticker"""
        if not self.connected: return False
        try:
            # Sanitize datetime objects for MongoDB
            sanitized = self._sanitize_for_mongo(memory_data)
            self.memory_collection.update_one(
                {'ticker': ticker},
                {'$set': {'memory': sanitized, 'updated_at': datetime.datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error updating memory: {e}")
            return False

    def get_ticker_memory(self, ticker):
        """Retrieve memory for a specific ticker"""
        if not self.connected: return None
        try:
            doc = self.memory_collection.find_one({'ticker': ticker})
            if doc and 'memory' in doc:
                return doc['memory']
            return None
        except Exception as e:
            print(f"Error fetching memory: {e}")
            return None

    def get_all_trades(self, limit=100):
        """Get recent trades"""
        if not self.connected: return []
        try:
            return list(self.trades_collection.find().sort('created_at', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching trades: {e}")
            return []

    def get_ticker_trades(self, ticker, limit=20):
        """Get trades for a specific ticker"""
        if not self.connected: return []
        try:
            return list(self.trades_collection.find(
                {'ticker': ticker}
            ).sort('created_at', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching ticker trades: {e}")
            return []

    def get_analysis_history(self, ticker, limit=20):
        """Get analysis history for a ticker"""
        if not self.connected: return []
        try:
            return list(self.analysis_collection.find(
                {'ticker': ticker}
            ).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching analysis history: {e}")
            return []

    def get_signal_history(self, ticker=None, limit=50):
        """Get signal audit trail"""
        if not self.connected: return []
        try:
            query = {'ticker': ticker} if ticker else {}
            return list(self.signals_collection.find(query).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching signal history: {e}")
            return []

    def save_daily_stats(self, stats_data):
        """Save daily statistics (P&L, win rate, drawdown)"""
        if not self.connected: return False
        try:
            today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
            doc = {
                'date': today,
                'updated_at': datetime.datetime.utcnow(),
                'total_trades': stats_data.get('total_trades', 0),
                'wins': stats_data.get('wins', 0),
                'losses': stats_data.get('losses', 0),
                'win_rate': stats_data.get('win_rate', 0),
                'total_pnl_pct': stats_data.get('total_pnl_pct', 0),
                'max_drawdown': stats_data.get('max_drawdown', 0),
                'consecutive_losses': stats_data.get('consecutive_losses', 0),
            }
            self.daily_stats_collection.update_one(
                {'date': today},
                {'$set': doc},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving daily stats: {e}")
            return False

    def get_daily_stats_history(self, limit=30):
        """Get daily stats history"""
        if not self.connected: return []
        try:
            return list(self.daily_stats_collection.find().sort('date', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching daily stats: {e}")
            return []

    def log_search(self, username, ticker, analysis_details=None):
        """Log a search query"""
        if not self.connected: return False
        try:
            doc = {
                'username': username,
                'ticker': ticker,
                'timestamp': datetime.datetime.utcnow()
            }
            if analysis_details:
                doc['details'] = self._sanitize_for_mongo(analysis_details)
            self.searches_collection.insert_one(doc)
            return True
        except Exception as e:
            print(f"Error logging search: {e}")
            return False

    def get_all_users_searches(self):
        """Get recent searches grouped by user"""
        if not self.connected: return {}
        try:
            pipeline = [
                {"$sort": {"timestamp": -1}},
                {"$group": {
                    "_id": "$username",
                    "searches": {"$push": {
                        "ticker": "$ticker",
                        "time": "$timestamp",
                        "details": {"$ifNull": ["$details", {}]}
                    }}
                }}
            ]
            results = list(self.searches_collection.aggregate(pipeline))
            user_history = {}
            for res in results:
                user_history[res['_id']] = res['searches'][:10]
            return user_history
        except Exception as e:
            print(f"Error fetching searches: {e}")
            return {}

    # =========================================================================
    # DASHBOARD — AGGREGATE STATISTICS
    # =========================================================================

    def get_dashboard_stats(self):
        """Get aggregate stats for the main dashboard"""
        if not self.connected:
            return {
                'total_scans': 0, 'total_analyses': 0, 'total_signals': 0,
                'total_trades': 0, 'unique_tickers_scanned': 0,
                'unique_tickers_analyzed': 0
            }
        try:
            return {
                'total_scans': self.scanner_history_collection.count_documents({}),
                'total_analyses': self.analysis_collection.count_documents({}),
                'total_signals': self.signals_collection.count_documents({}),
                'total_trades': self.trades_collection.count_documents({}),
                'unique_tickers_scanned': len(self.scan_results_collection.distinct('symbol')),
                'unique_tickers_analyzed': len(self.analysis_collection.distinct('ticker')),
            }
        except Exception as e:
            print(f"Error fetching dashboard stats: {e}")
            return {
                'total_scans': 0, 'total_analyses': 0, 'total_signals': 0,
                'total_trades': 0, 'unique_tickers_scanned': 0,
                'unique_tickers_analyzed': 0
            }

    def get_top_scanned_symbols(self, limit=10):
        """Get most frequently scanned symbols"""
        if not self.connected: return []
        try:
            pipeline = [
                {"$group": {"_id": "$symbol", "count": {"$sum": 1}, "avg_score": {"$avg": "$total_score"}}},
                {"$sort": {"count": -1}},
                {"$limit": limit}
            ]
            return list(self.scan_results_collection.aggregate(pipeline))
        except Exception as e:
            print(f"Error: {e}")
            return []

    def get_top_analyzed_tickers(self, limit=10):
        """Get most frequently analyzed tickers"""
        if not self.connected: return []
        try:
            pipeline = [
                {"$group": {"_id": "$ticker", "count": {"$sum": 1}, "avg_confidence": {"$avg": "$confidence_score"}}},
                {"$sort": {"count": -1}},
                {"$limit": limit}
            ]
            return list(self.analysis_collection.aggregate(pipeline))
        except Exception as e:
            print(f"Error: {e}")
            return []

    # =========================================================================
    # LOGIN HISTORY
    # =========================================================================

    def log_login(self, username, ip_address='N/A'):
        """Record a login event"""
        if not self.connected: return False
        try:
            self.login_history_collection.insert_one({
                'username': username,
                'timestamp': datetime.datetime.utcnow(),
                'ip_address': ip_address,
            })
            return True
        except Exception as e:
            print(f"Error logging login: {e}")
            return False

    def get_login_history(self, username=None, limit=100):
        """Get login history, optionally filtered by username"""
        if not self.connected: return []
        try:
            query = {'username': username} if username else {}
            return list(self.login_history_collection.find(query).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching login history: {e}")
            return []

    # =========================================================================
    # ADMIN — PER-USER HISTORY QUERIES
    # =========================================================================

    def get_user_search_history(self, username=None, limit=100):
        """Get search history for a specific user or all users"""
        if not self.connected: return []
        try:
            query = {'username': username} if username else {}
            return list(self.searches_collection.find(query).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching user search history: {e}")
            return []

    def get_user_analysis_history(self, username=None, limit=100):
        """Get analysis history for a specific user or all users"""
        if not self.connected: return []
        try:
            query = {'username': username} if username else {}
            return list(self.analysis_collection.find(query).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching user analysis history: {e}")
            return []

    def get_user_scan_history(self, username=None, limit=100):
        """Get scan run history for a specific user or all users"""
        if not self.connected: return []
        try:
            query = {'username': username} if username else {}
            return list(self.scanner_history_collection.find(query).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching user scan history: {e}")
            return []

    def get_user_signal_history(self, username=None, limit=100):
        """Get signal history for a specific user or all users"""
        if not self.connected: return []
        try:
            query = {'username': username} if username else {}
            return list(self.signals_collection.find(query).sort('timestamp', -1).limit(limit))
        except Exception as e:
            print(f"Error fetching user signal history: {e}")
            return []

    # =========================================================================
    # UTILITY
    # =========================================================================

    def _sanitize_for_mongo(self, data):
        """Recursively sanitize data for MongoDB (convert non-serializable types)"""
        if isinstance(data, dict):
            return {k: self._sanitize_for_mongo(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_for_mongo(item) for item in data]
        elif isinstance(data, (datetime.datetime, datetime.date)):
            return data.isoformat()
        elif hasattr(data, 'item'):  # numpy types
            return data.item()
        elif hasattr(data, '__float__'):
            return float(data)
        elif hasattr(data, '__int__'):
            return int(data)
        else:
            return data


# Singleton instance
db_client = TradingDB()
