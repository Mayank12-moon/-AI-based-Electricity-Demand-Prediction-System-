import urllib.request
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def check_grid_india():
    req = urllib.request.Request('https://grid-india.in/reports/daily-reports/psp-report/', headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        text = resp.read().decode('utf-8', errors='ignore')
    
    scripts = re.findall(r'<script[^>]+src=["\'](.*?)["\']', text)
    print("Grid-India scripts:")
    for s in scripts:
        print(" ", s)

    # Let's inspect the main script to find the API endpoint for PSP reports
    for s in scripts:
        if 'index' in s or 'main' in s or 'assets' in s:
            full_url = s if s.startswith('http') else ('https://grid-india.in' + ('' if s.startswith('/') else '/') + s)
            print("Inspecting bundle:", full_url)
            try:
                b_req = urllib.request.Request(full_url, headers=headers)
                with urllib.request.urlopen(b_req, context=ctx, timeout=10) as b_resp:
                    bundle = b_resp.read().decode('utf-8', errors='ignore')
                    # Find API routes
                    api_matches = re.findall(r'["\'](/api/[^"\']+|https?://[^"\']*/api/[^"\']*)["\']', bundle)
                    print(f"  Found {len(api_matches)} API matches. Sample:")
                    for a in set(api_matches[:10]):
                        print("    API:", a)
            except Exception as e:
                print("Failed bundle inspect:", e)

if __name__ == '__main__':
    check_grid_india()
