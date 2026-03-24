import pymongo
from pymongo.server_api import ServerApi
import datetime

MONGO_URI = "mongodb+srv://Trading:Trading2026@trading.xawhtqs.mongodb.net/?appName=Trading"

class TradingDB:
    def __init__(self):
        try:
            self.client = pymongo.MongoClient(MONGO_URI, server_api=ServerApi('1'))
            self.db = self.client['intraday_trading_engine']
            self.trades_collection = self.db['trade_history']
            self.memory_collection = self.db['ticker_memory']
            self.users_collection = self.db['users']
            self.searches_collection = self.db['search_history']
            # Test connection
            self.client.admin.command('ping')
            print("Pinged your deployment. You successfully connected to MongoDB!")
            self.connected = True
            
            # Seed default admin user if not exists
            admin_user = self.users_collection.find_one({'username': 'admin'})
            if not admin_user:
                self.create_user("admin", "admin123", is_admin=True)
            elif admin_user.get('password') != 'admin123':
                # Optional: Force password to admin123 if it was changed/corrupted
                self.users_collection.update_one(
                    {'username': 'admin'},
                    {'$set': {'password': 'admin123', 'is_admin': True}}
                )
                
        except Exception as e:
            print(f"MongoDB connection failed: {e}")
            self.connected = False

    def save_trade(self, trade_data):
        """Save a new trade to the trade_history collection"""
        if not self.connected: return False
        try:
            trade_data['created_at'] = datetime.datetime.utcnow()
            self.trades_collection.insert_one(trade_data)
            return True
        except Exception as e:
            print(f"Error saving trade: {e}")
            return False

    def update_ticker_memory(self, ticker, memory_data):
        """Update the tracking memory for a specific ticker"""
        if not self.connected: return False
        try:
            self.memory_collection.update_one(
                {'ticker': ticker},
                {'$set': {'memory': memory_data, 'updated_at': datetime.datetime.utcnow()}},
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
        """Get recent trades from global history"""
        if not self.connected: return []
        try:
            cursor = self.trades_collection.find().sort('created_at', -1).limit(limit)
            return list(cursor)
        except Exception as e:
            print(f"Error fetching trades: {e}")
            return []

    def create_user(self, username, password, is_admin=False):
        """Create a new user"""
        if not self.connected: return False
        try:
            if self.users_collection.find_one({'username': username}):
                return False # User exists
                
            self.users_collection.insert_one({
                'username': username,
                'password': password, # In production use hashing (e.g. bcrypt)
                'is_admin': is_admin,
                'created_at': datetime.datetime.utcnow()
            })
            return True
        except Exception as e:
            print(f"Error creating user: {e}")
            return False

    def verify_user(self, username, password):
        """Verify user credentials and return user doc if valid"""
        if not self.connected: return None
        try:
            user = self.users_collection.find_one({'username': username, 'password': password})
            return user
        except Exception as e:
            print(f"Error verifying user: {e}")
            return None

    def log_search(self, username, ticker, analysis_details=None):
        """Log a ticker search query by an authenticated user with detailed analysis results"""
        if not self.connected: return False
        try:
            doc = {
                'username': username,
                'ticker': ticker,
                'timestamp': datetime.datetime.utcnow()
            }
            if analysis_details:
                doc['details'] = analysis_details
                
            self.searches_collection.insert_one(doc)
            return True
        except Exception as e:
            print(f"Error logging search: {e}")
            return False
            
    def get_all_users_searches(self):
        """Retrieve recent searches for all users to display in admin view"""
        if not self.connected: return {}
        try:
            # Group searches by user, taking latest 10
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
            
            # Format as dictionary {username: [searches...]} keeping only top 10
            user_history = {}
            for res in results:
                user_history[res['_id']] = res['searches'][:10]
            return user_history
        except Exception as e:
            print(f"Error fetching searches: {e}")
            return {}

# Singleton instance
db_client = TradingDB()
