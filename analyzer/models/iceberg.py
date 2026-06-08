import pandas as pd
import numpy as np

class IcebergModel:
    def __init__(self, time_interval_ms=100, volume_cluster_threshold=3):
        self.time_interval_ms = time_interval_ms
        self.volume_cluster_threshold = volume_cluster_threshold
        
    def detect(self, df):
        """
        Detect Iceberg orders from a DataFrame of ticks.
        Required columns: 'price', 'volume'
        Optional: 'timestamp' (if available, otherwise we use row index as proxy or mock it)
        Returns a DataFrame marking potential iceberg executions.
        """
        if df.empty or 'volume' not in df.columns:
            return pd.DataFrame()
            
        df = df.copy()
        
        # 1. Volume Clustering Detection
        # Detect consecutive identical volumes at the same price
        df['prev_price'] = df['price'].shift(1)
        df['prev_vol'] = df['volume'].shift(1)
        
        df['same_price'] = df['price'] == df['prev_price']
        df['same_vol'] = df['volume'] == df['prev_vol']
        
        # Group consecutive identical volume/price ticks
        df['cluster_group'] = (~(df['same_price'] & df['same_vol'])).cumsum()
        
        cluster_counts = df.groupby('cluster_group').size()
        valid_clusters = cluster_counts[cluster_counts >= self.volume_cluster_threshold].index
        
        df['is_iceberg_volume'] = df['cluster_group'].isin(valid_clusters)
        
        # 2. Time interval detection (if timestamp exists)
        # Assuming traders might split 1000 into 5x200 every 50ms.
        # If timestamp is not in df, we only rely on volume clustering for now.
        
        return df[df['is_iceberg_volume']]
