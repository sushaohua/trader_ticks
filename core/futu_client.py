"""
Futu OpenD Client - Responsible for connection, subscription, and tick data reception.
"""


class FutuClient:
    """Connect to Futu OpenD, subscribe to market data, and receive ticks."""
    
    def __init__(self, host: str, port: int, password: str = ""):
        """
        Initialize Futu client.
        
        Args:
            host: IP address of Futu OpenD
            port: Port of Futu OpenD
            password: Password for Futu OpenD (if required)
        """
        self.host = host
        self.port = port
        self.password = password
    
    def connect(self):
        """Connect to Futu OpenD."""
        pass
    
    def subscribe(self, codes: list):
        """
        Subscribe to market data for given stock codes.
        
        Args:
            codes: List of stock codes (e.g., ['US.AAPL', 'HK.0700', 'SZ.000001'])
        """
        pass
    
    def receive_ticks(self):
        """Receive tick data stream from Futu OpenD."""
        pass
    
    def disconnect(self):
        """Disconnect from Futu OpenD."""
        pass
