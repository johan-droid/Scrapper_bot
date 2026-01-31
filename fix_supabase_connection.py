#!/usr/bin/env python3
"""
Fix for Supabase connection issue in GitHub Actions
"""

import os
from dotenv import load_dotenv

load_dotenv()

def test_supabase_connection():
    """Test Supabase connection with proper error handling"""
    
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    
    print(f"Supabase URL: {SUPABASE_URL}")
    print(f"Supabase Key: {SUPABASE_KEY[:20]}..." if SUPABASE_KEY else "Not set")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Supabase credentials not configured")
        return False
    
    try:
        # Try importing and initializing Supabase with proper error handling
        from supabase import create_client
        
        # Create client without proxy parameter
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Test connection with a simple query
        result = supabase.table('runs').select('id').limit(1).execute()
        
        print("✅ Supabase connection successful")
        print(f"Test query result: {result.data}")
        return True
        
    except Exception as e:
        print(f"❌ Supabase connection failed: {str(e)}")
        
        # Try alternative connection method
        try:
            from supabase import Client, create_client
            
            # Try with different initialization
            supabase = Client(SUPABASE_URL, SUPABASE_KEY)
            result = supabase.table('runs').select('id').limit(1).execute()
            
            print("✅ Supabase connection successful with alternative method")
            return True
            
        except Exception as e2:
            print(f"❌ Alternative connection also failed: {str(e2)}")
            return False

if __name__ == "__main__":
    test_supabase_connection()
