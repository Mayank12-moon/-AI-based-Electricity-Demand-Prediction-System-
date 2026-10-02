import urllib.request
import urllib.parse
import ssl
import re
import json
import os

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

def safe_fetch(url, data=None):
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            content = resp.read()
            return resp.status, resp.headers, content
    except Exception as e:
        return None, None, str(e).encode()

def probe_delhi_sldc_realtime():
    print("--- 1. Probing Delhi SLDC Realtime ---")
    status, hdrs, content = safe_fetch('https://www.delhisldc.org/Redirect.aspx?Loc=0805')
    if status != 200:
        print(f"Failed to fetch SLDC: {content}")
        return {}
    
    html = content.decode('utf-8', errors='ignore')
    # Parse table
    m = re.search(r'<table[^>]+id=["\']ContentPlaceHolder2_dgdetails["\'][^>]*>(.*?)</table>', html, re.S | re.I)
    table_data = []
    if m:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S | re.I)
        for r in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S | re.I)
            cells_clean = [re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', ' ') for c in cells]
            table_data.append(cells_clean)
    
    # Also check ViewState and EventValidation for posting
    viewstate = re.search(r'name=["\']__VIEWSTATE["\'][^>]+value=["\']([^"\']*)["\']', html)
    generator = re.search(r'name=["\']__VIEWSTATEGENERATOR["\'][^>]+value=["\']([^"\']*)["\']', html)
    eventval = re.search(r'name=["\']__EVENTVALIDATION["\'][^>]+value=["\']([^"\']*)["\']', html)
    selected_date = re.search(r'name=["\']ctl00\$ContentPlaceHolder2\$SelectedDate["\'][^>]+value=["\']([^"\']*)["\']', html)

    # Check chart image
    chart_img = re.search(r'<img[^>]+id=["\']ContentPlaceHolder2_chartcontrol1["\'][^>]+src=["\']([^"\']*)["\']', html)

    print(f"SLDC Status: {status}")
    print(f"Table rows: {len(table_data)}")
    for r in table_data:
        print("  ", r)
    print(f"Date input: {selected_date.group(1) if selected_date else None}")
    print(f"Chart Image URL: {chart_img.group(1) if chart_img else None}")
    
    # Also test posting to change Discom to 'BRPL'
    if viewstate and eventval:
        post_url = 'https://www.delhisldc.org/Loadcurve.aspx?Loc=0805'
        form_data = {
            '__EVENTTARGET': 'ctl00$ContentPlaceHolder2$cmbdiscom',
            '__EVENTARGUMENT': '',
            '__VIEWSTATE': viewstate.group(1),
            '__VIEWSTATEGENERATOR': generator.group(1) if generator else '',
            '__EVENTVALIDATION': eventval.group(1),
            'ctl00$ContentPlaceHolder2$cmbdiscom': 'BRPL',
            'ctl00$ContentPlaceHolder2$SelectedDate': selected_date.group(1) if selected_date else ''
        }
        encoded_data = urllib.parse.urlencode(form_data).encode('utf-8')
        post_status, post_hdrs, post_content = safe_fetch(post_url, data=encoded_data)
        print(f"Discom Postback Status: {post_status}, Content Length: {len(post_content) if post_content else 0}")
        if post_status == 200:
            post_html = post_content.decode('utf-8', errors='ignore')
            m_brpl = re.search(r'<table[^>]+id=["\']ContentPlaceHolder2_dgdetails["\'][^>]*>(.*?)</table>', post_html, re.S | re.I)
            if m_brpl:
                rows_brpl = re.findall(r'<tr[^>]*>(.*?)</tr>', m_brpl.group(1), re.S | re.I)
                print("BRPL Postback Table Rows:")
                for r in rows_brpl:
                    cells = [re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', ' ') for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S | re.I)]
                    print("   ", cells)

    return {"table": table_data}

def probe_delhi_sldc_reports():
    print("\n--- 2. Probing Delhi SLDC Reports & Archives ---")
    # Daily reports
    report_urls = [
        'https://www.delhisldc.org/Redirect.aspx?Loc=1004',
        'https://www.delhisldc.org/Redirect.aspx?Loc=1002',
        'https://www.delhisldc.org/dc_schedule.aspx'
    ]
    for u in report_urls:
        status, hdrs, content = safe_fetch(u)
        print(f"Report URL {u}: Status {status}, Length {len(content) if content else 0}")
        if status == 200:
            html = content.decode('utf-8', errors='ignore')
            # Look for links, tables or dates
            links = re.findall(r'href=["\']([^"\']+\.(?:pdf|csv|xlsx?|aspx[^"\']*))["\']', html, re.I)
            print(f"  Found {len(links)} links, sample: {links[:5]}")

def probe_grid_india():
    print("\n--- 3. Probing Grid-India / POSOCO Daily PSP Reports ---")
    urls = [
        'https://grid-india.in/reports/daily-reports/psp-report/',
        'https://grid-india.in/',
        'https://posoco.in/'
    ]
    for u in urls:
        status, hdrs, content = safe_fetch(u)
        print(f"Grid India URL {u}: Status {status}, Length {len(content) if content else 0}")
        if status == 200:
            html = content.decode('utf-8', errors='ignore')
            # Look for PSP report pdf or xls links
            psps = re.findall(r'href=["\']([^"\']*(?:PSP|psp|Daily)[^"\']*)["\']', html, re.I)
            print(f"  PSP links sample: {psps[:5]}")

def probe_open_meteo():
    print("\n--- 4. Probing Open-Meteo APIs for Delhi Zones ---")
    zones = {
        "Delhi_Central": {"lat": 28.6139, "lon": 77.2090},
        "BRPL_SouthWest": {"lat": 28.5355, "lon": 77.1600},
        "BYPL_East": {"lat": 28.6280, "lon": 77.2789},
        "TPDDL_North": {"lat": 28.7041, "lon": 77.1025},
        "MES_Cantonment": {"lat": 28.5961, "lon": 77.1350}
    }
    
    variables = "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,wind_speed_10m,cloud_cover,precipitation,shortwave_radiation,direct_radiation,diffuse_radiation"
    
    # Test forecast
    fc_url = f"https://api.open-meteo.com/v1/forecast?latitude=28.6139&longitude=77.2090&hourly={variables}&timezone=Asia%2FKolkata&forecast_days=16"
    status, _, content = safe_fetch(fc_url)
    print(f"Open-Meteo Forecast Status: {status}")
    if status == 200:
        data = json.loads(content.decode())
        print(f"  Hourly timesteps returned: {len(data.get('hourly', {}).get('time', []))}")
        print(f"  Sample time: {data['hourly']['time'][0]} to {data['hourly']['time'][-1]}")
        print(f"  Variables: {list(data.get('hourly', {}).keys())}")
    
    # Test Air Quality API
    aqi_url = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=28.6139&longitude=77.2090&hourly=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,european_aqi,us_aqi&timezone=Asia%2FKolkata"
    status, _, content = safe_fetch(aqi_url)
    print(f"Open-Meteo Air Quality Status: {status}")
    if status == 200:
        aqi_data = json.loads(content.decode())
        print(f"  AQI variables: {list(aqi_data.get('hourly', {}).keys())}")
    
    # Test Historical Archive
    hist_url = f"https://archive-api.open-meteo.com/v1/archive?latitude=28.6139&longitude=77.2090&start_date=2024-01-01&end_date=2024-01-05&hourly={variables}&timezone=Asia%2FKolkata"
    status, _, content = safe_fetch(hist_url)
    print(f"Open-Meteo Historical Archive Status: {status}")
    if status == 200:
        hist_data = json.loads(content.decode())
        print(f"  Archive timesteps returned: {len(hist_data.get('hourly', {}).get('time', []))}")

def probe_holidays():
    print("\n--- 5. Probing Indian Holiday Calendar ---")
    # Test free Nager.Date API
    nager_url = "https://date.nager.at/api/v3/PublicHolidays/2026/IN"
    status, _, content = safe_fetch(nager_url)
    print(f"Nager.Date IN 2026 Status: {status}")
    if status == 200:
        hols = json.loads(content.decode())
        print(f"  Holidays found for 2026: {len(hols)}")
        for h in hols[:6]:
            print(f"    {h['date']}: {h['localName']} ({h['name']})")
    else:
        print("  Testing fallback holiday check...")

if __name__ == '__main__':
    probe_delhi_sldc_realtime()
    probe_delhi_sldc_reports()
    probe_grid_india()
    probe_open_meteo()
    probe_holidays()
