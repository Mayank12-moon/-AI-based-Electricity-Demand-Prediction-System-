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

# Search for H.getAllFiles
for m in re.finditer(r'H\.getAllFiles', text):
    start = max(0, m.start() - 100)
    end = min(len(text), m.end() + 300)
    print("--- Call to H.getAllFiles ---")
    print(text[start:end].encode('ascii', errors='replace').decode('ascii'))
