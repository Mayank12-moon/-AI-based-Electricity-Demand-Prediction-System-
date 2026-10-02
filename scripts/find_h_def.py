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

m = re.search(r'getPageMetaData\s*:\s*["\']([^"\']+)["\']', text)
if m:
    print("getPageMetaData is:", m.group(1))

# Print all keys in H object
m_h = re.search(r'H\s*=\s*\{([^}]+)\}', text)
if m_h:
    print("H object content:", m_h.group(1)[:500])
else:
    # search around getPageMetaData
    m_around = re.search(r'getPageMetaData', text)
    if m_around:
        print("Around getPageMetaData:", text[m_around.start()-50:m_around.end()+300])
