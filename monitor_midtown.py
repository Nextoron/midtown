import os
import json
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = "state.json"
BASE_URL = "https://www.midtowncomics.com/search?rel=&cfr=t&q="

EXCLUDES = [
    "tpb",
    "trade paperback",
    "hardcover",
    "hc",
    "omnibus",
    "compendium",
    "graphic novel",
]

BAD_TITLE_EXACT = {
    "add to cart",
    "added",
    "by",
    "release date",
    "current price:",
    "original price:",
    "view more...",
    "quick view",
}

BAD_TITLE_CONTAINS = [
    "choose qty for",
    "in cart",
    "free shipping",
    "free bag & board",
    "order online for in-store pick up",
]

def load_keywords():
    with open("keywords.txt", "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip()]

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(state), f, indent=2)

def post_discord(message: str):
    r = requests.post(WEBHOOK, json={"content": message}, timeout=20)
    r.raise_for_status()

def fetch_search_html(keyword: str) -> str:
    url = BASE_URL + quote_plus(keyword)
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def normalize_spaces(text: str) -> str:
    return " ".join(text.split()).strip()

def looks_like_noise(title: str) -> bool:
    t = normalize_spaces(title).lower()

    if len(t) < 5:
        return True
    if t in BAD_TITLE_EXACT:
        return True
    if any(bad in t for bad in BAD_TITLE_CONTAINS):
        return True
    return False

def excluded_format(title: str) -> bool:
    t = title.lower()
    return any(ex in t for ex in EXCLUDES)

def keyword_matches_title(keyword: str, title: str) -> bool:
    k = keyword.lower().strip()
    t = title.lower()

    # Exact phrase match first
    if k in t:
        return True

    # Then a softer all-words match for phrases
    words = [w for w in k.split() if w]
    return bool(words) and all(w in t for w in words)

def parse_items(html: str, keyword: str):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_links = set()

    for a in soup.find_all("a", href=True):
        title = normalize_spaces(a.get_text(" ", strip=True))
        href = a.get("href", "").strip()

        if not title or not href:
            continue
        if looks_like_noise(title):
            continue
        if excluded_format(title):
            continue
        if not keyword_matches_title(keyword, title):
            continue

        link = urljoin("https://www.midtowncomics.com", href)

        # Skip obvious non-product/navigation links
        if "/search" in link and "q=" in link:
            continue
        if link.endswith("#"):
            continue

        if link in seen_links:
            continue

        seen_links.add(link)
        items.append({
            "title": title,
            "link": link,
            "price": "N/A",
        })

    return items

def main():
    keywords = load_keywords()
    seen = load_state()
    updated_seen = set(seen)

    for keyword in keywords:
        html = fetch_search_html(keyword)
        items = parse_items(html, keyword)

        for item in items:
            key = item["link"]

            if key in seen:
                continue

            updated_seen.add(key)

            message = (
                f"🟢 **New Midtown Match**\n"
                f"**Keyword:** {keyword}\n"
                f"**Title:** {item['title']}\n"
                f"{item['link']}"
            )
            post_discord(message)

    save_state(updated_seen)

if __name__ == "__main__":
    main()
