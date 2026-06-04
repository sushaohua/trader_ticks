"""
Parquet Engine - Responsible for in-memory buffer management and Parquet file writing.
"""


class ParquetEngine:
    """Manage memory buffer and write tick data to Parquet files."""
    
    def __init__(self, buffer_size: int = 10000):
        """
        Initialize Parquet engine.
        
        Args:
            buffer_size: Size of in-memory buffer before flushing to Parquet
        """
        self.buffer_size = buffer_size
        self.buffer = []
    
    def add_tick(self, tick_data: dict):
        """
        Add a tick data point to the buffer.
        
        Args:
            tick_data: Dictionary containing tick information
        """
        self.buffer.append(tick_data)
        if len(self.buffer) >= self.buffer_size:
            self.flush()
    
    def flush(self, output_path: str = None):
        """
        Flush buffer to Parquet file.
        
        Args:
            output_path: Path to save Parquet file
        """
        if not self.buffer:
            return
        
        # TODO: Write buffer to Parquet
        self.buffer = []
    
    def close(self):
        """Close engine and flush remaining data."""
        self.flush()
