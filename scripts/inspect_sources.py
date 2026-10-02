import urllib.request
import ssl
import re
import json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

def inspect_home():
    for url in ['https://www.delhisldc.org/HomeSldc.aspx', 'https://www.delhisldc.org/']:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
            print(f"=== {url} ===")
            print(f"Size: {len(html)}")
            
            # Find spans with numbers or labels
            spans = re.findall(r'<span[^>]*id=["\']([^"\']+)["\'][^>]*>(.*?)</span>', html, re.I | re.S)
            for sid, sval in spans:
                sval_clean = re.sub(r'<[^>]+>', '', sval).strip()
                if any(k in sid.lower() for k in ['delhi', 'load', 'demand', 'freq', 'time', 'date', 'brpl', 'bypl', 'tpd', 'mes']):
                    print(f"SPAN [{sid}]: {sval_clean}")
                elif any(k in sval_clean.lower() for k in ['mw', 'hz']):
                    print(f"SPAN [{sid}] val: {sval_clean}")

            # Check for marquee or ticker
            marquees = re.findall(r'<marquee[^>]*>(.*?)</marquee>', html, re.I | re.S)
            for mq in marquees:
                mq_clean = re.sub(r'<[^>]+>', ' ', mq).strip()
                print(f"MARQUEE: {mq_clean[:200]}")
        except Exception as e:
            print(f"Error {url}: {e}")

if __name__ == '__main__':
    inspect_home()
