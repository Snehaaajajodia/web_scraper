# Review Scraper

A Python script to scrape product reviews from popular software review platforms (G2, Capterra, TrustRadius) using Playwright for JavaScript-rendered content.

## Features

- Scrapes reviews from G2, Capterra, and TrustRadius
- Handles JavaScript-rendered content with Playwright
- Filters reviews by date range
- Supports infinite scroll and pagination
- Extracts review title, description, date, rating, and reviewer information
- Outputs results in JSON format

## Requirements

- Python 3.7+
- Playwright browser automation framework

## Installation

1. Clone or download this repository
2. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Install Playwright browsers:
   ```bash
   playwright install
   ```

## Usage

```bash
python scrape_reviews.py --company <company_slug> --start <start_date> --end <end_date> --source <source>
```

### Parameters

- `--company`: Company product slug (as used in the site's URL)
  - Example: For Zoho CRM on G2 (https://www.g2.com/products/zoho-crm/reviews), use `zoho-crm`
- `--start`: Start date in YYYY-MM-DD format
- `--end`: End date in YYYY-MM-DD format
- `--source`: Review source (`g2`, `capterra`, or `trustradius`)
- `--outdir`: (Optional) Output directory for JSON files (defaults to current directory)

### Examples

```bash
# Scrape Zoho CRM reviews from G2 between Jan 1 and June 30, 2024
python scrape_reviews.py --company zoho-crm --start 2024-01-01 --end 2024-06-30 --source g2

# Scrape Salesforce reviews from Capterra
python scrape_reviews.py --company salesforce --start 2024-01-01 --end 2024-03-31 --source capterra

# Scrape HubSpot reviews from TrustRadius and save to a specific directory
python scrape_reviews.py --company hubspot --start 2023-12-01 --end 2024-05-31 --source trustradius --outdir ./reviews
```

## Output

The script generates a JSON file with the following naming convention:
`{company}_{source}_{start_date}_to_{end_date}.json`

Each review contains these fields:
- `title`: Review title
- `description`: Review content/body
- `date`: Review date (ISO format when possible)
- `rating`: Star rating or score
- `reviewer`: Reviewer name or identifier
- `source`: Source platform

## Notes

1. The company slug should match the product identifier used by the target website
2. Check the product page URL manually if unsure about the correct slug
3. Date parsing is heuristic - some reviews without clear dates might be included
4. Website structures change frequently - selectors may need updating over time
5. The script handles infinite scroll and "Load More" buttons automatically

## Troubleshooting

- If you get timeout errors, try increasing the timeout values in the code
- If no reviews are found, verify the company slug is correct
- If dates aren't being parsed correctly, check the date format on the target site

## Legal Considerations

- Respect websites' terms of service and robots.txt files
- Use appropriate delays between requests to avoid overloading servers
- Consider using official APIs when available
- This tool is for educational purposes - check legality in your jurisdiction

## License

This project is provided for educational purposes. Please ensure you comply with the terms of service of any websites you scrape and applicable laws in your jurisdiction.
