import re
import urllib.parse
from typing import Dict, List, Set, Optional
import httpx
from bs4 import BeautifulSoup

# Regex patterns
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)

# Ignored extensions & common false positives in emails
IGNORE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css', '.js')
IGNORE_DOMAINS = ('sentry.io', 'wixpress.com', 'example.com', 'schema.org', 'domain.com', 'email.com', 'w3.org')

# Social media domains to detect
SOCIAL_DOMAINS = {
    "linkedin": re.compile(r'https?://(www\.)?linkedin\.com/(company|in)/[a-zA-Z0-9-_%]+', re.IGNORECASE),
    "facebook": re.compile(r'https?://(www\.)?facebook\.com/[a-zA-Z0-9._-]+', re.IGNORECASE),
    "instagram": re.compile(r'https?://(www\.)?instagram\.com/[a-zA-Z0-9._-]+', re.IGNORECASE),
    "twitter": re.compile(r'https?://(www\.)?(twitter|x)\.com/[a-zA-Z0-9_]+', re.IGNORECASE),
    "youtube": re.compile(r'https?://(www\.)?youtube\.com/(c/|channel/|user/|@)[a-zA-Z0-9-_]+', re.IGNORECASE)
}

CONTACT_PAGE_KEYWORDS = ["contact", "about", "team", "staff", "connect", "reach", "location"]

class WebsiteEnricher:
    def __init__(self, timeout: float = 10.0, max_pages_per_site: int = 3):
        self.timeout = timeout
        self.max_pages_per_site = max_pages_per_site
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _clean_email(self, email: str) -> Optional[str]:
        email = email.strip().lower()
        if any(email.endswith(ext) for ext in IGNORE_EXTENSIONS):
            return None
        if any(dom in email for dom in IGNORE_DOMAINS):
            return None
        if len(email) > 60 or len(email) < 6:
            return None
        return email

    def _find_candidate_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Finds internal pages likely containing contact information (e.g. /contact, /about)."""
        candidate_urls = []
        base_domain = urllib.parse.urlparse(base_url).netloc

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            anchor_text = a_tag.get_text(separator=" ", strip=True).lower()
            
            # Combine href and anchor text to check for keywords
            combined_text = f"{href.lower()} {anchor_text}"
            
            if any(keyword in combined_text for keyword in CONTACT_PAGE_KEYWORDS):
                full_url = urllib.parse.urljoin(base_url, href)
                parsed = urllib.parse.urlparse(full_url)
                
                # Ensure it belongs to the same domain and is HTTP/HTTPS
                if parsed.netloc == base_domain and parsed.scheme in ('http', 'https'):
                    # Strip fragments and query parameters
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if clean_url not in candidate_urls and clean_url != base_url:
                        candidate_urls.append(clean_url)
                        if len(candidate_urls) >= self.max_pages_per_site - 1:
                            break

        return candidate_urls

    def _extract_from_html(self, html: str, emails_set: Set[str], socials_dict: Dict[str, str]):
        soup = BeautifulSoup(html, 'html.parser')

        # 1. Look for mailto: links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            if href.lower().startswith('mailto:'):
                raw_email = href.split(':', 1)[1].split('?')[0]
                cleaned = self._clean_email(raw_email)
                if cleaned:
                    emails_set.add(cleaned)

            # 2. Look for social links in <a> tags
            for platform, pattern in SOCIAL_DOMAINS.items():
                if platform not in socials_dict or not socials_dict[platform]:
                    match = pattern.search(href)
                    if match:
                        socials_dict[platform] = match.group(0)

        # 3. Search raw text with Regex for emails
        text = soup.get_text(separator=" ")
        matches = EMAIL_REGEX.findall(text)
        for match in matches:
            cleaned = self._clean_email(match)
            if cleaned:
                emails_set.add(cleaned)

    async def enrich(self, client: httpx.AsyncClient, website_url: str) -> Dict[str, any]:
        """Visits homepage and contact pages to extract emails and social media accounts."""
        result = {
            "emails": [],
            "primary_email": "",
            "linkedin": "",
            "facebook": "",
            "instagram": "",
            "twitter": "",
            "youtube": ""
        }

        if not website_url or website_url == "N/A" or not website_url.startswith("http"):
            return result

        emails_set: Set[str] = set()
        socials_dict: Dict[str, str] = {}

        pages_to_crawl = [website_url]

        try:
            # 1. Fetch Homepage
            resp = await client.get(website_url, headers=self.headers, timeout=self.timeout, follow_redirects=True)
            if resp.status_code == 200:
                self._extract_from_html(resp.text, emails_set, socials_dict)
                
                # Find additional contact/about pages
                soup = BeautifulSoup(resp.text, 'html.parser')
                candidate_links = self._find_candidate_links(soup, str(resp.url))
                pages_to_crawl.extend(candidate_links)
        except Exception:
            pass

        # 2. Fetch contact/about pages
        for page_url in pages_to_crawl[1:]:
            try:
                resp = await client.get(page_url, headers=self.headers, timeout=self.timeout, follow_redirects=True)
                if resp.status_code == 200:
                    self._extract_from_html(resp.text, emails_set, socials_dict)
            except Exception:
                continue

        # Format output
        email_list = list(emails_set)
        result["emails"] = email_list
        result["primary_email"] = email_list[0] if email_list else ""
        for platform in SOCIAL_DOMAINS.keys():
            result[platform] = socials_dict.get(platform, "")

        return result
