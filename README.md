# Midas in View

Gold prices per gram in MYR, USD, HKD and AED for buyers in Malaysia, with making-fee comparisons and market news. English / 中文, light / dark mode.

**Live site:** https://efronong.github.io/midas-in-view/

## How it updates
- `.github/workflows/refresh.yml` runs every day at 08:32 Malaysia time (and on demand from the Actions tab → *Daily data refresh* → *Run workflow*).
- It runs `scripts/refresh.py`, which updates `data.json`: spot gold (gold-api.com, fallback Yahoo Finance GC=F), USD/MYR and USD/HKD (ExchangeRate-API), Bank Negara Kijang Emas prices (BNM Open API), the 52-week range and news headlines (Google News RSS). Any source that fails keeps its previous value.
- The ↻ button on the page reloads `data.json` and pulls the latest live spot price and exchange rates in the browser.

Not financial advice.
