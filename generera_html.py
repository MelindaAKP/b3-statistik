"""
B3 Teamtailor – Statisk HTML-generator
Kors av GitHub Actions dagligen. Sparar index.html.
"""

import json, re, os, sys
from datetime import date, datetime
from collections import defaultdict

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

API_KEY   = "H9pJ5doqgt5rOB5nV6Cj7JPDAUv1hJs9Itvea3t0"
BASE_URL  = "https://api.teamtailor.com/v1"
FROM_DATE = date(2026, 1, 1)
TO_DATE   = date.today()

HEADERS = {
    "Authorization": "Token token=" + API_KEY,
    "X-Api-Version": "20240404",
}

def api_get(path, params=None):
    r = requests.get(BASE_URL + "/" + path, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def parse_dt(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def is_pipe_stage(name):
    n = (name or "").lower()
    return "uppdrag" in n or "erbjudande" in n or n == "offered"

def is_hired_stage(name):
    n = (name or "").lower()
    return n == "hired" or ("anst" in n and "ll" in n)

def avg(lst):
    if not lst:
        return None
    return round(sum(lst) / len(lst), 1)

# Hamta jobb
print("Hamtar jobb...")
jobs = {}
p = 1
while True:
    d = api_get("jobs", {"page[size]": 30, "page[number]": p})
    for j in d.get("data", []):
        jobs[j["id"]] = j.get("attributes", {})
    total = int((d.get("meta") or {}).get("page-count") or 1)
    if p >= total:
        break
    p += 1
print("  " + str(len(jobs)) + " jobb")

# Hamta ansokningar (nyaste forst)
print("Hamtar ansokningar...")
all_apps = []
incl_cands = {}
incl_jobs = {}
incl_stages = {}
p = 1
done = False
while not done:
    params = {
        "include": "candidate,job,stage",
        "sort": "-created-at",
        "page[size]": 30,
        "page[number]": p,
    }
    raw = api_get("job-applications", params)
    items = raw.get("data", [])
    if not items:
        break
    for inc in raw.get("included", []):
        t = inc.get("type", "")
        if t == "candidates":
            incl_cands[inc["id"]] = inc.get("attributes", {})
        elif t == "jobs":
            incl_jobs[inc["id"]] = inc.get("attributes", {})
        elif t in ("stages", "stage"):
            incl_stages[inc["id"]] = inc.get("attributes", {})
    for item in items:
        dt = parse_dt((item.get("attributes") or {}).get("created-at"))
        if dt is None:
            continue
        if dt.date() < FROM_DATE:
            done = True
            break
        if dt.date() <= TO_DATE:
            all_apps.append(item)
    total = int((raw.get("meta") or {}).get("page-count") or 1)
    print("  Sida " + str(p) + "/" + str(total) + " - " + str(len(all_apps)) + " ansokningar", end="\r")
    if p >= total:
        break
    p += 1
print("\n  " + str(len(all_apps)) + " ansokningar totalt")

# Analysera
hire_days = []
pipe_days = []
hired_list = []
b3_count = defaultdict(int)
monthly = defaultdict(int)

for app in all_apps:
    attr       = app.get("attributes", {})
    rels       = app.get("relationships", {})
    created_at = parse_dt(attr.get("created-at"))
    if not created_at:
        continue

    cand_id  = (rels.get("candidate", {}).get("data") or {}).get("id")
    job_id   = (rels.get("job",       {}).get("data") or {}).get("id")
    stage_id = (rels.get("stage",     {}).get("data") or {}).get("id")

    cand_attr  = incl_cands.get(cand_id, {})
    job_attr   = incl_jobs.get(job_id, jobs.get(job_id, {}))
    stage_name = incl_stages.get(stage_id, {}).get("name", "") if stage_id else ""
    changed_at = parse_dt(attr.get("changed-stage-at"))

    monthly[created_at.strftime("%Y-%m")] += 1

    b3 = None
    for src in [job_attr.get("title", ""), job_attr.get("department", ""),
                job_attr.get("company-name", ""), attr.get("sourced-from", "")]:
        if isinstance(src, str) and "b3" in src.lower():
            m = re.search(r'B3\s+\w+', src, re.IGNORECASE)
            if m:
                b3 = m.group(0).strip()
                break
    if not b3:
        for tag in (cand_attr.get("tags") or []):
            t = tag if isinstance(tag, str) else tag.get("name", "")
            if t.lower().startswith("b3"):
                b3 = t
                break
    b3_count[b3 or "Okant"] += 1

    if is_pipe_stage(stage_name) and changed_at:
        pipe_days.append(abs((changed_at - created_at).days))

    hired_at  = parse_dt(attr.get("hired-at"))
    hired_flg = is_hired_stage(stage_name) or hired_at is not None
    if hired_flg:
        hire_date = hired_at or (changed_at if is_hired_stage(stage_name) else None)
        days = abs((hire_date - created_at).days) if hire_date else None
        fname = cand_attr.get("first-name", "") or ""
        lname = cand_attr.get("last-name", "") or ""
        hired_list.append({
            "name":    (fname + " " + lname).strip() or "Kandidat " + str(cand_id),
            "job":     job_attr.get("title", ""),
            "applied": created_at.date().isoformat(),
            "hired":   hire_date.date().isoformat() if hire_date else "?",
            "days":    days,
        })
        if days is not None:
            hire_days.append(days)

hired_list.sort(key=lambda x: x["applied"], reverse=True)
monthly_sorted = dict(sorted(monthly.items()))
b3_sorted      = dict(sorted(b3_count.items(), key=lambda x: -x[1]))

tth_val = str(avg(hire_days)) if avg(hire_days) is not None else "-"
ttp_val = str(avg(pipe_days)) if avg(pipe_days) is not None else "-"

# Bygg tabell
hired_rows = ""
for h in hired_list[:100]:
    d = str(h["days"]) + " d" if h["days"] is not None else "-"
    hired_rows += (
        "<tr>"
        "<td class='fw-semibold'>" + h["name"] + "</td>"
        "<td><span class='badge-b3'>" + (h["job"] or "-") + "</span></td>"
        "<td>" + h["applied"] + "</td>"
        "<td>" + h["hired"] + "</td>"
        "<td class='text-end fw-bold'>" + d + "</td>"
        "</tr>"
    )

if hired_rows:
    hired_table = (
        "<div class='table-responsive'>"
        "<table class='table table-hover align-middle mb-0'>"
        "<thead><tr><th>Namn</th><th>Tjanst</th><th>Sokte</th>"
        "<th>Anstalld</th><th class='text-end'>Dagar</th></tr></thead>"
        "<tbody>" + hired_rows + "</tbody></table></div>"
    )
else:
    hired_table = "<p class='text-secondary text-center py-3'>Inga anstallda i perioden</p>"

period    = str(FROM_DATE) + " - " + str(TO_DATE)
generated = datetime.now().strftime("%Y-%m-%d %H:%M")

html = (
    "<!DOCTYPE html>\n"
    "<html lang='sv'>\n"
    "<head>\n"
    "<meta charset='UTF-8'>\n"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
    "<title>B3 Rekryteringsstatistik</title>\n"
    "<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>\n"
    "<script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'></script>\n"
    "<style>\n"
    "body{background:#f0f4f8;font-family:'Segoe UI',sans-serif}\n"
    ".navbar{background:#1a2236}\n"
    ".card{border:none;border-radius:16px;box-shadow:0 2px 12px rgba(0,0,0,.08)}\n"
    ".metric-card{text-align:center;padding:2rem 1rem}\n"
    ".metric-value{font-size:3rem;font-weight:700;color:#1a2236}\n"
    ".metric-unit{font-size:1rem;color:#6c757d;margin-top:-8px}\n"
    ".metric-label{font-size:.9rem;color:#6c757d;margin-top:.5rem;text-transform:uppercase;letter-spacing:.05em}\n"
    "table thead{background:#1a2236;color:white}\n"
    ".period-badge{background:#e8f0fe;color:#1a2236;border-radius:8px;padding:.3rem .8rem;font-size:.85rem;font-weight:600}\n"
    ".badge-b3{background:#e8f0fe;color:#1a2236;font-size:.8rem;font-weight:600;padding:.2rem .6rem;border-radius:6px}\n"
    "</style>\n"
    "</head>\n"
    "<body>\n"
    "<nav class='navbar navbar-dark px-4 py-3 d-flex justify-content-between align-items-center flex-wrap gap-2'>\n"
    "  <span class='text-white fw-bold fs-5'>B3 Rekryteringsstatistik</span>\n"
    "  <div class='d-flex align-items-center gap-3 flex-wrap'>\n"
    "    <span class='period-badge'>" + period + "</span>\n"
    "    <span class='text-white-50 small'>Uppdaterad: " + generated + "</span>\n"
    "  </div>\n"
    "</nav>\n"
    "<div class='container-fluid py-4 px-4'>\n"
    "  <div class='row g-4 mb-4'>\n"
    "    <div class='col-6 col-md-3'><div class='card metric-card'>"
    "<div class='metric-value'>" + str(len(all_apps)) + "</div>"
    "<div class='metric-unit'>ansokningar</div><div class='metric-label'>Totalt</div></div></div>\n"
    "    <div class='col-6 col-md-3'><div class='card metric-card'>"
    "<div class='metric-value'>" + str(len(hired_list)) + "</div>"
    "<div class='metric-unit'>anstallda</div><div class='metric-label'>Anstallda</div></div></div>\n"
    "    <div class='col-6 col-md-3'><div class='card metric-card' style='border-top:4px solid #4f8ef7'>"
    "<div class='metric-value text-primary'>" + tth_val + "</div>"
    "<div class='metric-unit'>dagar (genomsnitt)</div><div class='metric-label'>Time to Hire</div></div></div>\n"
    "    <div class='col-6 col-md-3'><div class='card metric-card' style='border-top:4px solid #f7a24f'>"
    "<div class='metric-value' style='color:#f7a24f'>" + ttp_val + "</div>"
    "<div class='metric-unit'>dagar (genomsnitt)</div><div class='metric-label'>Time to Pipe</div></div></div>\n"
    "  </div>\n"
    "  <div class='row g-4 mb-4'>\n"
    "    <div class='col-md-7'><div class='card p-4 h-100'>"
    "<h6 class='fw-bold text-secondary mb-3 text-uppercase'>Ansokningar per manad</h6>"
    "<canvas id='monthlyChart' height='100'></canvas></div></div>\n"
    "    <div class='col-md-5'><div class='card p-4 h-100'>"
    "<h6 class='fw-bold text-secondary mb-3 text-uppercase'>B3-bolagsaktivitet</h6>"
    "<canvas id='b3Chart' height='160'></canvas></div></div>\n"
    "  </div>\n"
    "  <div class='card p-4'>\n"
    "    <h6 class='fw-bold text-secondary mb-3 text-uppercase'>Anstallda kandidater</h6>\n"
    "    " + hired_table + "\n"
    "  </div>\n"
    "</div>\n"
    "<script>\n"
    "const monthly=" + json.dumps(monthly_sorted) + ";\n"
    "const b3data=" + json.dumps(dict(list(b3_sorted.items())[:10])) + ";\n"
    "const colors=['#4f8ef7','#f7a24f','#4fcf8e','#f74f8e','#a24ff7','#f7e44f','#4ff7f0','#f76a4f','#8ef74f','#4f4ff7'];\n"
    "new Chart(document.getElementById('monthlyChart'),{"
    "type:'bar',"
    "data:{labels:Object.keys(monthly),datasets:[{label:'Ansokningar',data:Object.values(monthly),backgroundColor:'#4f8ef7',borderRadius:6}]},"
    "options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}"
    "});\n"
    "new Chart(document.getElementById('b3Chart'),{"
    "type:'doughnut',"
    "data:{labels:Object.keys(b3data),datasets:[{data:Object.values(b3data),backgroundColor:colors,borderWidth:2}]},"
    "options:{plugins:{legend:{position:'right',labels:{font:{size:12}}}}}"
    "});\n"
    "</script>\n"
    "</body>\n"
    "</html>\n"
)

outfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
with open(outfile, "w", encoding="utf-8") as f:
    f.write(html)

print("\nKlar! index.html sparad.")
print("Ansokningar : " + str(len(all_apps)))
print("Anstallda   : " + str(len(hired_list)))
print("Time to Hire: " + tth_val + " dagar")
print("Time to Pipe: " + ttp_val + " dagar")
