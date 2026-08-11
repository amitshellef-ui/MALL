# -*- coding: utf-8 -*-
"""עזר משותף: טוען את data/aliases.json ומחשב שמות-חיפוש (עברית+אנגלית) לכל חנות."""
import json, os, re, unicodedata

_ROOT = os.path.dirname(os.path.abspath(__file__))
_ALIASES_FILE = os.path.join(_ROOT, "data", "aliases.json")

def norm(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9א-ת]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def load_groups():
    try:
        with open(_ALIASES_FILE, encoding="utf-8") as f:
            raw = json.load(f).get("groups", [])
    except Exception:
        return []
    # מנרמלים כל חבר בקבוצה, שומרים גם את הצורה המקורית להצגה/חיפוש
    groups = []
    for g in raw:
        members = [{"raw": m, "n": norm(m)} for m in g if norm(m)]
        if len(members) >= 2:
            groups.append(members)
    return groups

def _member_matches(mn, name_n):
    """האם חבר-קבוצה mn (מנורמל) מתאים לשם חנות name_n (מנורמל)?"""
    if not mn or not name_n:
        return False
    if len(mn) <= 2:                       # חברים קצרים (ml, be, zip קצר) — התאמה מדויקת/מילה שלמה בלבד
        return mn == name_n or mn in name_n.split()
    return mn in name_n or name_n in mn    # אחרת: הכלה דו-כיוונית

def aliases_for(name, groups):
    """מחזיר רשימת שמות-חיפוש חלופיים לשם נתון (ללא כפילות עם השם עצמו)."""
    name_n = norm(name)
    out = []
    for members in groups:
        if any(_member_matches(m["n"], name_n) for m in members):
            for m in members:
                if m["n"] != name_n and m["raw"] not in out:
                    out.append(m["raw"])
    return out
