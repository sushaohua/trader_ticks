import pandas as pd
import numpy as np

class FlowSpeedModel:
    def __init__(self, rolling_window_seconds=60, speed_surge_threshold=100):
        self.rolling_window_seconds = rolling_window_seconds
        self.speed_surge_threshold = speed_surge_threshold
        
    def calculate(self, df):
        """
        Calculate Aggressive Order Flow Speed from a DataFrame of ticks.
        Required columns: 'price', 'volume'
        Returns a DataFrame summarizing tick flow.
        """
        if df.empty:
            return pd.DataFrame()
            
        df = df.copy()
        
        # In a real environment, we'd use the timestamp column.
        # If timestamp is not present, we will simulate a timeline for demonstration.
        if 'timestamp' not in df.columns:
            # Fake a timestamp: assume 1 tick = 0.1 seconds for testing if no timestamp
            df['timestamp'] = pd.Timestamp.now() + pd.to_timedelta(np.arange(len(df)) * 0.1, unit='s')
        else:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
        df.set_index('timestamp', inplace=True)
        
        # Resample to 1-second bins to count ticks
        # We count number of ticks per second
        tick_counts = df['price'].resample('1s').count().rename('tick_count')
        
        # Calculate rolling sum of ticks over the window
        rolling_speed = tick_counts.rolling(window=f"{self.rolling_window_seconds}s").sum()
        
        # Calculate aggressive direction if available
        if 'ticker_direction' in df.columns:
            # Create dummy variables for buy and sell
            df['is_buy'] = (df['ticker_direction'].str.lower() == 'buy').astype(int)
            df['is_sell'] = (df['ticker_direction'].str.lower() == 'sell').astype(int)
            
            buys = df['is_buy'].resample('1s').sum()
            sells = df['is_sell'].resample('1s').sum()
            
            rolling_buys = buys.rolling(window=f"{self.rolling_window_seconds}s").sum()
            rolling_sells = sells.rolling(window=f"{self.rolling_window_seconds}s").sum()
            
            result = pd.DataFrame({
                'tick_speed': rolling_speed,
                'buy_speed': rolling_buys,
                'sell_speed': rolling_sells
            })
            
            result['buy_ratio'] = result['buy_speed'] / result['tick_speed'].replace(0, np.nan)
        else:
            result = pd.DataFrame({'tick_speed': rolling_speed})
            
        result['is_surge'] = result['tick_speed'] >= self.speed_surge_threshold
        
        return result.reset_index()
