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
        keywords = [k.strip().lower() for k in f if k.strip()]
    print(f"DEBUG: loaded keywords -> {keywords}")
    return keywords

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = set(json.load(f))
            print(f"DEBUG: loaded state with {len(state)} items")
            return state
    except Exception as e:
        print(f"DEBUG: no existing state or failed to load state ({e})")
        return set()

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(state), f)
    print(f"DEBUG: saved state with {len(state)} items")

def post(msg):
    print("DEBUG: sending Discord message")
    r = requests.post(WEBHOOK, json={"content": msg}, timeout=20)
    print(f"DEBUG: Discord response status -> {r.status_code}")
    r.raise_for_status()

def fetch_results(keyword):
    url = BASE_URL + keyword.replace(" ", "+")
    print(f"DEBUG: fetching -> {url}")
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    print(f"DEBUG: fetch status for '{keyword}' -> {r.status_code}")
    r.raise_for_status()
    return r.text

def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    print(f"DEBUG: page title -> {soup.title.string if soup.title else 'NO TITLE'}")

    items = []

    # Broad temporary parser for debugging
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        title = a.get_text(" ", strip=True)

        if not title or len(title) < 5:
            continue

        if "/store/" not in href:
            continue

        if href.startswith("http"):
            link = href
        else:
            link = "https://www.midtowncomics.com" + href

        items.append({
            "title": title,
            "link": link,
            "price": "N/A"
        })

    print(f"DEBUG: parsed {len(items)} raw items")
    if items:
        print(f"DEBUG: first item -> {items[0]}")
    return items

def is_valid(title):
    t = title.lower()
    for ex in EXCLUDES:
        if ex in t:
            return False
    return True

def main():
    print("DEBUG: script started")
    keywords = load_keywords()
    seen = load_state()
    new_seen = set(seen)

    for keyword in keywords:
        print(f"DEBUG: checking keyword -> {keyword}")
        html = fetch_results(keyword)
        items = parse_items(html)

        for item in items:
            title = item["title"]

            if not is_valid(title):
                print(f"DEBUG: excluded -> {title}")
                continue

            key = item["link"]

            if key in seen:
                continue

            print(f"DEBUG: new match -> {title}")
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
    print("DEBUG: script finished")

if __name__ == "__main__":
    main()
