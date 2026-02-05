import logging
import sys
from datetime import datetime
from src.database import supabase, utc_tz

# Setup logging
logging.basicConfig(level=logging.INFO)

def diagnose():
    if not supabase:
        print("Supabase not connected")
        return

    print("--- FETCHING EXISTING RUNS ---")
    try:
        # Fetch last 5 runs to see what 'status' values are currently used
        r = supabase.table("runs").select("*").order("id", desc=True).limit(5).execute()
        for run in r.data:
            print(f"ID: {run['id']}, Date: {run['date']}, Slot: {run['slot']}, Status: {run['status']}")
    except Exception as e:
        print(f"Fetch failed: {e}")

    print("\n--- ATTEMPTING TEST INSERT ---")
    try:
        # Try to insert a dummy run with a 'safe' random slot to avoid collision
        test_slot = 999
        date_str = str(datetime.now().date())
        
        data = {
            "date": date_str,
            "slot": test_slot,
            "status": "started", # Testing 'started'
            "started_at": datetime.now(utc_tz).isoformat()
        }
        print(f"Inserting: {data}")
        r = supabase.table("runs").insert(data).execute()
        print(f"Insert Success: {r.data}")
        
        # Cleanup
        if r.data:
            print("Cleaning up test row...")
            supabase.table("runs").delete().eq("id", r.data[0]['id']).execute()
            
    except Exception as e:
        print(f"Insert Failed: {e}")
        # Try to get more info?
        if hasattr(e, 'response'):
             print(f"Response Body: {e.response.text if hasattr(e.response, 'text') else '?'}")

if __name__ == "__main__":
    diagnose()
