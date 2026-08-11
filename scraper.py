# -*- coding: utf-8 -*-
"""
מנוע העדכון (גרסה 2) — מושך לוגואים אמיתיים ונתונים מהאתרים הרשמיים של הקניונים.

חשוב: האתרים טוענים את הלוגואים דרך JavaScript, ולכן המנוע משתמש בדפדפן headless
(Playwright/Chromium) שמרנדר את הדף לפני החילוץ. זה רץ מצוין ב-GitHub Actions.

עקרונות עמידות:
- הבסיס הוא stores.json הקיים (רשימת החנויות המטופחת: שמות, קומות, קטגוריות, טלפונים, כינויים).
- מהאתרים מחלצים מפת "שם חנות -> לוגו" ומצרפים לוגו אמיתי לכל חנות שמזוהה.
- חנות חדשה שמופיעה באתר ולא קיימת אצלנו — מתווספת (עם לוגו וקומה אם נמצאו).
- אם רינדור של אתר נכשל — שומרים את הנתונים הקודמים של אותו קניון (כולל לוגו פאביקון), כך שהאתר לא נשבר.
- כל חנות שאין לה לוגו אמיתי מקבלת פאביקון (logos_util) כגיבוי, ואם גם זה אין — עיגול ראשי-תיבות בממשק.

דרישות:  pip install playwright beautifulsoup4 lxml  &&  playwright install chromium
הרצה:    python3 scraper.py
"""
import json, os, re, sys, unicodedata, hashlib, datetime
from aliases_util import load_groups, aliases_for, norm
from logos_util import load_brands, logo_for

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "stores.json")
FLOORS_FILE = os.path.join(ROOT, "data", "savyonim_floors.json")
ALIAS_GROUPS = load_groups()
BRANDS = load_brands()

SITES = [
    ("hadar", "קניון הדר ירושלים", "https://www.hadar-mall.co.il/hadar-mall-stores", "ירושלים"),
    ("savyonim", "קניון סביונים יהוד", "https://friendly-savyonim.co.il/store/", "יהוד"),
]
MIN_OK = {"hadar": 30, "savyonim": 20}

def sid(mall, name):
    return hashlib.md5(f"{mall}|{norm(name)}".encode("utf-8")).hexdigest()[:10]

# ---- חילוץ בתוך הדף (רץ בדפדפן): מחזיר [{name,image,floor,phone}] ----
JS_EXTRACT = r"""
() => {
  const out = [], seen = new Set();
  const bad = /(sprite|placeholder|blank|spacer|logo-header|site-logo|header|footer|icon-|\.svg($|\?))/i;
  const imgs = Array.from(document.querySelectorAll('img'));
  for (const img of imgs) {
    const src = img.currentSrc || img.src || img.getAttribute('data-src')
              || img.getAttribute('data-lazy-src') || img.getAttribute('data-original') || '';
    if (!src || src.startsWith('data:') || bad.test(src)) continue;
    const card = img.closest('a, li, article, .store, .shop, [class*="store"], [class*="shop"]') || img.parentElement;
    if (!card) continue;
    let name = (img.getAttribute('alt') || '').trim();
    const text = (card.innerText || '').replace(/\s+/g,' ').trim();
    if (!name) name = (text.split(' | ')[0] || text).slice(0,60).trim();
    if (!name || name.length > 60) continue;
    let floor = null;
    const mm = text.match(/קומה\s*(-?\d+)/);
    if (mm) floor = mm[1];
    else if (/קומת\s*קרקע/.test(text)) floor = 'קומת קרקע';
    const ph = text.match(/0\d[\d\- ]{6,}\d/);
    const key = name.replace(/\s+/g,' ').toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({name, image: src, floor, phone: ph ? ph[0].replace(/\s/g,'') : null});
  }
  return out;
}
"""

def render_cards(url):
    """מרנדר דף בדפדפן headless ומחזיר רשימת כרטיסים. זורק חריגה אם Playwright לא זמין/נכשל."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"))
        try:
            pg.goto(url, timeout=60000, wait_until="domcontentloaded")
            pg.wait_for_timeout(2500)
            for _ in range(15):                 # גלילה כדי לטעון תמונות עצלות
                pg.mouse.wheel(0, 3000); pg.wait_for_timeout(350)
            pg.wait_for_timeout(1200)
            cards = pg.evaluate(JS_EXTRACT)
        finally:
            b.close()
    return cards or []

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def norm_floor_map():
    floors = load_json(FLOORS_FILE, {}).get("floors", {})
    return {norm(k): v for k, v in floors.items()}

def match_card(name, cards_by_norm, aliases):
    """מוצא כרטיס תואם לשם חנות (לפי שם או כינוי)."""
    keys = [norm(name)] + [norm(a) for a in (aliases or [])]
    for k in keys:
        if k in cards_by_norm:
            return cards_by_norm[k]
    # התאמה חלקית
    for k in keys:
        for ck, card in cards_by_norm.items():
            if k and (k in ck or ck in k) and len(k) >= 3:
                return card
    return None

def main():
    existing = load_json(OUT, {"stores": []})
    prev = existing.get("stores", [])
    floors = norm_floor_map()
    report = {}

    # רינדור שני האתרים (או שמירת קיים אם נכשל)
    site_cards = {}
    for key, mall, url, city in SITES:
        try:
            cards = render_cards(url)
            if len(cards) < MIN_OK[key]:
                raise RuntimeError(f"only {len(cards)} cards (<{MIN_OK[key]})")
            site_cards[key] = {norm(c["name"]): c for c in cards if c.get("name")}
            report[key] = {"status": "rendered", "cards": len(cards)}
        except Exception as e:
            site_cards[key] = None
            report[key] = {"status": "render_failed", "error": str(e)[:150]}
            print(f"[{key}] רינדור נכשל: {e}")

    stores = []
    # 1) עדכון החנויות הקיימות
    seen_ids = set()
    for s in prev:
        key = s.get("mall_key")
        cards_by_norm = site_cards.get(key)
        rec = dict(s)
        rec["aliases"] = aliases_for(s["name"], ALIAS_GROUPS)
        if cards_by_norm:  # רינדור הצליח -> נצרף לוגו אמיתי
            card = match_card(s["name"], cards_by_norm, rec["aliases"])
            if card and card.get("image"):
                rec["image"] = card["image"]                 # לוגו אמיתי מהאתר
            if card and card.get("floor") and not rec.get("floor"):
                rec["floor"] = card["floor"]
            if card and card.get("phone") and not rec.get("phone"):
                rec["phone"] = card["phone"]
        # גיבוי: אם אין לוגו אמיתי — פאביקון לפי דומיין
        if not rec.get("image"):
            rec["image"] = logo_for(s["name"], rec["aliases"], BRANDS)
        stores.append(rec)
        seen_ids.add(rec["id"])

    # 2) הוספת חנויות חדשות שנמצאו באתר ולא היו אצלנו
    for key, mall, url, city in SITES:
        cards_by_norm = site_cards.get(key)
        if not cards_by_norm:
            continue
        existing_norm = {norm(s["name"]) for s in stores if s["mall_key"] == key}
        for cn, card in cards_by_norm.items():
            if cn in existing_norm:
                continue
            name = card["name"]
            al = aliases_for(name, ALIAS_GROUPS)
            floor = card.get("floor") or (floors.get(norm(name)) if key == "savyonim" else None)
            _id = sid(mall, name)
            if _id in seen_ids:
                continue
            seen_ids.add(_id)
            stores.append({
                "id": _id, "name": name, "mall": mall, "mall_key": key,
                "floor": floor, "category": "כללי", "phone": card.get("phone"),
                "hours": None, "aliases": al,
                "image": card.get("image") or logo_for(name, al, BRANDS),
                "url": url,
            })
            report.setdefault(key, {}).setdefault("added", []).append(name)

    data = {
        "updated_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": "scraper",
        "malls": [{"key": k, "name": m, "city": c} for k, m, u, c in SITES],
        "count": len(stores),
        "stores": stores,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    real_logos = sum(1 for s in stores if s.get("image") and "google.com/s2" not in (s["image"] or ""))
    print("\n===== סיכום ריצה =====")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'סה"כ {len(stores)} חנויות; מתוכן {real_logos} עם לוגו אמיתי מהאתר.')
    if all(v.get("status") == "render_failed" for v in report.values()):
        print("שני האתרים נכשלו ברינדור — נשמרו הנתונים הקודמים.")
        sys.exit(1)

if __name__ == "__main__":
    main()
