#!/usr/bin/env python3
"""Send the daily web-push notification to every saved subscription.

Needs the repository secret VAPID_PRIVATE_KEY. Subscriptions live in push/subscriptions.json
(the page gives each device's code; they are useless without the private key).
Expired subscriptions (404/410) are removed.
"""
import json, os, sys
from pathlib import Path
from pywebpush import webpush, WebPushException

ROOT = Path(__file__).resolve().parent.parent
SUBS = ROOT / "push" / "subscriptions.json"
key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
if not key:
    print("VAPID_PRIVATE_KEY not set; skipping notifications"); sys.exit(0)

d = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
store = json.loads(SUBS.read_text(encoding="utf-8"))
subs = store.get("subscriptions", [])
if not subs:
    print("No subscriptions"); sys.exit(0)

sp, prev = d["spot"]["usdPerOz"], d["spot"].get("prevCloseUsdPerOz") or d["spot"]["usdPerOz"]
myr = d["fx"]["MYR"]["rate"]
g24 = sp / 31.1035 * myr
chg = (sp / prev - 1) * 100
arrow = "▲" if chg > 0.05 else "▼" if chg < -0.05 else "■"
trend = {"up": "rising", "down": "falling", "mixed": "mixed"}.get((d.get("model") or {}).get("trend"), "")
body = f"24K RM {g24:,.2f}/g · US${sp:,.0f}/oz {arrow} {chg:+.2f}%"
if trend:
    body += f" · trend {trend}"
payload = json.dumps({"title": "Midas in View · daily update", "body": body,
                      "url": "https://efronong.github.io/midas-in-view/"})

keep = []
for s in subs:
    try:
        webpush(subscription_info=s, data=payload, vapid_private_key=key,
                vapid_claims={"sub": "https://github.com/efronong/midas-in-view"}, ttl=43200)
        keep.append(s); print("sent")
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        print("failed", code, str(e)[:120])
        if code not in (404, 410):
            keep.append(s)
if len(keep) != len(subs):
    store["subscriptions"] = keep
    SUBS.write_text(json.dumps(store, indent=1) + "\n", encoding="utf-8")
