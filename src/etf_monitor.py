
#!/usr/bin/env python3
import html, json, re, time, logging
import urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER_AGENT = "ETF-Monitor aryansinghsf@gmail.com"
NTFY = "https://ntfy.sh/etf-filings-h28dk19x"
POLL = 300
DAYS = 3
STATE = Path.home() / ".etf_seen.json"

WATCHES = [
    ("New ETF registration", "N-1A", False),
    ("ETF launch candidate", "N-2,S-1,S-3", True),
    ("Upcoming ETF listing", "8-A12B", True),
    ("ETF Section 12(g) registration", "8-A12G", True),
]

EXCHANGES = (
    ("NYSE Arca", r"\bNYSE\s*ARCA\b"),
    ("NYSE American", r"\bNYSE\s*AMERICAN\b"),
    ("New York Stock Exchange",
     r"\bNEW YORK STOCK EXCHANGE\b|\bNYSE\b(?!\s*(?:ARCA|AMERICAN))"),
    ("Nasdaq", r"\bNASDAQ(?: STOCK MARKET)?\b"),
    ("Cboe BZX", r"\bCBOE BZX\b|\bBATS BZX\b"),
    ("Cboe", r"\bCBOE\b(?!\s+BZX)"),
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger()

def get(url, limit=None):
    r = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(r, timeout=30) as f:
        return f.read(limit).decode("utf-8", "ignore")

def load_seen():
    try:
        return set(json.loads(STATE.read_text()))
    except Exception:
        return set()

def save_seen(seen):
    STATE.write_text(json.dumps(sorted(seen)))

def url_for(cik, a):
    return ("https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{a.replace('-','')}/{a}-index.htm")

def filing_text(cik, a):
    base = ("https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{a.replace('-','')}")
    try:
        raw = get(f"{base}/{a}.txt", 800000)
    except Exception:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))

def has_etf_language(text):
    return bool(re.search(r"\bexchange[- ]traded (?:fund|product)\b", text,
                          re.IGNORECASE))

def listing_exchange(text):
    return "; ".join(name for name, pattern in EXCHANGES
                     if re.search(pattern, text, re.IGNORECASE))

def search(forms):
    today = datetime.now(timezone.utc).date()
    p = {"q": '"exchange-traded fund"', "forms": forms,
         "dateRange": "custom",
         "startdt": (today - timedelta(days=DAYS)).isoformat(),
         "enddt": today.isoformat()}
    u = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(p)
    out = {}

    for h in json.loads(get(u)).get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        a = s.get("adsh")
        if a and a not in out:
            cik = (s.get("ciks") or ["0"])[0]
            out[a] = (a, cik, s.get("form", "?"), s.get("file_date", "?"),
                      (s.get("display_names") or ["?"])[0])

    return list(out.values())

def fund_name(cik, a, deep):
    base = ("https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{a.replace('-','')}")
    try:
        hdr = get(f"{base}/{a}-index-headers.html")
    except Exception:
        return ""

    names = list(dict.fromkeys(re.findall(r"<SERIES-NAME>([^<\n]+)", hdr)))
    if not names:
        return ""
    doc = ""
    if deep:
        m = re.search(r"&lt;FILENAME&gt;(\S+\.htm)", hdr)
        if m:
            try:
                time.sleep(0.5)
                raw = get(f"{base}/{m.group(1)}", 500000)
                doc = re.sub(r"<[^>]+>", " ", html.unescape(raw))
            except Exception:
                pass
    parts = []
    for n in names[:4]:
        n = n.strip()
        t = None
        if doc:
            mm = re.search(re.escape(n) + r"\s*\(([A-Z]{2,6})\)", doc)
            t = mm.group(1) if mm else None
        parts.append(f"{n} ({t})" if t else n)
    return "; ".join(parts)

def notify(label, rec, exchange=""):
    a, cik, form, date, issuer = rec
    detail = fund_name(cik, a, label == "New ETF registration")
    if exchange:
        title = f"{label}: {issuer} ({exchange})"
    else:
        title = f"{label}: {detail}" if detail else f"{label}: {issuer} ({form})"
    body = f"{issuer}\nForm {form} filed {date}\n{url_for(cik, a)}"
    req = urllib.request.Request(NTFY, data=body.encode(),
        headers={"Title": title, "Priority": "high",
                 "User-Agent": USER_AGENT}, method="POST")
    urllib.request.urlopen(req, timeout=15).read()

def main():
    seen = load_seen()
    first = not STATE.exists()
    log.info("Monitor started")
    wait = POLL
    while True:
        try:
            recs = []
            for label, forms, validate in WATCHES:
                try:
                    for rec in search(forms):
                        recs.append((label, validate, rec))
                except Exception as e:
                    log.info("search failed: %s", e)
                time.sleep(0.3)
            new = [(l, v, r) for (l, v, r) in recs if r[0] not in seen]
            if first:
                log.info("First run: seeding %d", len(new))
                seen.update(r[0] for (l, v, r) in new)
                save_seen(seen)
                first = False
            else:
                for label, validate, rec in new:
                    log.info("NEW %s %s", label, rec[4])
                    try:
                        text = filing_text(rec[1], rec[0]) if validate else ""
                        if validate and text is None:
                            log.info("validation deferred: %s", rec[4])
                            continue
                        if validate and not has_etf_language(text):
                            log.info("skipped non-ETF candidate: %s", rec[4])
                            seen.add(rec[0])
                            save_seen(seen)
                            continue
                        exchange = listing_exchange(text) if label == "Upcoming ETF listing" else ""
                        if label == "Upcoming ETF listing" and not exchange:
                            log.info("skipped 8-A12B without a recognized exchange: %s", rec[4])
                            seen.add(rec[0])
                            save_seen(seen)
                            continue
                        notify(label, rec, exchange)
                        seen.add(rec[0])
                        save_seen(seen)
                        time.sleep(0.3)
                    except Exception as e:
                        log.info("notify failed %s", e)
                if not new:
                    log.info("No new filings (%d)", len(seen))
        except Exception as e:
            log.info("poll failed: %s", e)
            wait = min(wait * 2, 3600)
        time.sleep(wait)

main() 
