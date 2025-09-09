#!/usr/bin/env python3
"""
scrape_reviews.py

Usage:
    python scrape_reviews.py --company zoho-crm --start 2024-01-01 --end 2024-06-30 --source g2

Notes:
- company should match the product slug used by the site (e.g. "zoho-crm" for G2 URL
  https://www.g2.com/products/zoho-crm/reviews). If unsure, check the product page URL manually.
- This script uses Playwright to load pages (handles JS-rendered content).
- Make sure to run: pip install -r requirements.txt
  and then: playwright install
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from dateutil import parser as dateparser
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeoutError

# -----------------------
# Helpers
# -----------------------
def parse_date_safe(date_str: str) -> Optional[datetime]:
    try:
        return dateparser.parse(date_str, dayfirst=False)
    except Exception:
        return None

def within_range(dt: datetime, start: datetime, end: datetime) -> bool:
    return start <= dt <= end

def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

# -----------------------
# Generic extraction strategy
# -----------------------
# Because HTML structures change frequently across sites, the code below tries a robust
# DOM-scraping approach:
#  - find elements that look like "review cards"
#  - from each, try several selectors to extract title, body, date, rating, reviewer
#
# You may need to tweak CSS selectors for particular product pages in the future.

async def extract_reviews_from_dom(page: Page) -> List[Dict]:
    """Run in-page JS to find likely review nodes and extract fields robustly."""
    script = """
    () => {
        const candidates = [];
        // A broad query to find anything that looks like a review card
        const nodes = Array.from(document.querySelectorAll('[class*="review"], [data-testid*="review"], [aria-label*="review"], article, div'));
        for (const n of nodes) {
            // we only want nodes that contain some review-like text and a date-like token
            const txt = n.innerText || "";
            if (txt.length < 50) continue;  // skip tiny nodes
            // heuristic: presence of 'review' words, star, out of 5, or 'posted' etc
            const low = txt.toLowerCase();
            if (!(low.includes("review") || low.includes("stars") || low.match(/\\b\\d{4,4}-\\d{2}-\\d{2}\\b/) || low.match(/\\b\\d{1,2}\\s+(days|months|years)\\b/))) continue;
            candidates.push(n);
        }
        // Map candidate nodes to extracted fields
        const results = [];
        const seen = new Set();
        for (const c of candidates) {
            let title = "";
            let body = "";
            let date = "";
            let rating = "";
            let reviewer = "";

            // title heuristics
            const h = c.querySelector('h1, h2, h3, .review-title, [class*="title"]');
            if (h) title = h.innerText.trim();

            // body heuristics
            const bodyNode = c.querySelector('.review-text, .review-body, [class*="comment"], [class*="content"], p');
            if (bodyNode) body = bodyNode.innerText.trim();
            else {
                // fallback: full text minus first line
                const all = c.innerText.trim().split('\\n').map(s=>s.trim()).filter(Boolean);
                if (all.length >= 2) {
                    body = all.slice(1).join(" ");
                    if (!title) title = all[0];
                } else {
                    body = c.innerText.trim();
                }
            }

            // date heuristics: look for time elements or date-like text
            const t = c.querySelector('time') || c.querySelector('[class*="date"], [class*="posted"]');
            if (t) date = t.getAttribute('datetime') || t.innerText.trim();

            // rating heuristics: look for stars or aria-labels
            const r = c.querySelector('[aria-label*="star"], [class*="rating"], [class*="stars"]');
            if (r) rating = r.getAttribute('aria-label') || r.innerText.trim();

            // reviewer heuristics
            const rev = c.querySelector('[class*="author"], [class*="user"], [class*="reviewer"]');
            if (rev) reviewer = rev.innerText.trim();

            // unique id for deduplication
            const key = (title + '|' + body.slice(0,80)).slice(0,200);
            if (seen.has(key)) continue;
            seen.add(key);

            results.push({
                'title': title,
                'description': body,
                'date': date,
                'rating': rating,
                'reviewer': reviewer
            });
        }
        return results;
    }
    """
    try:
        extracted = await page.evaluate(script)
        return extracted or []
    except Exception as e:
        print("DOM extraction error:", e)
        return []

# -----------------------
# Site-specific flows (uses same extraction but site navigation/pagination differs)
# -----------------------

async def scroll_and_collect(page: Page, max_scrolls: int = 40, wait_ms: int = 800) -> List[Dict]:
    """
    Repeatedly scrolls the page to load more reviews (useful for infinite scroll or lazy load),
    and extracts reviews from DOM after each scroll. Stops early if no new reviews appear.
    """
    collected = []
    seen_keys = set()
    last_len = 0

    for i in range(max_scrolls):
        # extract current DOM reviews
        found = await extract_reviews_from_dom(page)
        new_count = 0
        for r in found:
            key = (r.get('title','') + '|' + (r.get('description','') or "")[:120])
            if key not in seen_keys:
                collected.append(r)
                seen_keys.add(key)
                new_count += 1

        # attempt to click "Load more" buttons if present
        try:
            load_more = await page.query_selector('button:has-text("Load more"), button:has-text("Load More"), a:has-text("Next"), a:has-text("next")')
            if load_more:
                try:
                    await load_more.click()
                    await page.wait_for_timeout(wait_ms)
                except Exception:
                    # might be not clickable; fallback to scroll
                    await page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
                    await page.wait_for_timeout(wait_ms)
            else:
                # no button found: scroll
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
                await page.wait_for_timeout(wait_ms)
        except PWTimeoutError:
            await page.wait_for_timeout(wait_ms)

        if len(collected) == last_len and new_count == 0:
            # no progress this iteration -> stop
            break
        last_len = len(collected)

    return collected

async def scrape_g2(page: Page, company_slug: str, start: datetime, end: datetime) -> List[Dict]:
    url = f"https://www.g2.com/products/{company_slug}/reviews"
    print("Opening G2:", url)
    try:
        await page.goto(url, timeout=30000)
    except Exception as e:
        raise RuntimeError(f"Could not open G2 page: {e}")

    all_reviews = await scroll_and_collect(page)

    # parse/normalize dates, filter by date range
    normalized = []
    for r in all_reviews:
        # try to find date in r['date'] or within description
        date_candidate = r.get('date') or ""
        if not date_candidate:
            # try to find a date token in description
            # leave as empty for now
            pass
        dt = parse_date_safe(date_candidate) or parse_date_safe(r.get('description','')[:50])
        if dt is None:
            # if we cannot parse date, keep the review but mark date as unknown
            r_parsed_date = None
        else:
            r_parsed_date = dt

        if r_parsed_date is None or within_range(r_parsed_date, start, end):
            # include if date unknown (optionally) or within range
            # For stricter behavior, skip unknown-date reviews:
            # if r_parsed_date is None: continue
            r_copy = {
                "title": r.get("title") or "",
                "description": r.get("description") or "",
                "date": iso(r_parsed_date) if r_parsed_date else (r.get("date") or ""),
                "rating": r.get("rating") or "",
                "reviewer": r.get("reviewer") or "",
                "source": "G2"
            }
            normalized.append(r_copy)

    # final filter to ensure dates in range if we parsed them
    filtered = []
    for r in normalized:
        if r.get("date"):
            p = parse_date_safe(r["date"])
            if p and within_range(p, start, end):
                filtered.append(r)
            elif not p:
                # keep unknown string-dates (conservative)
                filtered.append(r)
        else:
            filtered.append(r)
    return filtered

async def scrape_capterra(page: Page, company_slug: str, start: datetime, end: datetime) -> List[Dict]:
    # Capterra product pages often look like:
    # https://www.capterra.com/p/12345/product-name/reviews/
    # But many use search-based slugs. We attempt a naive slug URL and fall back to search.
    url_variants = [
        f"https://www.capterra.com/p/{company_slug}/reviews/",
        f"https://www.capterra.com/search?q={company_slug}",
        f"https://www.capterra.com/p/{company_slug}/"
    ]
    success = False
    for u in url_variants:
        try:
            print("Trying Capterra URL:", u)
            await page.goto(u, timeout=20000)
            success = True
            break
        except Exception:
            success = False
            continue
    if not success:
        raise RuntimeError("Could not open Capterra page for provided slug. Please verify company slug.")

    all_reviews = await scroll_and_collect(page)

    normalized = []
    for r in all_reviews:
        dt = parse_date_safe(r.get('date') or "")
        r_copy = {
            "title": r.get("title") or "",
            "description": r.get("description") or "",
            "date": iso(dt) if dt else (r.get("date") or ""),
            "rating": r.get("rating") or "",
            "reviewer": r.get("reviewer") or "",
            "source": "Capterra"
        }
        # filter if date parsed and out of range
        if dt:
            if within_range(dt, start, end):
                normalized.append(r_copy)
        else:
            # keep if date unknown (optionally)
            normalized.append(r_copy)
    return normalized

async def scrape_trustradius(page: Page, company_slug: str, start: datetime, end: datetime) -> List[Dict]:
    url = f"https://www.trustradius.com/products/{company_slug}/reviews"
    print("Opening TrustRadius:", url)
    try:
        await page.goto(url, timeout=30000)
    except Exception as e:
        raise RuntimeError(f"Could not open TrustRadius page: {e}")

    all_reviews = await scroll_and_collect(page)
    normalized = []
    for r in all_reviews:
        dt = parse_date_safe(r.get('date') or "")
        r_copy = {
            "title": r.get("title") or "",
            "description": r.get("description") or "",
            "date": iso(dt) if dt else (r.get("date") or ""),
            "rating": r.get("rating") or "",
            "reviewer": r.get("reviewer") or "",
            "source": "TrustRadius"
        }
        if dt:
            if within_range(dt, start, end):
                normalized.append(r_copy)
        else:
            normalized.append(r_copy)
    return normalized

# -----------------------
# Orchestrator
# -----------------------
async def run_scraper(company: str, start_date: str, end_date: str, source: str, outdir: str = "."):
    # validate dates
    try:
        start = dateparser.parse(start_date)
        end = dateparser.parse(end_date)
    except Exception as e:
        raise ValueError(f"Invalid date(s): {e}")
    if start > end:
        raise ValueError("Start date must be <= end date.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        source_lower = source.lower()
        if source_lower == "g2":
            reviews = await scrape_g2(page, company, start, end)
        elif source_lower == "capterra":
            reviews = await scrape_capterra(page, company, start, end)
        elif source_lower in ("trustradius", "trust radius", "trust-radius"):
            reviews = await scrape_trustradius(page, company, start, end)
        else:
            raise ValueError("Unsupported source. Choose 'g2', 'capterra' or 'trustradius'.")

        # close browser
        await context.close()
        await browser.close()

    # Save JSON
    outdir_p = Path(outdir)
    outdir_p.mkdir(parents=True, exist_ok=True)
    fname = f"{company}_{source_lower}_{start.strftime('%Y%m%d')}_to_{end.strftime('%Y%m%d')}.json"
    outpath = outdir_p / fname
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(reviews)} reviews to {outpath}")
    return outpath, reviews

# -----------------------
# CLI
# -----------------------
def main():
    parser = argparse.ArgumentParser(description="Scrape product reviews from G2 / Capterra / TrustRadius")
    parser.add_argument("--company", required=True, help="Company product slug (as used in the site's URL)")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--source", required=True, choices=["g2","capterra","trustradius"], help="Source: g2 | capterra | trustradius")
    parser.add_argument("--outdir", default=".", help="Output directory for JSON")
    args = parser.parse_args()

    try:
        outpath, reviews = asyncio.run(run_scraper(args.company, args.start, args.end, args.source, args.outdir))
    except Exception as e:
        print("Error:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()   