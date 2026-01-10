#!/usr/bin/env python3
"""
Test script to verify the connection fixes work properly
"""
import sys
import os
import logging
from datetime import datetime

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import the fixed functions
from animebot import (
    fetch_anime_news, fetch_ann_dc_news, fetch_dc_updates, 
    fetch_tms_news, fetch_fandom_updates, circuit_breaker,
    get_scraping_session
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def test_session_creation():
    """Test that session creation works"""
    print("Testing session creation...")
    session = get_scraping_session()
    assert session is not None
    assert "User-Agent" in session.headers
    session.close()
    print("✓ Session creation works")

def test_circuit_breaker():
    """Test circuit breaker functionality"""
    print("Testing circuit breaker...")
    
    # Should allow calls initially
    assert circuit_breaker.can_call("TEST") == True
    
    # Record failures
    for i in range(3):
        circuit_breaker.record_failure("TEST")
    
    # Should block calls after threshold
    assert circuit_breaker.can_call("TEST") == False
    
    # Record success should reset
    circuit_breaker.record_success("TEST")
    assert circuit_breaker.can_call("TEST") == True
    
    print("✓ Circuit breaker works")

def test_source_fetching():
    """Test each source individually"""
    sources = [
        ("ANN", fetch_anime_news),
        ("ANN_DC", fetch_ann_dc_news),
        ("DCW", fetch_dc_updates),
        ("TMS", fetch_tms_news),
        ("FANDOM", fetch_fandom_updates)
    ]
    
    results = {}
    
    for name, func in sources:
        print(f"Testing {name}...")
        try:
            data = func()
            results[name] = len(data) if data else 0
            print(f"✓ {name}: {results[name]} items fetched")
        except Exception as e:
            results[name] = f"ERROR: {str(e)[:100]}"
            print(f"✗ {name}: {results[name]}")
    
    return results

def main():
    print("=" * 50)
    print("Testing Connection Fixes")
    print("=" * 50)
    
    try:
        test_session_creation()
        test_circuit_breaker()
        
        print("\nTesting source fetching (this may take a while)...")
        results = test_source_fetching()
        
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        
        working_sources = 0
        for source, result in results.items():
            if isinstance(result, int):
                print(f"{source}: ✓ {result} items")
                working_sources += 1
            else:
                print(f"{source}: ✗ {result}")
        
        print(f"\nWorking sources: {working_sources}/{len(results)}")
        
        if working_sources > 0:
            print("✓ At least some sources are working - fixes appear successful!")
        else:
            print("✗ No sources working - may need additional investigation")
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())