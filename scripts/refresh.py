#!/usr/bin/env python3
"""Daily refresh for Midas in View.

Runs on GitHub Actions (see .github/workflows/refresh.yml). Updates data.json in place:
spot gold, FX rates, Bank Negara Kijang Emas prices, 52-week range, a daily history
point and the news feed. Any source that fails keeps its previous value, so a bad day
never blanks the page. Standard library only.
"""
import json, re, sys, html, datetime as dt
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data.json"
MYT = dt.timezone(dt.timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (MidasInView daily refresh; GitHub Actions)"}
log = []


def get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url, headers=None):
    return json.loads(get(url, headers).decode("utf-8"))


def now_myt():
    return dt.datetime.now(MYT).replace(microsecond=0)


# ---------------------------------------------------------------- spot gold
def fetch_spot():
    """Spot XAU/USD from gold-api.com; fallback: Yahoo Finance COMEX futures."""
    try:
        j = get_json("https://api.gold-api.com/price/XAU")
        p = float(j["price"])
        at = j.get("updatedAt") or dt.datetime.now(dt.timezone.utc).isoformat()
        return p, at, "gold-api.com (spot XAU/USD)", "https://gold-api.com/"
    except Exception as e:
        log.append(f"gold-api failed: {e}")
    j = get_json("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=5d&interval=1d")
    m = j["chart"]["result"][0]["meta"]
    at = dt.datetime.fromtimestamp(m["regularMarketTime"], dt.timezone.utc).isoformat()
    return float(m["regularMarketPrice"]), at, "Yahoo Finance (COMEX futures GC=F)", "https://finance.yahoo.com/quote/GC=F/"


def fetch_year_closes():
    j = get_json("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=1y&interval=1d")
    r = j["chart"]["result"][0]
    out = []
    for ts, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
        if c:
            out.append((dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat(), float(c)))
    return out


# ---------------------------------------------------------------- FX
def fetch_fx():
    j = get_json("https://open.er-api.com/v6/latest/USD")
    if j.get("result") != "success":
        raise RuntimeError("er-api result not success")
    return j["rates"], j.get("time_last_update_utc", "")


# ---------------------------------------------------------------- Kijang Emas
def fetch_kijang():
    hdr = {"Accept": "application/vnd.BNM.API.v1+json"}
    rows = {}
    today = now_myt().date()
    months = [(today.year, today.month)]
    prev = today.replace(day=1) - dt.timedelta(days=1)
    months.append((prev.year, prev.month))
    for y, m in months:
        try:
            j = get_json(f"https://api.bnm.gov.my/public/kijang-emas/year/{y}/month/{m}", hdr)
            data = j.get("data") or []
            if isinstance(data, dict):
                data = [data]
            for d in data:
                oz = d.get("one_oz") or {}
                if d.get("effective_date") and oz.get("selling"):
                    rows[d["effective_date"]] = {"d": d["effective_date"], "sell": float(oz["selling"]), "buy": float(oz["buying"])}
        except Exception as e:
            log.append(f"BNM {y}-{m} failed: {e}")
    try:
        d = get_json("https://api.bnm.gov.my/public/kijang-emas", hdr)["data"]
        oz = d["one_oz"]
        rows[d["effective_date"]] = {"d": d["effective_date"], "sell": float(oz["selling"]), "buy": float(oz["buying"])}
    except Exception as e:
        log.append(f"BNM latest failed: {e}")
    return sorted(rows.values(), key=lambda r: r["d"], reverse=True)[:5]


# ---------------------------------------------------------------- news
QUERIES = [
    ("Malaysia", 'gold price (Malaysia OR ringgit OR "Bank Negara")'),
    ("US", "gold prices (Fed OR dollar OR yields OR inflation)"),
    ("Hong Kong", '"Hong Kong" gold'),
    ("UAE", "Dubai gold rate"),
    ("Global", '"central banks" gold OR "World Gold Council"'),
]

NOTES = [  # keyword pattern -> general note on how such news tends to affect gold
    (r"\b(fed|fomc|rate hike|rate cut|interest rate|yield|treasur)", {
        "en": "Interest-rate news: higher US rates or yields usually weigh on gold; lower ones tend to support it.",
        "zh": "利率消息：美国利率或收益率上升通常压制金价，下降则往往利好金价。"}),
    (r"\b(dollar|usd|dxy|greenback)", {
        "en": "US dollar news: a stronger dollar usually makes gold cheaper in USD and dearer in other currencies.",
        "zh": "美元消息：美元走强通常压低以美元计的金价，并推高以其他货币计的金价。"}),
    (r"\b(inflation|cpi|pce|prices rose)", {
        "en": "Inflation news: hot inflation can lift gold as a hedge, but may also raise rate-hike odds.",
        "zh": "通胀消息：通胀偏高可提升黄金的保值需求，但也可能增加加息预期。"}),
    (r"(central bank|reserves|world gold council|wgc)", {
        "en": "Central-bank demand is a longer-term support for gold; it rarely moves daily prices on its own.",
        "zh": "央行需求是金价的长期支撑因素，单独很少左右日内价格。"}),
    (r"(ringgit|bank negara|bnm|\bopr\b|malaysia)", {
        "en": "Ringgit news: a stronger ringgit makes gold slightly cheaper in RM, even if USD gold is flat.",
        "zh": "马币消息：即使美元金价不变，马币走强也会使以令吉计的金价略降。"}),
    (r"(dubai|uae|emirat|dirham|aed)", {
        "en": "UAE: the dirham is pegged to the USD, so Dubai gold rates follow spot gold almost one-for-one.",
        "zh": "阿联酋：迪拉姆与美元挂钩，迪拜金价几乎与现货同步。"}),
    (r"(hong kong|\bhk\b|hkex|tael)", {
        "en": "Hong Kong: the HKD is pegged to the USD, so local gold tracks spot; demand from mainland China also matters.",
        "zh": "香港：港元与美元挂钩，本地金价跟随现货；内地需求也有影响。"}),
    (r"(war|conflict|tension|sanction|tariff|geopolit|iran|russia|israel)", {
        "en": "Geopolitical risk: uncertainty often lifts safe-haven demand for gold.",
        "zh": "地缘政治风险：不确定性往往提升黄金的避险需求。"}),
]
DEFAULT_NOTE = {"en": "Check the article for how this affects supply, demand, the dollar or interest rates.",
                "zh": "请查看原文，了解其对供需、美元或利率的影响。"}


def note_for(title):
    t = title.lower()
    for pat, note in NOTES:
        if re.search(pat, t):
            return note
    return DEFAULT_NOTE


def fetch_news(per_region=2):
    items, seen = [], set()
    for region, q in QUERIES:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q + " when:3d", "hl": "en-MY", "gl": "MY", "ceid": "MY:en"})
        try:
            root = ET.fromstring(get(url))
        except Exception as e:
            log.append(f"news {region} failed: {e}")
            continue
        n = 0
        for it in root.iter("item"):
            title = html.unescape(it.findtext("title") or "").strip()
            link = it.findtext("link") or ""
            src = it.find("source")
            source = (src.text if src is not None else "") or ""
            if source and title.endswith(" - " + source):
                title = title[: -len(" - " + source)]
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or not link or key in seen:
                continue
            try:
                pub = dt.datetime.strptime(it.findtext("pubDate"), "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc)
            except Exception:
                continue
            seen.add(key)
            items.append({"region": region, "date": pub.isoformat(), "auto": True,
                          "h": {"en": title, "zh": title}, "i": note_for(title),
                          "s": source or "Google News", "u": link})
            n += 1
            if n >= per_region:
                break
    return items


# ---------------------------------------------------------------- main
def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    now = now_myt()
    today = now.date().isoformat()
    changed = []

    # spot
    try:
        p, at, src, url = fetch_spot()
        last = d["spot"]["usdPerOz"]
        if not (0.85 * last <= p <= 1.15 * last):
            raise RuntimeError(f"spot {p} too far from previous {last}; skipped")
        prior = [h for h in d["history"] if h["d"] < today]
        prev = prior[-1] if prior else None
        d["spot"].update({"usdPerOz": round(p, 2), "at": at, "status": "verified", "source": src, "url": url})
        if prev:
            d["spot"].update({"prevCloseUsdPerOz": prev["v"], "prevSource": f"Previous daily reading ({prev['d']})", "prevUrl": prev.get("u", url)})
        d["history"] = [h for h in d["history"] if h["d"] != today] + [{"d": today, "v": round(p, 2), "s": src, "u": url}]
        cutoff = (now.date() - dt.timedelta(days=400)).isoformat()
        d["history"] = sorted([h for h in d["history"] if h["d"] >= cutoff], key=lambda h: h["d"])
        changed.append(f"spot {p:.2f}")
    except Exception as e:
        log.append(f"spot failed: {e}")

    # 52-week range
    try:
        closes = fetch_year_closes()
        if len(closes) > 150:
            vals = [c for _, c in closes]
            d["week52"] = {"hi": round(max(vals), 2), "lo": round(min(vals), 2),
                           "src": f"Yahoo Finance GC=F daily closes, to {closes[-1][0]}", "url": "https://finance.yahoo.com/quote/GC=F/history/"}
            changed.append("week52")
    except Exception as e:
        log.append(f"week52 failed: {e}")

    # FX
    try:
        rates, stamp = fetch_fx()
        for c in ("MYR", "HKD"):
            r = float(rates[c])
            d["fx"][c].update({"rate": round(r, 4), "status": "verified", "url": "https://www.exchangerate-api.com/",
                               "note": {"en": f"Daily reference rate from ExchangeRate-API ({stamp[:16]}).",
                                        "zh": f"ExchangeRate-API 每日参考汇率（{stamp[:16]}）。"}})
        changed.append(f"MYR {rates['MYR']:.4f}")
    except Exception as e:
        log.append(f"fx failed: {e}")

    # Kijang Emas
    try:
        k = fetch_kijang()
        if k and (not d["kijang"] or k[0]["d"] >= d["kijang"][0]["d"]):
            d["kijang"] = k
            changed.append(f"kijang {k[0]['d']}")
    except Exception as e:
        log.append(f"kijang failed: {e}")

    # news: fresh automatic items; keep any hand-written items from the last 10 days
    try:
        fresh = fetch_news()
        if len(fresh) >= 4:
            keep_after = (now - dt.timedelta(days=10)).isoformat()
            manual = [n for n in d["news"] if not n.get("auto") and n["date"] >= keep_after]
            d["news"] = sorted(fresh + manual, key=lambda n: n["date"], reverse=True)[:14]
            changed.append(f"news {len(fresh)}")
    except Exception as e:
        log.append(f"news failed: {e}")

    d["checkedAt"] = now.isoformat()
    d["lastRefresh"] = {"at": now.isoformat(), "by": "GitHub Actions", "note": "; ".join(changed + log)[:500]}
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("updated:", ", ".join(changed) or "nothing")
    for line in log:
        print("warn:", line)
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())
