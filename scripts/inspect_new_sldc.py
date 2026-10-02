import urllib.request
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def analyze_new_home():
    js_url = 'https://www.delhisldc.org/home-new/assets/index-DTMl6Qqy.js'
    req = urllib.request.Request(js_url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        js = resp.read().decode('utf-8', errors='ignore')

    print(f"JS file size: {len(js)} bytes")
    
    # Search for URLs, endpoints, API routes, keywords
    endpoints = set()
    for m in re.findall(r'["\'](/[^"\']+|https?://[^"\']+)["\']', js):
        if any(k in m.lower() for k in ['api', 'data', 'json', 'demand', 'load', 'sldc', 'realtime', 'get', 'fetch', 'chart', 'discom', 'aspx']):
            endpoints.add(m)
            
    print(f"Found {len(endpoints)} potential API/data endpoints:")
    for ep in sorted(endpoints):
        print("  EP:", ep)

if __name__ == '__main__':
    analyze_new_home()
