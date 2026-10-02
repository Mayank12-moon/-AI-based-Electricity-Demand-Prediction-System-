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

# Search for /reports/daily-reports/psp-report or psp-report
for m in re.finditer(r'psp-report', text, re.I):
    start = max(0, m.start() - 200)
    end = min(len(text), m.end() + 200)
    print("--- psp-report match ---")
    print(text[start:end].encode('ascii', errors='replace').decode('ascii'))
