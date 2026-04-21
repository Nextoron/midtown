import os
import json
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
    "graphic novel"
]

def load_keywords():
    with open("keywords.txt", "r", encoding="utf-8") as f:
        return [k.strip().lower() for k in f if k.strip()]

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(state), f)

def post(msg):
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=20)
    r.raise_for_status()

def fetch_results(keyword):
    url = BASE_URL + keyword.replace(" ", "+")
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for card in soup.select(".product"):
        title_tag = card.select_one(".product-title")
        price_tag = card.select_one(".price")

        if not title_tag:
            continue

        href = title_tag.get("href")
        if not href:
            continue

        title = title_tag.get_text(strip=True)
        link = "https://www.midtowncomics.com" + href
        price = price_tag.get_text(strip=True) if price_tag else "N/A"

        items.append({
            "title": title,
            "link": link,
            "price": price
        })

    return items

def is_valid(title):
    t = title.lower()
    for ex in EXCLUDES:
        if ex in t:
            return False
    return True

def main():
    keywords = load_keywords()
    seen = load_state()
    new_seen = set(seen)

    for keyword in keywords:
        html = fetch_results(keyword)
        items = parse_items(html)

        for item in items:
            title = item["title"]

            if not is_valid(title):
                continue

            key = item["link"]

            if key in seen:
                continue

            new_seen.add(key)

            msg = (
                f"🟢 **New Midtown Match**\n"
                f"**Keyword:** {keyword}\n"
                f"**Title:** {title}\n"
                f"**Price:** {item['price']}\n"
                f"{item['link']}"
            )

            post(msg)

    save_state(new_seen)

if __name__ == "__main__":
    main()
