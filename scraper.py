# -*- coding: utf-8 -*-
"""
מנוע העדכון — סורק את האתרים הרשמיים של קניון הדר וקניון סביונים,
מושך שם / קומה / קטגוריה / טלפון / שעות / תמונה, וכותב stores.json.

עקרונות אמינות:
- מתמזג עם stores.json הקיים. אם סריקה של קניון נכשלת או מחזירה מעט מדי חנויות,
  שומרים את הנתונים הקודמים של אותו קניון — כך האתר אף פעם לא "נשבר".
- קומות סביונים נלקחות מ- data/savyonim_floors.json (האתר הרשמי לא מפרסם קומות),
  וממופות לפי שם בכל ריצה, כך שגם חנות חדשה תקבל קומה אם הוספת אותה למיפוי.
- מזהה ומדפיס שינויים (נוספו / הוסרו / השתנתה קומה) לכל ריצה.

הרצה:  python3 scraper.py
דרישות:  pip install requests beautifulsoup4 lxml
"""
import json, re, os, sys, unicodedata, hashlib, datetime
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "stores.json")
FLOORS_FILE = os.path.join(ROOT, "data", "savyonim_floors.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
           "Accept-Language": "he-IL,he;q=0.9,en;q=0.8"}
TIMEOUT = 30
MIN_OK = {"hadar": 40, "savyonim": 25}  # מתחת לזה נחשב "סריקה כושלת" ונשמור ישן

HADAR_URL = "https://www.hadar-mall.co.il/hadar-mall-stores"
SAV_LIST_URL = "https://friendly-savyonim.co.il/store/"
SAV_WPJSON = "https://friendly-savyonim.co.il/wp-json/wp/v2/"

# ---------------- עזרי נרמול ----------------
def norm(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9א-ת]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def sid(mall, name):
    return hashlib.md5(f"{mall}|{norm(name)}".encode("utf-8")).hexdigest()[:10]

def get(url, **kw):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r

def clean_floor(txt):
    if not txt: return None
    t = txt.replace("קומה", " ").strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t or None

# ---------------- קניון הדר ----------------
def scrape_hadar():
    """מבנה: כרטיסי חנות עם שם + קטגוריה + טלפון + 'קומה X'."""
    html = get(HADAR_URL).text
    soup = BeautifulSoup(html, "lxml")
    stores, seen = [], set()

    # אסטרטגיה 1: כרטיסים שמכילים את המילה "קומה"
    candidates = []
    for el in soup.find_all(["article", "li", "div"]):
        txt = el.get_text(" ", strip=True)
        if "קומה" in txt and 3 <= len(txt) <= 200 and el.find(["h1","h2","h3","h4","h5","a","strong"]):
            candidates.append(el)

    # בוחרים את רמת-הכרטיס הקטנה ביותר (כדי לא לתפוס קונטיינרים ענקיים)
    for el in candidates:
        name_el = el.find(["h2","h3","h4","h5","strong","a"])
        name = name_el.get_text(" ", strip=True) if name_el else None
        if not name or len(name) > 60:
            continue
        txt = el.get_text(" ", strip=True)
        mfloor = re.search(r"קומה\s*([0-9\-]+)", txt)
        floor = mfloor.group(1) if mfloor else None
        mphone = re.search(r"(0\d[\d\-]{6,})", txt)
        phone = mphone.group(1) if mphone else None
        img = el.find("img")
        image = None
        if img:
            image = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        key = norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        stores.append({"name": name, "floor": floor, "category": None,
                       "phone": phone, "hours": None, "image": image,
                       "url": HADAR_URL})
    return stores

# ---------------- קניון סביונים ----------------
def scrape_savyonim_wpjson():
    """ניסיון מועדף: WordPress REST API. מנסה כמה slugים נפוצים של סוג-תוכן 'חנות'."""
    types = None
    try:
        types = get(SAV_WPJSON + "types").json()
    except Exception:
        pass
    slugs = ["store", "stores", "shop", "shops", "hanut", "brand", "brands"]
    if isinstance(types, dict):
        for k in types.keys():
            if any(w in k.lower() for w in ("store", "shop", "brand")):
                slugs.insert(0, k)
    for slug in slugs:
        try:
            items, page = [], 1
            while True:
                r = get(SAV_WPJSON + f"{slug}?per_page=100&page={page}")
                batch = r.json()
                if not isinstance(batch, list) or not batch:
                    break
                items.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            if len(items) >= MIN_OK["savyonim"]:
                out = []
                for it in items:
                    title = (it.get("title") or {}).get("rendered") or it.get("name")
                    if not title: continue
                    title = BeautifulSoup(title, "lxml").get_text(" ", strip=True)
                    out.append({"name": title, "url": it.get("link"),
                                "category": None, "phone": None, "hours": None, "image": None})
                if out:
                    return out
        except Exception:
            continue
    return []

def scrape_savyonim_html():
    html = get(SAV_LIST_URL).text
    soup = BeautifulSoup(html, "lxml")
    stores, seen = [], set()
    for a in soup.select("a[href*='/store/']"):
        href = a.get("href", "")
        if href.rstrip("/").endswith("/store"):  # קישור לעמוד הראשי
            continue
        name = a.get_text(" ", strip=True)
        img = a.find("img")
        image = (img.get("src") or img.get("data-src")) if img else None
        if not name:
            if img and img.get("alt"):
                name = img.get("alt").strip()
        if not name or len(name) > 70:
            continue
        key = norm(name)
        if key in seen:
            continue
        seen.add(key)
        stores.append({"name": name, "url": href, "category": None,
                       "phone": None, "hours": None, "image": image})
    return stores

def scrape_savyonim():
    items = scrape_savyonim_wpjson()
    if len(items) < MIN_OK["savyonim"]:
        items = scrape_savyonim_html()
    # מיפוי קומות מהקובץ הידני
    floors = {}
    try:
        with open(FLOORS_FILE, encoding="utf-8") as f:
            floors = json.load(f).get("floors", {})
    except Exception as e:
        print("אזהרה: לא נטען קובץ הקומות של סביונים:", e)
    norm_floors = {norm(k): v for k, v in floors.items()}
    for s in items:
        s["floor"] = norm_floors.get(norm(s["name"]))
    return items

# ---------------- מיזוג ושמירה ----------------
def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stores": []}

def finalize(mall_key, mall_name, scraped, existing_stores):
    """מחזיר רשומות סופיות לקניון: אם הסריקה תקינה—בונה מחדש; אחרת שומר ישן."""
    old = [s for s in existing_stores if s.get("mall_key") == mall_key]
    if len(scraped) < MIN_OK[mall_key]:
        print(f"[{mall_key}] סריקה החזירה {len(scraped)} חנויות (<{MIN_OK[mall_key]}). שומר {len(old)} קיימות.")
        return old, {"status": "kept_old", "count": len(old)}
    old_by = {s["id"]: s for s in old}
    out, changes = [], {"added": [], "removed": [], "floor_changed": []}
    new_ids = set()
    for s in scraped:
        _id = sid(mall_name, s["name"])
        new_ids.add(_id)
        prev = old_by.get(_id, {})
        rec = {
            "id": _id, "name": s["name"], "mall": mall_name, "mall_key": mall_key,
            "floor": s.get("floor") or prev.get("floor"),
            "category": s.get("category") or prev.get("category") or "כללי",
            "phone": s.get("phone") or prev.get("phone"),
            "hours": s.get("hours") or prev.get("hours"),
            "image": s.get("image") or prev.get("image"),
            "url": s.get("url") or prev.get("url"),
        }
        if not prev:
            changes["added"].append(s["name"])
        elif prev.get("floor") != rec["floor"] and rec["floor"]:
            changes["floor_changed"].append(f'{s["name"]}: {prev.get("floor")}→{rec["floor"]}')
        out.append(rec)
    for _id, s in old_by.items():
        if _id not in new_ids:
            changes["removed"].append(s["name"])
    return out, {"status": "updated", "count": len(out), **changes}

def main():
    existing = load_existing()
    prev_stores = existing.get("stores", [])
    report = {}

    try:
        h = scrape_hadar()
    except Exception as e:
        print("שגיאת סריקה הדר:", e); h = []
    try:
        s = scrape_savyonim()
    except Exception as e:
        print("שגיאת סריקה סביונים:", e); s = []

    hadar_final, report["hadar"] = finalize("hadar", "קניון הדר ירושלים", h, prev_stores)
    sav_final, report["savyonim"] = finalize("savyonim", "קניון סביונים יהוד", s, prev_stores)

    stores = hadar_final + sav_final
    data = {
        "updated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": "scraper",
        "malls": [
            {"key": "hadar", "name": "קניון הדר ירושלים", "city": "ירושלים"},
            {"key": "savyonim", "name": "קניון סביונים יהוד", "city": "יהוד"},
        ],
        "count": len(stores),
        "stores": stores,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n===== סיכום ריצה =====")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"סה\"כ נכתבו {len(stores)} חנויות ל- {OUT}")
    # יציאה עם קוד שגיאה אם *שני* הקניונים נכשלו (כדי שה-Action יסמן אדום)
    if report["hadar"]["status"] == "kept_old" and report["savyonim"]["status"] == "kept_old":
        print("שני הקניונים נכשלו בסריקה — בדוק את הסלקטורים/הכתובות.")
        sys.exit(1)

if __name__ == "__main__":
    main()
