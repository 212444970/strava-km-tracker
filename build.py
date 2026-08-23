"""
Static site builder for Netlify.

Reads STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN from env,
fetches all rides, and writes public/index.html.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
RIDE_TYPES = {"Ride", "VirtualRide", "EBikeRide", "GravelRide", "MountainBikeRide"}


# ---------------------------------------------------------------------------
# Strava helpers
# ---------------------------------------------------------------------------

def get_access_token():
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_all_rides(access_token):
    rides = []
    page = 1
    while True:
        resp = requests.get(
            STRAVA_ACTIVITIES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"per_page": 200, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        for a in batch:
            if a.get("sport_type") in RIDE_TYPES and a.get("distance", 0) > 0:
                rides.append({
                    "name": a["name"],
                    "date": a["start_date_local"][:10],
                    "km": round(a["distance"] / 1000, 2),
                    "type": a["sport_type"],
                    "moving_time": a["moving_time"],
                    "elevation": round(a.get("total_elevation_gain", 0)),
                })
        if len(batch) < 200:
            break
        page += 1
    return sorted(rides, key=lambda x: x["date"], reverse=True)


def compute_stats(rides):
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    def parse(d):
        return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)

    return {
        "total": round(sum(r["km"] for r in rides), 1),
        "this_year": round(sum(r["km"] for r in rides if parse(r["date"]) >= year_start), 1),
        "this_month": round(sum(r["km"] for r in rides if parse(r["date"]) >= month_start), 1),
        "this_week": round(sum(r["km"] for r in rides if parse(r["date"]) >= week_start), 1),
        "ride_count": len(rides),
    }


def format_duration(seconds):
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def compute_monthly(rides):
    from collections import defaultdict
    monthly = defaultdict(float)
    for r in rides:
        monthly[r["date"][:7]] += r["km"]
    sorted_items = sorted(monthly.items())
    cal_max = {}
    for ym, km in sorted_items:
        m = ym[5:7]
        if m not in cal_max or km > cal_max[m][1]:
            cal_max[m] = (ym, km)
    record_yms = {v[0] for v in cal_max.values()}
    top_20 = sorted(monthly.items(), key=lambda x: x[1], reverse=True)[:20]
    return sorted_items, top_20, record_yms


def monthly_chart_html(monthly_items, record_yms):
    MONTHS_CS = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"]
    data_js = json.dumps([
        {"ym": ym, "km": round(km, 1), "rec": ym in record_yms}
        for ym, km in monthly_items
    ])
    months_js = json.dumps(MONTHS_CS)
    return """
  <section class="chart-section">
    <h2>Km za měsíc</h2>
    <div class="chart-wrap">
      <canvas id="mc"></canvas>
      <div id="mc-tip" class="chart-tip"></div>
    </div>
    <script>
    (function() {
      var MONTHS = """ + months_js + """;
      var data = """ + data_js + """;
      var canvas = document.getElementById('mc');
      var tip = document.getElementById('mc-tip');
      var PAD = {l: 44, r: 8, t: 14, b: 28};
      var H = 220;

      function draw() {
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        var cw = W - PAD.l - PAD.r;
        var ch = H - PAD.t - PAD.b;
        var n = data.length;
        var maxKm = Math.max.apply(null, data.map(function(d) { return d.km; }));
        var slot = cw / n;
        var bw = Math.max(1, slot * 0.82);

        for (var i = 0; i <= 4; i++) {
          var y = PAD.t + ch - ch * i / 4;
          ctx.strokeStyle = '#2a2a2a';
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(PAD.l + cw, y); ctx.stroke();
          ctx.fillStyle = '#555';
          ctx.font = '10px system-ui';
          ctx.textAlign = 'right';
          ctx.fillText(Math.round(maxKm * i / 4), PAD.l - 4, y + 3.5);
        }

        data.forEach(function(d, i) {
          var x = PAD.l + i * slot + (slot - bw) / 2;
          var bh = Math.max(1, ch * d.km / maxKm);
          ctx.fillStyle = d.rec ? '#fc4c02' : '#3a7bc8';
          ctx.fillRect(x, PAD.t + ch - bh, bw, bh);
        });

        var lastYr = '';
        ctx.fillStyle = '#555';
        ctx.font = '10px system-ui';
        ctx.textAlign = 'center';
        data.forEach(function(d, i) {
          var yr = d.ym.slice(0, 4);
          if ((d.ym.slice(5) === '01' || i === 0) && yr !== lastYr) {
            lastYr = yr;
            ctx.fillText(yr, PAD.l + i * slot + slot / 2, H - PAD.b + 11);
          }
        });
      }

      draw();
      window.addEventListener('resize', draw);

      canvas.addEventListener('mousemove', function(e) {
        var rect = canvas.getBoundingClientRect();
        var W = parseFloat(canvas.style.width);
        var cw = W - PAD.l - PAD.r;
        var n = data.length;
        var i = Math.floor((e.clientX - rect.left - PAD.l) / (cw / n));
        if (i >= 0 && i < n) {
          var d = data[i];
          var mn = MONTHS[parseInt(d.ym.slice(5, 7)) - 1];
          tip.textContent = mn + ' ' + d.ym.slice(0, 4) + ': ' + d.km + ' km' + (d.rec ? ' ★' : '');
          tip.style.left = Math.min(PAD.l + i * (cw / n), W - 160) + 'px';
          tip.style.top = '4px';
          tip.style.opacity = '1';
        } else {
          tip.style.opacity = '0';
        }
      });

      canvas.addEventListener('mouseleave', function() { tip.style.opacity = '0'; });
    })();
    </script>
  </section>"""


def top_months_html(top_20):
    MONTHS_CS = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"]
    rows = ""
    for i, (ym, km) in enumerate(top_20, 1):
        m = MONTHS_CS[int(ym[5:7]) - 1]
        rows += f"      <tr><td class='num'>{i}.</td><td>{m} {ym[:4]}</td><td class='num'>{round(km, 1)} km</td></tr>\n"
    return f"""
  <section class="chart-section">
    <h2>Top 20 měsíců</h2>
    <table class="top-months">
      <thead><tr><th>#</th><th>Měsíc</th><th>km</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>
  </section>"""


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def ride_rows(rides):
    rows = []
    for r in rides[:20]:
        dur = format_duration(r["moving_time"])
        rows.append(
            f"<tr>"
            f'<td class="date">{r["date"]}</td>'
            f"<td>{r['name']}</td>"
            f'<td class="type">{r["type"]}</td>'
            f'<td class="num">{r["km"]} km</td>'
            f'<td class="num">{dur}</td>'
            f'<td class="num">{r["elevation"]} m</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def render(stats, rides):
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    monthly_items, top_20, record_yms = compute_monthly(rides)
    chart = monthly_chart_html(monthly_items, record_yms)
    top = top_months_html(top_20)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Bike KM Tracker</title>
  <link rel="stylesheet" href="/style.css" />
</head>
<body>
  <header>
    <h1>🚴 Bike KM Tracker</h1>
    <span class="built-at">Updated {built_at}</span>
  </header>

  <section class="stats-grid">
    <div class="stat-card accent">
      <span class="stat-label">Total km</span>
      <span class="stat-value">{stats['total']}</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">This year</span>
      <span class="stat-value">{stats['this_year']}</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">This month</span>
      <span class="stat-value">{stats['this_month']}</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">This week</span>
      <span class="stat-value">{stats['this_week']}</span>
    </div>
    <div class="stat-card muted">
      <span class="stat-label">Total rides</span>
      <span class="stat-value">{stats['ride_count']}</span>
    </div>
  </section>

  <section class="rides-section">
    <h2>Recent rides</h2>
    <table>
      <thead>
        <tr>
          <th>Date</th><th>Name</th><th>Type</th>
          <th>Distance</th><th>Duration</th><th>Elevation</th>
        </tr>
      </thead>
      <tbody>
        {ride_rows(rides)}
      </tbody>
    </table>
  </section>
{chart}
{top}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    required = ["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    print("Fetching Strava access token...")
    token = get_access_token()

    print("Fetching rides...")
    rides = fetch_all_rides(token)
    print(f"  Found {len(rides)} rides.")

    stats = compute_stats(rides)
    html = render(stats, rides)

    out_dir = Path("public")
    out_dir.mkdir(exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # Copy static CSS so public/ is self-contained
    css_src = Path(__file__).parent / "static" / "style.css"
    if css_src.exists():
        import shutil
        shutil.copy(css_src, out_dir / "style.css")

    print(f"Built public/index.html  ({stats['total']} km total)")
