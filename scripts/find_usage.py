import urllib.request
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {'User-Agent': 'Mozilla/5.0'}

req = urllib.request.Request('https://grid-india.in/assets/index-BYJJycyS.js', headers=headers)
with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
    text = resp.read().decode('utf-8', errors='ignore')

# Search for daily_psp_report usage in JSX / components
for m in re.finditer(r'\.daily_psp_report\b', text):
    start = max(0, m.start() - 300)
    end = min(len(text), m.end() + 300)
    chunk = text[start:end].encode('ascii', errors='replace').decode('ascii')
    print("--- USAGE ---")
    print(chunk)
