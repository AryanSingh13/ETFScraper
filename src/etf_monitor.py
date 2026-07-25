
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

WATCHES = [("New ETF launch", "N-1A,S-1,N-2"), ("ETF prospectus change", "497,485BPOS"),]

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

def url_for(cik, a):
    return ("https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{a.replace('-','')}/{a}-index.htm")

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

def notify(label, rec):
    a, cik, form, date, issuer = rec
    detail = fund_name(cik, a, label == "New ETF launch")
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
            for label, forms in WATCHES:
                try:
                    for rec in search(forms):
                        recs.append((label, rec))
                except Exception as e:
                    log.info("search failed: %s", e)
                time.sleep(0.3)
            new = [(l, r) for (l, r) in recs if r[0] not in seen]
            if first:
                log.info("First run: seeding %d", len(new))
                seen.update(r[0] for (l, r) in new)
                first = False
            else:
                for label, rec in new:
                    log.info("NEW %s %s", label, rec[4])
                    try:
                        notify(label, rec)
                        seen.add(rec[0])
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
