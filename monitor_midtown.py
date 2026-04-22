import os
import re
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = "state.json"
BASE_URL = "https://www.midtowncomics.com/search?rel=&cfr=t&q="

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

EXCLUDES = [
    "tpb",
    "trade paperback",
    "hardcover",
    " hc ",
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
    "image",
}

BAD_TITLE_CONTAINS = [
    "choose qty for",
    "in cart",
    "free shipping",
    "free bag & board",
    "order online for in-store pick up",
]

OUT_OF_STOCK_PHRASES = [
    "out of stock",
    "sold out",
    "currently unavailable",
    "unavailable",
]

IN_STOCK_PHRASES = [
    "add to cart",
    "in stock",
    "order online for in-store pick up",
    "free bag & board",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_keywords():
    with open("keywords.txt", "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip()]


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


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
    t = f" {title.lower()} "
    return any(ex in t for ex in EXCLUDES)


def keyword_matches_title(keyword: str, title: str) -> bool:
    k = keyword.lower().strip()
    t = title.lower()

    if k in t:
        return True

    words = [w for w in k.split() if w]
    return bool(words) and all(w in t for w in words)


def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_search_html(keyword: str) -> str:
    url = BASE_URL + quote_plus(keyword)
    return fetch_html(url)


def parse_search_items(html: str, keyword: str):
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

        if "/search" in link and "q=" in link:
            continue
        if link.endswith("#"):
            continue
        if "/product/" not in link:
            continue

        if link in seen_links:
            continue

        seen_links.add(link)
        items.append({
            "title": title,
            "link": link,
            "keyword": keyword,
        })

    return items


def extract_price(text: str):
    text = normalize_spaces(text)

    current_price_match = re.search(
        r"Current price:\s*\$([0-9]+(?:\.[0-9]{2})?)",
        text,
        re.IGNORECASE
    )
    if current_price_match:
        return float(current_price_match.group(1))

    near_mint_match = re.search(
        r"Near Mint\s*-\s*\$([0-9]+(?:\.[0-9]{2})?)",
        text,
        re.IGNORECASE
    )
    if near_mint_match:
        return float(near_mint_match.group(1))

    generic_match = re.search(r"\$([0-9]+(?:\.[0-9]{2})?)", text)
    if generic_match:
        return float(generic_match.group(1))

    return None


def detect_stock_status(page_text: str):
    t = normalize_spaces(page_text).lower()

    for phrase in OUT_OF_STOCK_PHRASES:
        if phrase in t:
            return False

    for phrase in IN_STOCK_PHRASES:
        if phrase in t:
            return True

    return False


def fetch_product_details(link: str):
    try:
        html = fetch_html(link)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        price = extract_price(text)
        in_stock = detect_stock_status(text)

        title_tag = soup.find("meta", attrs={"property": "og:title"})
        page_title = title_tag.get("content") if title_tag and title_tag.get("content") else None

        return {
            "price": price,
            "page_title": page_title,
            "in_stock": in_stock,
        }
    except Exception as e:
        print(f"Failed to fetch product details for {link}: {e}")
        return {
            "price": None,
            "page_title": None,
            "in_stock": False,
        }


def discord_post(payload):
    for attempt in range(6):
        r = requests.post(WEBHOOK, json=payload, timeout=20)

        if r.status_code in (200, 204):
            return True

        if r.status_code == 429:
            retry_after = 5
            try:
                data = r.json()
                retry_after = float(data.get("retry_after", 5))
            except Exception:
                pass

            print(f"Discord rate limit hit. Sleeping {retry_after} seconds.")
            time.sleep(retry_after)
            continue

        print(f"Discord error {r.status_code}: {r.text}")
        return False

    print("Failed to send Discord message after retries.")
    return False


def build_embed(alert_type, item, status_text, price_text, old_price_text=None, new_price_text=None):
    title_prefix = {
        "new": "🚨 NEW MIDTOWN MATCH",
        "restock": "🔄 MIDTOWN RESTOCK",
        "price_drop": "💸 MIDTOWN PRICE DROP",
    }[alert_type]

    fields = [
        {
            "name": "🔍 Keyword",
            "value": item["keyword"],
            "inline": True
        },
        {
            "name": "📦 Status",
            "value": status_text,
            "inline": True
        }
    ]

    if alert_type == "price_drop":
        fields.insert(1, {
            "name": "💰 Old Price",
            "value": old_price_text,
            "inline": True
        })
        fields.insert(2, {
            "name": "💵 New Price",
            "value": new_price_text,
            "inline": True
        })
    else:
        fields.insert(1, {
            "name": "💰 Price",
            "value": price_text,
            "inline": True
        })

    return {
        "embeds": [
            {
                "title": f"{title_prefix} — {item['title']}",
                "url": item["link"],
                "color": 5814783,
                "fields": fields
            }
        ]
    }


def send_new_item_alert(item, price):
    price_text = f"${price:.2f}" if isinstance(price, (int, float)) else "N/A"
    payload = build_embed(
        alert_type="new",
        item=item,
        status_text="In Stock",
        price_text=price_text
    )
    return discord_post(payload)


def send_restock_alert(item, price):
    price_text = f"${price:.2f}" if isinstance(price, (int, float)) else "N/A"
    payload = build_embed(
        alert_type="restock",
        item=item,
        status_text="Back In Stock",
        price_text=price_text
    )
    return discord_post(payload)


def send_price_drop_alert(item, old_price, new_price):
    payload = build_embed(
        alert_type="price_drop",
        item=item,
        status_text="In Stock",
        price_text=None,
        old_price_text=f"${old_price:.2f}",
        new_price_text=f"${new_price:.2f}"
    )
    return discord_post(payload)


def main():
    keywords = load_keywords()
    state = load_state()

    baseline_mode = len(state) == 0
    if baseline_mode:
        print("Baseline mode: empty state, learning current items without sending alerts.")

    for keyword in keywords:
        print(f"Checking keyword: {keyword}")
        search_html = fetch_search_html(keyword)
        items = parse_search_items(search_html, keyword)
        print(f"Found {len(items)} candidate items for {keyword}")

        for item in items:
            link = item["link"]
            old_record = state.get(link)

            details = fetch_product_details(link)
            price = details["price"]
            in_stock = details["in_stock"]

            if details["page_title"]:
                cleaned_title = normalize_spaces(details["page_title"])
                if cleaned_title:
                    item["title"] = cleaned_title

            if excluded_format(item["title"]):
                continue

            if old_record is None:
                if not baseline_mode and in_stock:
                    sent = send_new_item_alert(item, price)
                    print(f"New item alert: {item['title']} | sent={sent}")
                    time.sleep(1.25)

                state[link] = {
                    "title": item["title"],
                    "keyword": item["keyword"],
                    "price": price,
                    "in_stock": in_stock,
                    "last_seen": now_iso(),
                }
                continue

            old_price = old_record.get("price")
            old_in_stock = bool(old_record.get("in_stock", False))

            if (not old_in_stock) and in_stock and (not baseline_mode):
                sent = send_restock_alert(item, price)
                print(f"Restock alert: {item['title']} | sent={sent}")
                time.sleep(1.25)

            if (
                old_in_stock
                and in_stock
                and isinstance(old_price, (int, float))
                and isinstance(price, (int, float))
                and price < old_price
                and (not baseline_mode)
            ):
                sent = send_price_drop_alert(item, old_price, price)
                print(f"Price drop alert: {item['title']} | {old_price} -> {price} | sent={sent}")
                time.sleep(1.25)

            state[link] = {
                "title": item["title"],
                "keyword": item["keyword"],
                "price": price,
                "in_stock": in_stock,
                "last_seen": now_iso(),
            }

    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
