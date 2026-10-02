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

# Search for network calls
print("--- Fetch / Axios calls ---")
calls = re.findall(r'(?:fetch|axios\.(?:get|post))\s*\(\s*[`\'"]([^`\'"]+)[`\'"]', text)
for c in set(calls):
    print("Call:", c)

# Search for webcdn
print("--- webcdn matches ---")
webcdn = re.findall(r'https?://webcdn\.grid-india\.in[^"\'\s,]*', text)
for w in set(webcdn):
    print("Webcdn:", w)
