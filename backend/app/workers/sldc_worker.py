"""
GridSense Delhi - Delhi SLDC Ingestion Worker
Polls both live SLDC telemetry endpoints:
  1. Loc=0804: Real-time instantaneous Demand (MW), Discom Drawal, OD/UD, and Generation.
  2. Loc=0805: Day Peak Load, Min Load, Avg Load and peak times up to current hour.
Implements quality checking, anomaly detection, generation tracking, and clean series upsertion.
"""
import re
import time
import urllib.request
import urllib.parse
import ssl
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from sqlalchemy.orm import Session
from app.models.models import TelemetryRaw, TelemetryCleaned, SourceHealthLog
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

SLDC_REALTIME_URL = "https://www.delhisldc.org/Redirect.aspx?Loc=0804"
SLDC_LOADCURVE_URL = "https://www.delhisldc.org/Redirect.aspx?Loc=0805"
SLDC_POST_URL = "https://www.delhisldc.org/Loadcurve.aspx?Loc=0805"
SLDC_FREQ_URL = "https://www.delhisldc.org/Freqcurve.aspx"
SLDC_SOURCE = "SLDC"

ENTITY_MAP = {
    "Delhi": "DELHI",
    "BRPL": "BRPL",
    "BYPL": "BYPL",
    "NDPL": "TPDDL",     # NDPL and TPDDL are identical
    "TPDDL": "TPDDL",
    "NDMC": "NDMC",
    "MES": "MES",
}

# Capacity thresholds for spike detection (MW)
MAX_PLAUSIBLE_MW = {
    "DELHI": 10000, "BRPL": 5000, "BYPL": 3000,
    "TPDDL": 4000, "NDMC": 600, "MES": 120
}
MIN_PLAUSIBLE_MW = 10  # Anything below this is an invalid/zero reading

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Cache latest generation readings for API
_latest_generation: List[Dict[str, Any]] = []


def _fetch_url(url: str, data: Optional[bytes] = None, timeout: int = 15) -> Optional[str]:
    """Fetch URL with retries and return HTML content."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            if attempt < 2:
                time.sleep(2 ** attempt * 1.5)
                continue
            logger.error(f"[SLDC] Failed to fetch {url} after 3 attempts: {exc}")
            return None


def _parse_realtime_page(html: str) -> Dict[str, Any]:
    """
    Extract instantaneous Delhi load, Discom drawal breakdown,
    scheduled allocation, OD/UD, and generation from Loc=0804.
    """
    result: Dict[str, Any] = {
        "delhi_load_mw": None,
        "delhi_schedule_mw": None,
        "source_time_str": None,
        "discoms": {},
        "generation": [],
        "frequency_hz": None,
    }

    # 1. Total Delhi Load
    m_load = re.search(r'id=["\']ContentPlaceHolder3_LblLoad["\'][^>]*>([^<]+)<', html)
    if m_load:
        val = m_load.group(1).strip()
        try:
            result["delhi_load_mw"] = float(val)
        except ValueError:
            pass

    # 2. Scheduled Allocation
    m_alloc = re.search(r'id=["\']ContentPlaceHolder3_LblCurrScheduledAllocation["\'][^>]*>([^<]+)<', html)
    if m_alloc:
        val = m_alloc.group(1).strip()
        try:
            result["delhi_schedule_mw"] = float(val)
        except ValueError:
            pass

    # 3. Source timestamp
    m_time = re.search(r'id=["\']ContentPlaceHolder3_ddtime["\'][^>]*>([^<]+)<', html)
    if m_time:
        result["source_time_str"] = m_time.group(1).strip()

    # 4. Discom Drawal Table
    m_discom = re.search(r'<table[^>]+id=["\']ContentPlaceHolder3_DDISCOM["\'][^>]*>(.*?)</table>', html, re.S)
    if m_discom:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m_discom.group(1), re.S)
        for r in rows[1:]:  # skip header
            cells = [
                re.sub(r'<[^>]+>', '', c).strip().replace("&nbsp;", " ")
                for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)
            ]
            if len(cells) >= 3:
                name = cells[0].strip()
                code = ENTITY_MAP.get(name)
                if code:
                    def _parse_num(s):
                        clean = s.strip().replace(',', '')
                        try:
                            return float(clean)
                        except ValueError:
                            return None

                    sch = _parse_num(cells[1]) if len(cells) > 1 else None
                    drawl = _parse_num(cells[2]) if len(cells) > 2 else None
                    od_ud = _parse_num(cells[3]) if len(cells) > 3 else None
                    result["discoms"][code] = {
                        "schedule_mw": sch,
                        "drawl_mw": drawl,
                        "od_ud_mw": od_ud
                    }

    # 5. Delhi Generation Table
    global _latest_generation
    m_genco = re.search(r'<table[^>]+id=["\']ContentPlaceHolder3_dgenco["\'][^>]*>(.*?)</table>', html, re.S)
    if m_genco:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m_genco.group(1), re.S)
        genco_list = []
        for r in rows[1:]:
            cells = [
                re.sub(r'<[^>]+>', '', c).strip().replace("&nbsp;", " ")
                for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)
            ]
            if len(cells) >= 4 and cells[0].strip() and cells[0].strip() != "Total":
                try:
                    genco_list.append({
                        "plant_name": cells[0].strip(),
                        "schedule_mw": float(cells[1].replace(',', '')) if cells[1].strip() else 0.0,
                        "actual_mw": float(cells[3].replace(',', '')) if cells[3].strip() else 0.0,
                        "ui_mw": float(cells[4].replace(',', '')) if len(cells) > 4 and cells[4].strip() else 0.0,
                    })
                except (ValueError, IndexError):
                    pass
        if genco_list:
            result["generation"] = genco_list
            _latest_generation = genco_list

    return result


def _parse_dgdetails_table(html: str) -> List[Dict[str, Any]]:
    """Extract the ContentPlaceHolder2_dgdetails HTML table rows from Loc=0805."""
    results = []
    m = re.search(
        r'<table[^>]+id=["\']ContentPlaceHolder2_dgdetails["\'][^>]*>(.*?)</table>',
        html, re.S | re.I
    )
    if not m:
        return results

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S | re.I)
    for row in rows[1:]:  # skip header row
        cells = [
            re.sub(r'<[^>]+>', '', c).strip().replace("&nbsp;", " ")
            for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S | re.I)
        ]
        if len(cells) >= 6 and cells[0].strip():
            entity_label = cells[0].strip()
            entity_code = ENTITY_MAP.get(entity_label)
            if not entity_code:
                continue
            try:
                def _val(c):
                    s = c.strip().lstrip('-').replace('.', '', 1)
                    return float(c) if s.isdigit() else None

                record = {
                    "entity_label": entity_label,
                    "entity_code": entity_code,
                    "peak_mw": _val(cells[1]),
                    "peak_time_str": cells[2].strip(),
                    "min_mw": _val(cells[3]),
                    "min_time_str": cells[4].strip(),
                    "avg_mw": _val(cells[5]),
                }
                results.append(record)
            except (ValueError, IndexError) as e:
                logger.warning(f"[SLDC] Row parse error for {entity_label}: {e}")
    return results


def _check_quality(entity_code: str, demand_mw: Optional[float]) -> str:
    """Assign quality flag based on value plausibility."""
    if demand_mw is None:
        return "MISSING"
    if demand_mw < MIN_PLAUSIBLE_MW:
        return "ZERO"
    max_val = MAX_PLAUSIBLE_MW.get(entity_code, 15000)
    if demand_mw > max_val:
        return "SPIKE"
    return "OK"


def _parse_time_today(time_str: Optional[str]) -> Optional[datetime]:
    """Convert HH:MM:SS to full IST datetime for today."""
    if not time_str:
        return None
    try:
        now_ist = datetime.now(IST)
        parts = [int(p) for p in time_str.split(':')]
        h = parts[0] if len(parts) > 0 else 0
        m = parts[1] if len(parts) > 1 else 0
        s = parts[2] if len(parts) > 2 else 0
        return now_ist.replace(hour=h, minute=m, second=s, microsecond=0)
    except Exception:
        return None


def fetch_and_store_live() -> Dict[str, Any]:
    """
    Fetch both real-time instantaneous data (Loc=0804) and daily stats (Loc=0805),
    join them per entity, quality-check, and store in DB.
    """
    fetch_start = time.time()
    now_ist = datetime.now(IST)
    summary: dict[str, object] = {"records": 0, "success": False, "error": None}

    # 1. Fetch real-time feed (Loc=0804)
    html_rt = _fetch_url(SLDC_REALTIME_URL)
    rt_data = _parse_realtime_page(html_rt) if html_rt else {}

    # 2. Fetch load stats table (Loc=0805)
    html_stats = _fetch_url(SLDC_LOADCURVE_URL)
    stats_rows = _parse_dgdetails_table(html_stats) if html_stats else []

    # Map stats by entity code
    stats_by_code = {r["entity_code"]: r for r in stats_rows}

    # Build entity list (DELHI + 5 Discoms)
    all_codes = ["DELHI", "BRPL", "BYPL", "TPDDL", "NDMC", "MES"]
    
    if not rt_data.get("delhi_load_mw") and not stats_rows:
        summary["error"] = "Could not fetch data from either SLDC endpoint"
        _log_health(SLDC_SOURCE, False, int((time.time() - fetch_start) * 1000), 0, summary["error"])
        return summary

    db: Session = SessionLocal()
    try:
        ingested = 0
        naive_now = now_ist.replace(tzinfo=None)

        for ec in all_codes:
            stats = stats_by_code.get(ec, {})
            peak_mw = stats.get("peak_mw")
            min_mw = stats.get("min_mw")
            avg_mw = stats.get("avg_mw")
            peak_time = _parse_time_today(stats.get("peak_time_str"))
            min_time = _parse_time_today(stats.get("min_time_str"))

            # Determine real-time instantaneous demand MW:
            # First choice: real-time drawal from Loc=0804
            demand_mw = None
            if ec == "DELHI":
                demand_mw = rt_data.get("delhi_load_mw")
            else:
                discom_rt = rt_data.get("discoms", {}).get(ec, {})
                demand_mw = discom_rt.get("drawl_mw")

            # Fallback to stats avg or peak if Loc=0804 was down
            if demand_mw is None:
                demand_mw = avg_mw or peak_mw

            qflag = _check_quality(ec, demand_mw)

            raw_record = TelemetryRaw(
                entity_code=ec,
                timestamp_ist=naive_now,
                demand_mw=demand_mw,
                peak_mw=peak_mw,
                peak_time=peak_time.replace(tzinfo=None) if peak_time else None,
                min_mw=min_mw,
                min_time=min_time.replace(tzinfo=None) if min_time else None,
                avg_mw=avg_mw,
                source_name=SLDC_SOURCE,
                source_url=SLDC_REALTIME_URL if ec in rt_data.get("discoms", {}) or ec == "DELHI" else SLDC_LOADCURVE_URL,
                fetched_at=naive_now,
                quality_flag=qflag,
                raw_payload=f"rt_demand={demand_mw},peak={peak_mw},min={min_mw},avg={avg_mw},src_time={rt_data.get('source_time_str')}",
            )
            db.add(raw_record)
            ingested += 1

            # Cleaned series upsert (check existing timestamp to avoid UniqueConstraint errors)
            if qflag == "OK" and demand_mw is not None:
                # Round to nearest minute for clean series
                clean_ts = naive_now.replace(second=0, microsecond=0)
                existing_clean = (
                    db.query(TelemetryCleaned)
                    .filter_by(entity_code=ec, timestamp_ist=clean_ts)
                    .first()
                )
                if existing_clean:
                    existing_clean.demand_mw = demand_mw
                    existing_clean.quality_score = 1.0
                else:
                    cleaned = TelemetryCleaned(
                        entity_code=ec,
                        timestamp_ist=clean_ts,
                        demand_mw=demand_mw,
                        imputed=False,
                        quality_score=1.0,
                    )
                    db.add(cleaned)

        db.commit()
        summary["records"] = ingested
        summary["success"] = True
        latency_ms = int((time.time() - fetch_start) * 1000)
        _log_health(SLDC_SOURCE, True, latency_ms, ingested, None)
        logger.info(
            f"[SLDC] Ingested {ingested} entity readings at {now_ist.strftime('%H:%M:%S')} IST "
            f"(Delhi Load: {rt_data.get('delhi_load_mw')} MW)"
        )

    except Exception as exc:
        db.rollback()
        summary["error"] = str(exc)
        _log_health(SLDC_SOURCE, False, int((time.time() - fetch_start) * 1000), 0, str(exc))
        logger.error(f"[SLDC] DB error: {exc}")
    finally:
        db.close()

    return summary


def get_latest_generation() -> List[Dict[str, Any]]:
    """Return latest cached Delhi power generation by plant."""
    global _latest_generation
    if not _latest_generation:
        html = _fetch_url(SLDC_REALTIME_URL)
        if html:
            _parse_realtime_page(html)
    return _latest_generation


def fetch_historical_date(date_str: str, discom: str = "Delhi") -> List[Dict]:
    """
    Fetch SLDC summary stats for a given historical date (DD/MM/YYYY).
    Uses ASP.NET postback to Loadcurve.aspx.
    """
    html = _fetch_url(SLDC_LOADCURVE_URL)
    if not html:
        return []

    m_vs = re.search(r'name=["\']__VIEWSTATE["\'][^>]+value=["\']([^"\']*)["\']', html)
    m_ev = re.search(r'name=["\']__EVENTVALIDATION["\'][^>]+value=["\']([^"\']*)["\']', html)
    m_vg = re.search(r'name=["\']__VIEWSTATEGENERATOR["\'][^>]+value=["\']([^"\']*)["\']', html)

    if not m_vs or not m_ev:
        logger.warning("[SLDC] Could not extract ViewState for historical fetch")
        return []

    post_data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": m_vs.group(1),
        "__VIEWSTATEGENERATOR": m_vg.group(1) if m_vg else "",
        "__EVENTVALIDATION": m_ev.group(1),
        "ctl00$ContentPlaceHolder2$cmbdiscom": discom,
        "ctl00$ContentPlaceHolder2$SelectedDate": date_str,
        "ctl00$ContentPlaceHolder2$Button1": "Fetch Data",
    }
    encoded = urllib.parse.urlencode(post_data).encode("utf-8")
    html_post = _fetch_url(SLDC_POST_URL, data=encoded)
    if not html_post:
        return []
    return _parse_dgdetails_table(html_post)


def _log_health(source: str, success: bool, latency_ms: int, records: int, error: Optional[str]):
    """Insert a source health log record."""
    db = SessionLocal()
    try:
        log = SourceHealthLog(
            source_name=source,
            success=success,
            latency_ms=latency_ms,
            records_ingested=records,
            error_message=error,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"[SLDC] Health log failed: {e}")
    finally:
        db.close()
