from flask import Flask, render_template, request, send_file
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import os
from urllib.parse import urljoin, urlparse
import tldextract
from urllib.robotparser import RobotFileParser

app = Flask(__name__)

OUTPUT_FILE = "corporate_travel_leads.xlsx"

EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE_REGEX = r"(\+?\d[\d\-\s\(\)]{7,}\d)"


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def get_domain(url: str) -> str:
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
    except Exception:
        pass
    return ""


def can_fetch(url: str, user_agent: str = "*") -> bool:
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def extract_emails_and_phones(text: str):
    emails = set(re.findall(EMAIL_REGEX, text, re.I))
    phones = set()

    for match in re.findall(PHONE_REGEX, text):
        phone = " ".join(match.split())
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 8:
            phones.add(phone)

    filtered_emails = set()
    bad_parts = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".pdf"]
    for email in emails:
        e = email.lower()
        if not any(part in e for part in bad_parts):
            filtered_emails.add(e)

    return sorted(filtered_emails), sorted(phones)


def find_candidate_pages(base_url: str, soup: BeautifulSoup):
    keywords = ["contact", "about", "support", "reach", "company", "locations"]
    found = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text(" ", strip=True).lower()
        href_l = href.lower()

        if any(k in href_l for k in keywords) or any(k in text for k in keywords):
            abs_url = urljoin(base_url, href)
            if abs_url not in found:
                found.append(abs_url)

    return found[:3]


def scrape_website(website: str):
    result = {
        "contact_page": "",
        "scraped_emails": "",
        "scraped_phones": "",
        "website_status": "",
        "notes": ""
    }

    if not website:
        result["notes"] = "No website found"
        return result

    website = normalize_url(website)
    headers = {"User-Agent": "Mozilla/5.0 LeadGenerator/1.0"}

    try:
        if not can_fetch(website, headers["User-Agent"]):
            result["website_status"] = "Blocked by robots"
            result["notes"] = "robots.txt disallows fetch"
            return result

        r = requests.get(website, headers=headers, timeout=12)
        r.raise_for_status()

        html = r.text
        soup = BeautifulSoup(html, "html.parser")

        emails, phones = extract_emails_and_phones(html)
        candidate_pages = find_candidate_pages(website, soup)

        extra_emails = []
        extra_phones = []

        if candidate_pages:
            result["contact_page"] = candidate_pages[0]

        for page in candidate_pages:
            try:
                if not can_fetch(page, headers["User-Agent"]):
                    continue
                pr = requests.get(page, headers=headers, timeout=12)
                pr.raise_for_status()
                pe, pp = extract_emails_and_phones(pr.text)
                extra_emails.extend(pe)
                extra_phones.extend(pp)
            except Exception:
                continue

        all_emails = sorted(set(emails + extra_emails))
        all_phones = sorted(set(phones + extra_phones))

        result["scraped_emails"] = ", ".join(all_emails[:10])
        result["scraped_phones"] = ", ".join(all_phones[:10])
        result["website_status"] = "Success"

        if not all_emails and not all_phones:
            result["notes"] = "No public email/phone found on checked pages"

    except Exception as e:
        result["website_status"] = "Failed"
        result["notes"] = str(e)

    return result


def google_places_search(api_key: str, query: str):
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,"
            "places.formattedAddress,"
            "places.websiteUri,"
            "places.internationalPhoneNumber,"
            "places.nationalPhoneNumber,"
            "places.googleMapsUri"
        ),
    }
    payload = {
        "textQuery": query,
        "maxResultCount": 15
    }

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    r.raise_for_status()
    return r.json().get("places", [])


def hunter_domain_search(api_key: str, domain: str):
    if not api_key or not domain:
        return []

    url = "https://api.hunter.io/v2/domain-search"
    params = {"domain": domain, "api_key": api_key}

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("data", {}).get("emails", [])
    except Exception:
        return []


def hunter_verify_email(api_key: str, email: str):
    if not api_key or not email:
        return ""

    url = "https://api.hunter.io/v2/email-verifier"
    params = {"email": email, "api_key": api_key}

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("data", {}).get("status", "")
    except Exception:
        return ""


@app.route("/", methods=["GET", "POST"])
def index():
    message = ""
    preview_rows = []

    if request.method == "POST":
        google_api_key = request.form.get("google_api_key", "").strip()
        hunter_api_key = request.form.get("hunter_api_key", "").strip()
        keyword = request.form.get("keyword", "").strip()
        city = request.form.get("city", "").strip()

        if not google_api_key or not keyword or not city:
            message = "Enter Google API key, keyword, and city."
            return render_template("index.html", message=message, preview_rows=preview_rows)

        query = f"{keyword} in {city}"

        try:
            places = google_places_search(google_api_key, query)
            rows = []

            for place in places:
                company_name = place.get("displayName", {}).get("text", "")
                website = place.get("websiteUri", "")
                phone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""
                address = place.get("formattedAddress", "")
                maps_url = place.get("googleMapsUri", "")

                scraped = scrape_website(website)

                domain = get_domain(website)
                hunter_emails = hunter_domain_search(hunter_api_key, domain) if hunter_api_key and domain else []
                hunter_list = [x.get("value", "") for x in hunter_emails if x.get("value")]

                verification = ""
                if hunter_api_key and hunter_list:
                    verification = hunter_verify_email(hunter_api_key, hunter_list[0])

                rows.append({
                    "Company Name": company_name,
                    "Website": website,
                    "Google Phone": phone,
                    "Address": address,
                    "Google Maps URL": maps_url,
                    "Contact Page": scraped["contact_page"],
                    "Scraped Emails": scraped["scraped_emails"],
                    "Scraped Phones": scraped["scraped_phones"],
                    "Hunter Emails": ", ".join(hunter_list[:5]),
                    "Verification Status": verification,
                    "Website Status": scraped["website_status"],
                    "Notes": scraped["notes"],
                    "Source Query": query
                })

            df = pd.DataFrame(rows)
            if not df.empty:
                df.drop_duplicates(subset=["Company Name", "Website", "Google Phone"], inplace=True)

            df.to_excel(OUTPUT_FILE, index=False)
            preview_rows = df.head(10).to_dict(orient="records")
            message = f"Done. Saved {len(df)} leads to {OUTPUT_FILE}"

        except Exception as e:
            message = f"Error: {e}"

    return render_template("index.html", message=message, preview_rows=preview_rows)


@app.route("/download")
def download():
    if os.path.exists(OUTPUT_FILE):
        return send_file(OUTPUT_FILE, as_attachment=True)
    return "No Excel file created yet."


if __name__ == "__main__":
    app.run(debug=True)