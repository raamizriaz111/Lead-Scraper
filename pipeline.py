import asyncio
import argparse
import os
import pandas as pd
import httpx
from maps_scraper import GoogleMapsScraper
from enricher import WebsiteEnricher

async def enrich_lead(enricher: WebsiteEnricher, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, lead: dict) -> dict:
    website = lead.get("website", "")
    if not website or website == "N/A" or not website.startswith("http"):
        lead["email"] = ""
        lead["linkedin"] = ""
        lead["facebook"] = ""
        lead["instagram"] = ""
        lead["twitter"] = ""
        return lead

    async with semaphore:
        print(f"   [Enriching] Crawling website for {lead['name']}: {website}...")
        enriched = await enricher.enrich(client, website)
        
        # Keep only ONE email field. If there are multiple emails, put the 2nd below the 1st
        emails = enriched.get("emails", [])
        lead["email"] = "\n".join(emails) if emails else ""

        lead["linkedin"] = enriched.get("linkedin", "")
        lead["facebook"] = enriched.get("facebook", "")
        lead["instagram"] = enriched.get("instagram", "")
        lead["twitter"] = enriched.get("twitter", "")
        
        found_summary = []
        if lead["email"]:
            primary = emails[0] if emails else ""
            found_summary.append(f"Email: {primary}" + (f" (+{len(emails)-1} more)" if len(emails) > 1 else ""))
        if lead["linkedin"]:
            found_summary.append("LinkedIn")
        if lead["facebook"]:
            found_summary.append("Facebook")
        if lead["instagram"]:
            found_summary.append("Instagram")

        if found_summary:
            print(f"   ✓ Found for {lead['name']}: {', '.join(found_summary)}")
        else:
            print(f"   - No contact emails/socials detected on {website}")
            
        return lead

async def run_pipeline(query: str, max_results: int = 10, headless: bool = True, output_path: str = "leads_enriched.csv"):
    print("=" * 60)
    print(f"Starting 2-Step Lead Generation Pipeline")
    print(f"Search Query : {query}")
    print(f"Max Results  : {max_results}")
    print(f"Headless Mode: {headless}")
    print("=" * 60)

    # -------------------------------------------------------------
    # Step 1: Google Maps Scraping
    # -------------------------------------------------------------
    print("\n--- [STEP 1/2] Scraping Google Maps ---")
    scraper = GoogleMapsScraper(headless=headless, max_results=max_results)
    raw_leads = await scraper.scrape(query)

    if not raw_leads:
        print("No leads were found or extracted. Please check your query or network connection.")
        return

    print(f"\nStep 1 Complete: Extracted {len(raw_leads)} business listings from Google Maps.")

    # -------------------------------------------------------------
    # Step 2: Website Email & Social Enrichment
    # -------------------------------------------------------------
    print("\n--- [STEP 2/2] Enriching Websites (Extracting Emails & Socials) ---")
    enricher = WebsiteEnricher()
    semaphore = asyncio.Semaphore(5)  # Limit concurrent website requests

    async with httpx.AsyncClient(timeout=12.0, verify=False) as client:
        tasks = [enrich_lead(enricher, client, semaphore, lead) for lead in raw_leads]
        enriched_leads = await asyncio.gather(*tasks)

    # -------------------------------------------------------------
    # Step 3: Export to CSV / Pandas
    # -------------------------------------------------------------
    df = pd.DataFrame(enriched_leads)

    # Reorder columns for clean, single-email display
    preferred_order = [
        "name", "category", "phone", "email", "website",
        "linkedin", "facebook", "instagram", "twitter",
        "rating", "review_count", "address", "maps_url"
    ]
    existing_cols = [c for c in preferred_order if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in existing_cols]
    df = df[existing_cols + remaining_cols]

    df.to_csv(output_path, index=False)
    print("\n" + "=" * 60)
    print(f"✓ Pipeline Finished Successfully!")
    print(f"Total Leads Saved: {len(df)}")
    print(f"Output File       : {os.path.abspath(output_path)}")
    print("=" * 60)

    # Display preview summary
    emails_found_count = len(df[df["email"] != ""])
    websites_found_count = len(df[df["website"] != "N/A"])
    print(f"\nSummary Metrics:")
    print(f"- Total Listings Extracted: {len(df)}")
    print(f"- Listings with Websites  : {websites_found_count}")
    print(f"- Listings with Emails    : {emails_found_count} ({emails_found_count/len(df)*100:.1f}%)")

if __name__ == "__main__":
    desktop_dir = os.path.expanduser("~/Desktop")
    default_output_file = os.path.join(desktop_dir, "leads_enriched.csv")

    parser = argparse.ArgumentParser(description="2-Step Google Maps + Website Email Scraper")
    parser.add_argument("--query", type=str, default="dentists in Austin TX", help="Search query for Google Maps")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of leads to extract")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    parser.add_argument("--output", type=str, default="leads_enriched.csv", help="Output CSV filename (saved directly to Desktop)")

    args = parser.parse_args()

    # Always ensure the output is saved directly to the user's Desktop
    if not os.path.isabs(args.output) and not args.output.startswith("~"):
        final_output_path = os.path.join(desktop_dir, args.output)
    else:
        final_output_path = os.path.expanduser(args.output)

    asyncio.run(run_pipeline(
        query=args.query,
        max_results=args.limit,
        headless=args.headless,
        output_path=final_output_path
    ))
