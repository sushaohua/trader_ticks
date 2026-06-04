"""
Main Collector - Entry point for the trader ticks collection system.
Accepts parameters like --market US to specify which market to collect data for.
"""

import argparse
import json
import logging
from pathlib import Path


def setup_logging():
    """Setup logging configuration."""
    log_dir = Path(__file__).parent / "data" / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "collector.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def load_config(market: str):
    """
    Load configuration for the specified market.
    
    Args:
        market: Market code (US, HK, CN)
        
    Returns:
        Configuration dictionary
    """
    config_dir = Path(__file__).parent / "configs"
    
    # Load Futu settings
    futu_settings_path = config_dir / "futu_settings.json"
    with open(futu_settings_path, 'r') as f:
        futu_config = json.load(f)
    
    # Load market-specific watchlist
    watchlist_path = config_dir / f"watchlist_{market.lower()}.json"
    with open(watchlist_path, 'r') as f:
        watchlist = json.load(f)
    
    return {
        "market": market,
        "futu": futu_config,
        "watchlist": watchlist
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Trader Ticks Collector")
    parser.add_argument(
        "--market",
        type=str,
        choices=["US", "HK", "CN"],
        required=True,
        help="Market to collect data for (US, HK, or CN)"
    )
    
    args = parser.parse_args()
    logger = setup_logging()
    
    logger.info(f"Starting collector for {args.market} market")
    
    try:
        config = load_config(args.market)
        logger.info(f"Loaded config for market: {config['market']}")
        
        # TODO: Initialize FutuClient and ParquetEngine
        # TODO: Start data collection loop
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
