import asyncio
import re
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Page, BrowserContext

class GoogleMapsScraper:
    def __init__(self, headless: bool = True, max_results: int = 20, delay_between_actions: float = 1.5):
        self.headless = headless
        self.max_results = max_results
        self.delay = delay_between_actions

    async def _handle_consent(self, page: Page):
        """Dismiss Google's GDPR / cookie consent dialogs if present."""
        try:
            consent_selectors = [
                "button:has-text('Accept all')",
                "button:has-text('I agree')",
                "button[aria-label*='Accept']",
                "form[action*='consent'] button"
            ]
            for selector in consent_selectors:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
        except Exception:
            pass

    async def _scroll_feed(self, page: Page) -> List[str]:
        """Scrolls the left-hand search results panel to collect listing URLs."""
        feed_selector = 'div[role="feed"]'
        
        try:
            await page.wait_for_selector(feed_selector, timeout=12000)
        except Exception:
            print("Could not find results feed. Searching might have returned 0 results or a single direct result.")
            # Check if it redirected directly to a place
            if "/maps/place/" in page.url:
                return [page.url]
            return []

        place_links = []
        seen_links = set()
        scroll_attempts = 0
        max_scroll_attempts = 30

        print("Scrolling results panel to collect business links...")
        while len(seen_links) < self.max_results and scroll_attempts < max_scroll_attempts:
            # Find all links matching Google Maps place URL pattern
            anchors = await page.locator(f'{feed_selector} a[href*="/maps/place/"]').all()
            for a in anchors:
                try:
                    href = await a.get_attribute("href")
                    if href and href not in seen_links:
                        seen_links.add(href)
                        place_links.append(href)
                        if len(seen_links) >= self.max_results:
                            break
                except Exception:
                    continue

            # Check if reached end of list
            end_indicator = page.locator("text=\"You've reached the end of the list.\"")
            if await end_indicator.is_visible():
                print("Reached end of Google Maps results.")
                break

            # Scroll down the feed container
            await page.locator(feed_selector).evaluate("el => el.scrollBy(0, 1000)")
            await page.wait_for_timeout(1500)
            scroll_attempts += 1

        print(f"Collected {len(place_links)} place URLs.")
        return place_links[:self.max_results]

    async def _extract_place_details(self, page: Page, url: str) -> Dict[str, str]:
        """Navigates to a specific place URL and extracts detailed contact & business info."""
        data = {
            "name": "N/A",
            "category": "N/A",
            "phone": "N/A",
            "website": "N/A",
            "address": "N/A",
            "rating": "N/A",
            "review_count": "N/A",
            "maps_url": url,
            "latitude": "",
            "longitude": ""
        }

        # Extract coordinates from URL if present (e.g., @30.2672,-97.7431,17z)
        coord_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if coord_match:
            data["latitude"] = coord_match.group(1)
            data["longitude"] = coord_match.group(2)

        # Retry logic: attempt up to 2 times in case of transient network/throttle timeout
        for attempt in range(2):
            try:
                await page.goto(url, timeout=25000, wait_until="commit")
                # Wait for title to appear
                try:
                    await page.wait_for_selector("h1", timeout=10000)
                except Exception:
                    await page.wait_for_timeout(2000)

                # Business Name
                if await page.locator("h1").count() > 0:
                    data["name"] = (await page.locator("h1").first.inner_text()).strip()

                # If name extracted successfully, break retry loop
                if data["name"] and data["name"] != "N/A":
                    break
            except Exception as e:
                if attempt == 0:
                    # Brief cooldown before retry
                    await page.wait_for_timeout(2500)
                    continue
                else:
                    print(f"Error scraping details for {url} (after retry): {e}")
                    return data

        try:
            # Category
            category_selectors = [
                "button[jsaction*='pane.rating.category']",
                "button.DkEaL",
                "span.fontBodyMedium button",
                "div.fontBodyMedium button",
                "button[aria-label*='category']"
            ]
            for c_sel in category_selectors:
                cat_loc = page.locator(c_sel).first
                if await cat_loc.count() > 0:
                    cat_text = await cat_loc.inner_text()
                    if cat_text and len(cat_text.strip()) > 1:
                        data["category"] = cat_text.strip()
                        break

            # Phone Number
            phone_loc = page.locator("button[data-tooltip*='phone'], button[data-item-id*='phone:']").first
            if await phone_loc.count() > 0:
                phone_raw = await phone_loc.inner_text()
                # Remove map icon glyphs and excess whitespace
                clean_phone = re.sub(r'[\ue000-\uf8ff\r\n]+', ' ', phone_raw).strip()
                data["phone"] = clean_phone

            # Website
            website_loc = page.locator("a[data-tooltip*='website'], a[data-item-id='authority']").first
            if await website_loc.count() > 0:
                website_href = await website_loc.get_attribute("href")
                if website_href:
                    data["website"] = website_href.strip()

            # Address
            address_loc = page.locator("button[data-tooltip*='address'], button[data-item-id='address']").first
            if await address_loc.count() > 0:
                addr_raw = await address_loc.inner_text()
                clean_addr = re.sub(r'[\ue000-\uf8ff\r\n]+', ' ', addr_raw).strip()
                data["address"] = clean_addr

            # Rating
            rating_loc = page.locator("div.F7nice span[aria-hidden='true'], div.fontDisplayLarge").first
            if await rating_loc.count() > 0:
                data["rating"] = (await rating_loc.inner_text()).strip()

            # Review Count
            review_loc = page.locator("div.F7nice span:has-text('(')").first
            if await review_loc.count() > 0:
                rev_text = await review_loc.inner_text()
                # Clean up parentheses e.g. "(145)" -> "145"
                rev_clean = re.sub(r'[^\d]', '', rev_text)
                if rev_clean:
                    data["review_count"] = rev_clean

        except Exception as e:
            print(f"Error scraping details for {url}: {e}")

        return data

    async def scrape(self, search_query: str) -> List[Dict[str, str]]:
        """Executes full search and returns basic lead records."""
        leads = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US"
            )
            page = await context.new_page()

            search_url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            print(f"Navigating to Google Maps: {search_url}")
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            await self._handle_consent(page)

            # Step 1: Collect Place URLs from left panel
            place_urls = await self._scroll_feed(page)

            # Step 2: Extract Details from each place
            for idx, url in enumerate(place_urls):
                print(f"[{idx + 1}/{len(place_urls)}] Extracting details...")
                detail = await self._extract_place_details(page, url)
                if detail["name"] and detail["name"] != "N/A":
                    leads.append(detail)
                    print(f"   ✓ {detail['name']} | Phone: {detail['phone']} | Web: {detail['website']}")
                await page.wait_for_timeout(int(self.delay * 1000))

            await browser.close()

        return leads
