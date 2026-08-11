# -*- coding: utf-8 -*-
"""עזר משותף: ממפה שם חנות → URL של לוגו, לפי data/domains.json.
משתמש בשירות הפאביקון של גוגל (חינמי, ללא מפתח, זמין תמיד). אם אין דומיין מתאים -> None,
ואז הממשק מציג עיגול ראשי-תיבות."""
import json, os
from aliases_util import norm

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DOMAINS_FILE = os.path.join(_ROOT, "data", "domains.json")

def load_brands():
    try:
        with open(_DOMAINS_FILE, encoding="utf-8") as f:
            brands = json.load(f).get("brands", [])
    except Exception:
        return []
    out = []
    for b in brands:
        names = [norm(n) for n in b.get("names", []) if norm(n)]
        if b.get("domain") and names:
            out.append({"domain": b["domain"], "names": names})
    return out

def _match(mn, name_n):
    if not mn or not name_n:
        return False
    if len(mn) <= 2:
        return mn == name_n or mn in name_n.split()
    return mn in name_n or name_n in mn

def logo_url(domain):
    return f"https://www.google.com/s2/favicons?sz=128&domain={domain}"

def logo_for(name, aliases, brands):
    """מחזיר URL לוגו לפי שם החנות או אחד מכינוייה; אחרת None."""
    candidates = [norm(name)] + [norm(a) for a in (aliases or [])]
    for b in brands:
        for mn in b["names"]:
            if any(_match(mn, c) for c in candidates):
                return logo_url(b["domain"])
    return None
