"""Category suggestions for the To Update cards.

Two sources, best first:
1. Your own history: rows you've already given a category, matched on the
   same person ("To Jane Tan"), the same Item, or shared words.
2. Common Malaysian shop and bill words (MAKAN -> Food, PETRONAS -> Transport).

Only categories in your list are suggested. Pure: text in, names out.
"""

from __future__ import annotations

import re
from collections import Counter

KEYWORDS: dict[str, list[str]] = {
    "Food": [
        "makan", "restoran", "restaurant", "cafe", "café", "kopi", "coffee", "kopitiam", "nasi", "mee", "mamak",
        "bakery", "bakeri", "kitchen", "dapur", "food", "foods", "lunch", "dinner", "breakfast", "brunch", "supper",
        "drink", "drinks", "tea", "boba", "bubble", "dim sum", "noodle", "noodles", "ramen", "sushi", "pizza",
        "burger", "chicken", "ayam", "satay", "roti", "char kuey teow", "hawker", "kedai makan", "mcdonald",
        "kfc", "starbucks", "zus", "tealive", "chagee", "mixue", "secret recipe", "grabfood", "foodpanda",
        "shopeefood", "malatang", "steamboat", "bbq", "grill", "bistro", "snack", "dessert", "ice cream",
    ],
    "Transport": [
        "grab", "petronas", "shell", "caltex", "petron", "bhp", "petrol", "fuel", "toll", "plus", "parking",
        "park", "rapid", "mrt", "lrt", "ktm", "ets", "bus", "taxi", "airasia", "malaysia airlines",
        "firefly", "flight", "transit", "touch n go", "smarttag", "car wash", "tyre", "service centre",
    ],
    "Bills": [
        "tnb", "tenaga", "unifi", "maxis", "celcom", "digi", "umobile", "u mobile", "hotlink",
        "astro", "insurance", "takaful", "aia", "prudential", "great eastern", "allianz", "indah water",
        "air selangor", "syabas", "water", "rent", "sewa", "electric", "electricity", "internet", "phone bill",
        "postpaid", "prepaid", "reload", "cukai", "assessment", "quit rent", "loan", "ptptn", "subscription",
    ],
    "Health": [
        "clinic", "klinik", "pharmacy", "farmasi", "guardian", "watsons", "caring", "hospital", "dental",
        "dentist", "doctor", "medical", "medic", "gym", "fitness", "physio", "optical", "spectacles",
    ],
    "Shopping": [
        "shopee", "lazada", "mr diy", "mr. diy", "uniqlo", "h&m", "zara", "ikea", "aeon", "mydin", "speedmart",
        "tesco", "lotus", "giant", "jaya grocer", "village grocer", "econsave", "nsk", "family mart",
        "familymart", "7-eleven", "7 eleven", "kk mart", "mall", "store", "shop", "mart", "supermarket",
        "hypermarket", "daiso", "decathlon", "taobao", "temu", "amazon", "apple", "groceries", "grocery",
    ],
    "Entertainment": [
        "netflix", "spotify", "youtube", "disney", "cinema", "gsc", "tgv", "mbo", "steam", "playstation", "xbox",
        "nintendo", "game", "games", "concert", "ticket", "tickets", "karaoke", "bowling", "movie", "movies",
    ],
    "Self-Development": [
        "udemy", "coursera", "course", "class", "classes", "tuition", "book", "books", "kinokuniya", "popular",
        "mph", "bookxcess", "exam", "workshop", "seminar", "skillshare",
    ],
}

_WORD = re.compile(r"[a-z0-9&'.-]+")
_IGNORE = {
    "to", "from", "transfer", "duitnow", "qr", "payment", "pay", "sdn", "bhd", "the", "and", "of", "my",
    "fpx", "ibg", "instant", "online", "purchase", "id", "ref", "transaction", "debit", "credit", "card",
}


def _words(text: str) -> set[str]:
    return {w.strip(".-'") for w in _WORD.findall(text.lower())} - _IGNORE - {""}


def suggest_categories(statement: str, who: str, item: str, history: list[list[str]], categories: list[str],
                       limit: int = 3) -> list[str]:
    """`statement`: the statement text; `who`: Remarks ("To Jane Tan");
    `item`: the Item recorded or typed so far. `history`: [item, remarks,
    category] of rows that already have a category. Returns up to `limit`
    names from `categories`, best first."""
    allowed = {c.lower(): c for c in categories}
    blob = " " + " ".join(t.lower() for t in (statement, who, item) if t) + " "
    words = _words(blob)
    who = (who or "").strip().lower()
    item = (item or "").strip().lower()
    if item in ("transfer", "qr payment"):
        item = ""
    score: Counter[str] = Counter()

    for row in history:
        h_item, h_remarks, h_cat = (list(row) + ["", "", ""])[:3]
        cat = allowed.get(str(h_cat).strip().lower())
        if not cat:
            continue
        h_item, h_remarks = str(h_item).strip().lower(), str(h_remarks).strip().lower()
        if who and h_remarks == who:
            score[cat] += 3
        if h_item and h_item not in ("transfer", "qr payment") and h_item == item:
            score[cat] += 4
        score[cat] += len(words & _words(h_item)) * 1.5

    for cat, keys in KEYWORDS.items():
        name = allowed.get(cat.lower())
        if not name:
            continue
        for k in keys:
            if (" " in k and k in blob) or (k.strip() in words):
                score[name] += 2

    # Your own list may have names the keywords don't know: match on the name itself.
    for low, name in allowed.items():
        if low in words or (" " in low and low in blob):
            score[name] += 2

    return [c for c, s in score.most_common() if s > 0][:limit]
