import urllib.request
import ssl
import json
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def probe_datagov():
    print("--- Probing data.gov.in ---")
    urls = [
        'https://api.data.gov.in/catalog/search?query=delhi%20electricity&api-key=579b464db66ecb387e3a7c63cb4a0f0',
        'https://data.gov.in/search?title=electricity%20demand%20delhi',
        'https://data.gov.in/search?title=power%20generation%20delhi'
    ]
    for u in urls:
        try:
            req = urllib.request.Request(u, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                data = resp.read()
                print(f"URL: {u[:60]}... Status: {resp.status}, Len: {len(data)}")
                if 'json' in resp.headers.get('Content-Type', ''):
                    j = json.loads(data.decode('utf-8', errors='ignore'))
                    print("  JSON keys:", list(j.keys()) if isinstance(j, dict) else len(j))
                else:
                    text = data.decode('utf-8', errors='ignore')
                    links = re.findall(r'href=["\'](/resource/[^"\']+|/dataset/[^"\']+)["\']', text)
                    print(f"  Dataset links found: {len(links)}, Sample: {links[:3]}")
        except Exception as e:
            print(f"Error {u[:60]}: {e}")

if __name__ == '__main__':
    probe_datagov()
