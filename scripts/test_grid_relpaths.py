import urllib.request
import ssl
import json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0',
    'Content-Type': 'application/json'
}

paths = [
    '/reports/daily-reports/psp-report/',
    '/reports/daily-reports/psp-report',
    '/reports/daily-reports/daily-psp-report/',
    '/reports/daily-reports/daily-psp-report',
    '/reports/daily-psp-report',
    '/reports/daily-psp-report/',
    '/reports/psp-report',
    '/reports/daily-reports',
    '/reports/daily-reports/'
]

for p in paths:
    body = json.dumps({'_source': 'GRDW', '_relPath': p}).encode('utf-8')
    req = urllib.request.Request('https://webapi.grid-india.in/api/v1/page', data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            print(f"Path: {p} -> {len(data.get('retData', []))} items")
            if data.get('retData'):
                item = data['retData'][0]
                print("  Keys:", list(item.keys()))
                print("  Title:", item.get('Title_'))
                print("  PageFileType:", item.get('PageFileType'))
                print("  PageType:", item.get('PageType'))
                print("  uiType:", item.get('uiType'))
    except Exception as e:
        print(f"Path {p} failed: {e}")
