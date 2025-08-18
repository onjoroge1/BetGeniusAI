#!/usr/bin/env python3
"""
Manual Collection Trigger - Test the scheduler manually for development
"""

import requests
import time

def trigger_manual_collection():
    """Trigger manual collection via API for testing"""
    
    print("🔧 MANUAL COLLECTION TRIGGER")
    print("=" * 40)
    
    # API endpoint and credentials
    url = "http://localhost:8000/admin/trigger-collection"
    headers = {
        "Authorization": "Bearer betgenius_secure_key_2024",
        "Content-Type": "application/json"
    }
    
    print(f"📡 Triggering collection at: {url}")
    print(f"🔑 Using authenticated request...")
    
    try:
        # Make the API call
        response = requests.post(url, headers=headers)
        
        print(f"📊 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ SUCCESS: {result['message']}")
            print(f"📋 Note: {result['note']}")
            print(f"⏰ Timing: {result['timing']}")
            print(f"\n📈 Collection is now running in background...")
            print(f"   • Check the server logs for detailed progress")
            print(f"   • This bypasses the normal 02:00-02:30 UTC restriction")
            print(f"   • Perfect for testing and development")
            
        elif response.status_code == 401:
            print(f"❌ AUTHENTICATION ERROR: Invalid API key")
            
        else:
            result = response.json()
            print(f"❌ ERROR: {result.get('message', 'Unknown error')}")
            
    except requests.exceptions.ConnectionError:
        print(f"❌ CONNECTION ERROR: Server not running on localhost:8000")
        print(f"   💡 Make sure the BetGenius AI server is started")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")

def check_collection_status():
    """Check if collection is still running by monitoring the logs"""
    
    print(f"\n🔍 MONITORING COLLECTION STATUS")
    print("=" * 40)
    print(f"📋 To monitor the collection progress:")
    print(f"   • Watch the server console logs")
    print(f"   • Look for 'ENHANCED dual collection cycle' messages")
    print(f"   • Collection typically takes 2-5 minutes")
    print(f"   • Final result will show matches collected per league")

if __name__ == "__main__":
    trigger_manual_collection()
    check_collection_status()