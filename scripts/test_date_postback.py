import urllib.request
import urllib.parse
import ssl
import re
import json
import sys

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

def test_sldc_date_postback(target_date_str="30/09/2026"):
    print(f"Testing SLDC query for date: {target_date_str}")
    req = urllib.request.Request('https://www.delhisldc.org/Redirect.aspx?Loc=0805', headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='ignore')

    m_vs = re.search(r'name=["\']__VIEWSTATE["\'][^>]+value=["\']([^"\']*)["\']', html)
    m_ev = re.search(r'name=["\']__EVENTVALIDATION["\'][^>]+value=["\']([^"\']*)["\']', html)
    m_vg = re.search(r'name=["\']__VIEWSTATEGENERATOR["\'][^>]+value=["\']([^"\']*)["\']', html)

    if not m_vs or not m_ev:
        print("ViewState not found")
        return

    post_data = {
        '__EVENTTARGET': '',
        '__EVENTARGUMENT': '',
        '__VIEWSTATE': m_vs.group(1),
        '__VIEWSTATEGENERATOR': m_vg.group(1) if m_vg else '',
        '__EVENTVALIDATION': m_ev.group(1),
        'ctl00$ContentPlaceHolder2$cmbdiscom': 'Delhi',
        'ctl00$ContentPlaceHolder2$SelectedDate': target_date_str,
        'ctl00$ContentPlaceHolder2$Button1': 'Fetch Data'
    }
    encoded = urllib.parse.urlencode(post_data).encode('utf-8')
    post_req = urllib.request.Request('https://www.delhisldc.org/Loadcurve.aspx?Loc=0805', data=encoded, headers=headers)
    with urllib.request.urlopen(post_req, context=ctx, timeout=15) as resp:
        res_html = resp.read().decode('utf-8', errors='ignore')

    m_tbl = re.search(r'<table[^>]+id=["\']ContentPlaceHolder2_dgdetails["\'][^>]*>(.*?)</table>', res_html, re.S | re.I)
    if m_tbl:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m_tbl.group(1), re.S | re.I)
        print(f"Success for {target_date_str}: {len(rows)} rows found:")
        for r in rows:
            cells = [re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', ' ') for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S | re.I)]
            print("  ", cells)
    else:
        print(f"Table not found for {target_date_str}")

def test_delhi_sldc_daily_reports_details():
    print("\n--- Testing SLDC Daily Reports (Loc=1004) ---")
    url = 'https://www.delhisldc.org/Redirect.aspx?Loc=1004'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='ignore')

    # Look for table or links inside content placeholder
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.S | re.I)
    print(f"Total tables in Daily Reports page: {len(tables)}")
    # Find links to reports
    pdf_links = re.findall(r'href=["\']([^"\']+\.(?:pdf|xlsx?|csv))["\']', html, re.I)
    print(f"Report document links: {len(pdf_links)}")
    for l in pdf_links[:10]:
        print("  Doc link:", l)

if __name__ == '__main__':
    test_sldc_date_postback("30/09/2026")
    test_delhi_sldc_daily_reports_details()
