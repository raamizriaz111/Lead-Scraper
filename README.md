# 🚀 Google Maps Leads & Email Scraper (2-Step Pipeline)

A complete automated pipeline for B2B lead generation:
1. **Step 1: Google Maps Scraper** — Navigates Google Maps, scrolls listings, and extracts business names, phone numbers, categories, ratings, addresses, and website URLs.
2. **Step 2: Website Email & Social Enricher** — Asynchronously crawls each extracted website (homepage, `/contact`, `/about`, `/team`), extracting **emails** and **social media profiles** (LinkedIn, Facebook, Instagram, Twitter, YouTube).

---

## 📁 Project Structure

```
gmaps-lead-scraper/
├── maps_scraper.py      # Step 1: Playwright automation for Google Maps
├── enricher.py          # Step 2: Async HTTP crawler for emails & social links
├── pipeline.py          # Orchestrator running Step 1 -> Step 2 -> CSV export
├── requirements.txt     # Python dependencies
└── README.md            # Documentation
```

---

## 🛠️ Setup Instructions

### 1. Install Dependencies
```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

---

## 🏃 Running the Scraper

### Quick Run
```bash
python3 pipeline.py --query "dentists in Austin TX" --limit 10
```

### Options & Arguments
| Flag | Default | Description |
| :--- | :--- | :--- |
| `--query` | `"dentists in Austin TX"` | Google Maps search query |
| `--limit` | `10` | Maximum number of listings to extract |
| `--headless` | `False` | Run browser in background without UI window |
| `--output` | `leads_enriched.csv` | Output filename for exported CSV |

### Examples:
```bash
# Scrape real estate agents in Miami, run in headless mode, extract 25 leads
python3 pipeline.py --query "real estate agents in Miami FL" --limit 25 --headless --output miami_agents.csv

# Scrape restaurants in Chicago
python3 pipeline.py --query "italian restaurants in Chicago IL" --limit 50 --output chicago_restaurants.csv
```

---

## 📊 Output Fields in CSV
Each exported lead record includes:
* `name` — Business Name
* `category` — Industry / Category
* `phone` — Contact Phone Number
* `primary_email` — Main discovered email address
* `website` — Company website URL
* `all_emails` — All comma-separated emails discovered on the site
* `linkedin` — Company or personal LinkedIn profile URL
* `facebook` — Facebook page URL
* `instagram` — Instagram profile URL
* `twitter` — Twitter / X profile URL
* `rating` — Average star rating (e.g. 4.9)
* `review_count` — Total number of Google reviews
* `address` — Physical street address
* `maps_url` — Direct Google Maps link

---

## 🛡️ Scaling & Anti-Ban Tips

* **Grid/Zip Search:** Google Maps limits results to ~120 per query. For an entire city or state, loop through a list of zip codes (e.g., `"plumbers in 78701"`, `"plumbers in 78702"`).
* **Proxies:** When running queries in bulk (>100 leads/day), configure residential proxies inside Playwright context in `maps_scraper.py`:
  ```python
  context = await browser.new_context(
      proxy={"server": "http://proxy-host:port", "username": "user", "password": "pwd"}
  )
  ```
* **Polite Crawling:** The website enricher in `enricher.py` uses concurrency limits (`asyncio.Semaphore(5)`) and 10s timeouts to prevent overloading target websites.
