import pandas as pd
import numpy as np

class VPINModel:
    def __init__(self, volume_bucket_size=10000, window_size=50):
        self.volume_bucket_size = volume_bucket_size
        self.window_size = window_size
        
    def calculate(self, df):
        """
        Calculate VPIN from a DataFrame of ticks.
        Required columns: 'price', 'volume', 'ticker_direction'
        Returns a DataFrame with VPIN values per bucket.
        """
        if df.empty or 'volume' not in df.columns:
            return pd.DataFrame()
            
        # Ensure data is sorted by time if there was a timestamp, 
        # but here we assume order of rows is chronological.
        df = df.copy()
        
        # Estimate buy/sell volume
        # If ticker_direction is known:
        if 'ticker_direction' in df.columns:
            df['buy_vol'] = np.where(df['ticker_direction'].str.lower() == 'buy', df['volume'], 0)
            df['sell_vol'] = np.where(df['ticker_direction'].str.lower() == 'sell', df['volume'], 0)
            
            # For neutral/unknown, split evenly
            neutral_mask = ~df['ticker_direction'].str.lower().isin(['buy', 'sell'])
            df.loc[neutral_mask, 'buy_vol'] = df.loc[neutral_mask, 'volume'] / 2
            df.loc[neutral_mask, 'sell_vol'] = df.loc[neutral_mask, 'volume'] / 2
        else:
            # Fallback to Lee-Ready logic if direction is missing (price differences)
            df['price_diff'] = df['price'].diff()
            df['direction'] = np.sign(df['price_diff'])
            df['direction'] = df['direction'].replace(0, method='ffill').fillna(1)
            df['buy_vol'] = np.where(df['direction'] > 0, df['volume'], 0)
            df['sell_vol'] = np.where(df['direction'] < 0, df['volume'], 0)
            
        # Cumulative volume to assign buckets
        df['cum_vol'] = df['volume'].cumsum()
        df['bucket_id'] = df['cum_vol'] // self.volume_bucket_size
        
        # Aggregate by bucket
        buckets = df.groupby('bucket_id').agg({
            'buy_vol': 'sum',
            'sell_vol': 'sum',
            'volume': 'sum',
            'price': 'last' # Last price in bucket
        }).reset_index()
        
        # Remove incomplete last bucket if we want strictly full buckets
        # but for visualization, we can keep it.
        
        # Calculate Order Imbalance
        buckets['order_imbalance'] = abs(buckets['buy_vol'] - buckets['sell_vol'])
        
        # Calculate VPIN over rolling window
        # VPIN = Sum(Order Imbalance over window) / Sum(Volume over window)
        rolling_imbalance = buckets['order_imbalance'].rolling(window=self.window_size).sum()
        rolling_volume = buckets['volume'].rolling(window=self.window_size).sum()
        
        buckets['vpin'] = rolling_imbalance / rolling_volume
        
        return buckets
