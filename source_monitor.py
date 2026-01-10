#!/usr/bin/env python3
"""
Source Health Monitor - Track the health of news sources
"""
import json
import time
import logging
from datetime import datetime, timedelta
from collections import defaultdict

class SourceHealthMonitor:
    def __init__(self, log_file="source_health.json"):
        self.log_file = log_file
        self.health_data = self.load_health_data()
    
    def load_health_data(self):
        try:
            with open(self.log_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "sources": {},
                "daily_stats": {},
                "last_updated": None
            }
    
    def save_health_data(self):
        self.health_data["last_updated"] = datetime.now().isoformat()
        with open(self.log_file, 'w') as f:
            json.dump(self.health_data, f, indent=2)
    
    def record_fetch_attempt(self, source, success, item_count=0, error=None):
        today = datetime.now().date().isoformat()
        
        # Initialize source data if not exists
        if source not in self.health_data["sources"]:
            self.health_data["sources"][source] = {
                "total_attempts": 0,
                "total_successes": 0,
                "total_items": 0,
                "last_success": None,
                "last_error": None,
                "consecutive_failures": 0
            }
        
        # Initialize daily stats if not exists
        if today not in self.health_data["daily_stats"]:
            self.health_data["daily_stats"][today] = {}
        
        if source not in self.health_data["daily_stats"][today]:
            self.health_data["daily_stats"][today][source] = {
                "attempts": 0,
                "successes": 0,
                "items": 0,
                "errors": []
            }
        
        # Update counters
        source_data = self.health_data["sources"][source]
        daily_data = self.health_data["daily_stats"][today][source]
        
        source_data["total_attempts"] += 1
        daily_data["attempts"] += 1
        
        if success:
            source_data["total_successes"] += 1
            source_data["total_items"] += item_count
            source_data["last_success"] = datetime.now().isoformat()
            source_data["consecutive_failures"] = 0
            
            daily_data["successes"] += 1
            daily_data["items"] += item_count
        else:
            source_data["consecutive_failures"] += 1
            if error:
                source_data["last_error"] = {
                    "message": str(error)[:200],
                    "timestamp": datetime.now().isoformat()
                }
                daily_data["errors"].append({
                    "message": str(error)[:100],
                    "timestamp": datetime.now().isoformat()
                })
        
        self.save_health_data()
    
    def get_source_health(self, source):
        if source not in self.health_data["sources"]:
            return None
        
        data = self.health_data["sources"][source]
        success_rate = (data["total_successes"] / data["total_attempts"]) * 100 if data["total_attempts"] > 0 else 0
        
        return {
            "source": source,
            "success_rate": round(success_rate, 2),
            "total_attempts": data["total_attempts"],
            "total_successes": data["total_successes"],
            "total_items": data["total_items"],
            "consecutive_failures": data["consecutive_failures"],
            "last_success": data["last_success"],
            "last_error": data["last_error"]
        }
    
    def get_daily_summary(self, date=None):
        if date is None:
            date = datetime.now().date().isoformat()
        
        if date not in self.health_data["daily_stats"]:
            return {}
        
        return self.health_data["daily_stats"][date]
    
    def print_health_report(self):
        print("=" * 60)
        print("SOURCE HEALTH REPORT")
        print("=" * 60)
        
        for source in ["ANN", "ANN_DC", "DCW", "TMS", "FANDOM"]:
            health = self.get_source_health(source)
            if health:
                status = "🟢" if health["consecutive_failures"] == 0 else "🔴" if health["consecutive_failures"] >= 3 else "🟡"
                print(f"{status} {source}:")
                print(f"   Success Rate: {health['success_rate']}%")
                print(f"   Total Items: {health['total_items']}")
                print(f"   Consecutive Failures: {health['consecutive_failures']}")
                if health["last_error"]:
                    print(f"   Last Error: {health['last_error']['message'][:50]}...")
                print()
            else:
                print(f"⚪ {source}: No data")
                print()
        
        # Daily summary
        today_summary = self.get_daily_summary()
        if today_summary:
            print("TODAY'S SUMMARY:")
            print("-" * 30)
            for source, data in today_summary.items():
                print(f"{source}: {data['successes']}/{data['attempts']} attempts, {data['items']} items")
        
        print("=" * 60)

# Global monitor instance
health_monitor = SourceHealthMonitor()

def monitor_source_call(source_name):
    """Decorator to monitor source calls"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                item_count = len(result) if result else 0
                health_monitor.record_fetch_attempt(source_name, True, item_count)
                return result
            except Exception as e:
                health_monitor.record_fetch_attempt(source_name, False, 0, e)
                raise
        return wrapper
    return decorator

if __name__ == "__main__":
    health_monitor.print_health_report()