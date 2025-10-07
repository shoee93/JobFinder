#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مشروع: JobFinder (نسخة عربية مُشَرَّحة)
--------------------------------------
هذا السكربت يبحث عن وظائف من خلاصات RSS لمواقع التوظيف،
ثم يحلّل نصوص الإعلانات ويقارنها مع كلمات مفتاحية تحددها أنت.
بعدها يرتّب النتائج حسب درجة التطابق، يحفظها في قاعدة بيانات SQLite وملف CSV،
ويولّد خطابات تقديم (Anschreiben) جاهزة مبنية على قالب.
"""

# -----------------------------
# 1) استيراد المكتبات الضرورية
# -----------------------------
import os
import re
import csv
import hashlib
import sqlite3
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

import feedparser                 # لقراءة خلاصات RSS
import requests                   # لجلب صفحات الويب
from bs4 import BeautifulSoup     # لتحليل HTML واستخراج النصوص
import pandas as pd               # لتصدير النتائج إلى CSV/Excel
from dateutil import parser as dateparser  # لتحليل وتحويل التواريخ النصية
# -----------------------------
import spacy  # تحليل لغوي ألماني
nlp = spacy.load("de_core_news_sm")
# -----------------------------
# 2) الإعدادات 
# -----------------------------
CONFIG = {
    "user": {
        # بياناتك الشخصية التي ستظهر في خطاب التقديم
        "name": "Saddam Wahan",
        "email": "shoyemen2017@gmail.com",
        "phone": "+49 17656774776",
        "profile_summary": (
            "Kurz zu mir: Ich habe Biomedizintechnik studiert, lerne derzeit Python und interessiere mich für Künstliche Intelligenz sowie Embedded Systems."

        ),
        # مدينة/مدن تفضّلها (اختياري: تُستخدم لزيادة النقاط عند التطابق)
        "preferred_cities": ["Dresden", "Nürnberg", "Erlangen", "Berlin"]
    },
    "feeds": [
        # أمثلة لروابط RSS من Indeed (يمكنك التعديل والإضافة)
        "https://de.indeed.com/rss?q=Medizintechnik+Praktikum&l=Dresden",
        "https://de.indeed.com/rss?q=Software+Praktikum&l=Dresden",
        "https://www.stepstone.de/rss/stellenangebote?what=Python&where=Deutschland",],

        # يمكنك إضافة روابط RSS أخرى هنا
    "keywords": [
        # الكلمات المفتاحية (كل كلمة تُطابق ترفع النقاط)
        "Medizintechnik", "Biomedical", "Python", "C++", "Embedded",
        "Praktikum", "Werkstudent", "Quality", "Regulatory", "MDR", "FDA",
        "Signalverarbeitung", "Dresden", "Nürnberg", "Erlangen"
    ],
    # عدد أفضل الوظائف التي سيتم توليد خطابات تقديم لها
    "top_n_letters": 3,
    # اسم قاعدة البيانات المحلية
    "db_path": "jobs.db",
    # اسم ملف التصدير
    "csv_path": "jobs_export.csv",
    # مهلة الجلب من الويب والثبات (ثواني)
    "http_timeout": 15,
    "sleep_between_requests": 0.8,
    # User-Agent لتقليل الحظر من بعض المواقع
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# --------------------------------------
# 3) دوال مساعدة: قاعدة البيانات SQLite
# --------------------------------------
def init_db(db_path: str) -> None:
    """إنشاء جدول قاعدة البيانات إن لم يكن موجوداً."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                company TEXT,
                location TEXT,
                link TEXT UNIQUE,
                published TEXT,
                summary TEXT,
                score REAL,
                source TEXT,
                created_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_job(db_path: str, job: Dict[str, Any]) -> None:
    """إدراج الوظيفة في القاعدة (تجاهل إذا موجودة بنفس الرابط)."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO jobs
            (title, company, location, link, published, summary, score, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                job.get("title"),
                job.get("company"),
                job.get("location"),
                job.get("link"),
                job.get("published"),
                job.get("summary"),
                job.get("score", 0.0),
                job.get("source"),
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_all_jobs(db_path: str) -> List[Dict[str, Any]]:
    """قراءة كل الوظائف من القاعدة مرتّبة حسب النقاط (score) تنازلياً."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs ORDER BY score DESC, published DESC;")
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

# ------------------------------
# 4) دوال: جلب وتحليل الخلاصات
# ------------------------------
def fetch_rss_entries(feed_url: str) -> List[Dict[str, Any]]:
    """قراءة خلاصات RSS وإرجاع قائمة إدخالات (entries)."""
    parsed = feedparser.parse(feed_url)
    entries = []
    for e in parsed.entries:
        entry = {
            "title": e.get("title", "").strip(),
            "link": e.get("link", "").strip(),
            "summary": (e.get("summary", "") or e.get("description", "") or "").strip(),
            "published": extract_published(e),
            "source": feed_url,
        }
        entries.append(entry)
    return entries


def extract_published(entry: Any) -> str:
    """محاولة استخراج تاريخ النشر من عناصر RSS المختلفة وتحويله لصيغة ISO."""
    # نحاول عدة حقول محتملة
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = dateparser.parse(val)
                return dt.isoformat(timespec="seconds")
            except Exception:
                pass
    # إذا لم نجد تاريخاً صالحاً، نستخدم تاريخ اليوم
    return datetime.utcnow().isoformat(timespec="seconds")


def fetch_page_text(url: str, timeout: int, ua: str) -> str:
    """جلب صفحة الويب واستخراج نصها (بدون وسوم HTML)."""
    try:
        headers = {"User-Agent": ua}
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # إزالة السكربتات والستايلات
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text
    except Exception:
        return ""
    # ---------------------------------
# 🔍 NEU: Websuche (deutschlandweite Jobs über Google)
# ---------------------------------
def search_jobs_online(query: str, max_results: int = 15) -> list:
    """
    Sucht Jobs direkt über Google (nicht nur RSS).
    Gibt eine Liste von URLs zurück, die wahrscheinlich Jobanzeigen enthalten.
    """
    from urllib.parse import quote
    url = f"https://www.google.com/search?q={quote(query)}+site:indeed.com+OR+site:stepstone.de+OR+site:adzuna.de+OR+site:workwise.io+OR+site:kimeta.de"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")

    links = []
    for a in soup.select("a"):
        href = a.get("href", "")
        if href.startswith("/url?q="):
            clean = href.split("/url?q=")[1].split("&")[0]
            if "http" in clean and "google" not in clean:
                links.append(clean)
    return links[:max_results]


# ---------------------------------
# 5) دوال: التحليل وتوليد النقاط
# ---------------------------------
def safe_lower(s: str) -> str:
    """Wandelt den Text sicher in Kleinbuchstaben um."""
    try:
        return s.lower()
    except Exception:
        return s


def contains_negation(text: str) -> bool:
    """
    Prüft, ob der Text eine Verneinung enthält (z. B. kein, keine, keinen, nicht).
    Gibt True zurück, wenn eine Verneinung erkannt wird.
    """
    doc = nlp(text)
    for token in doc:
        # dep_ == "neg" bedeutet, das Wort ist eine Verneinung im Satz
        if token.dep_ == "neg" or token.text.lower() in ["kein", "keine", "keinen", "nicht"]:
            return True
    return False


def count_keyword_hits(text: str, keywords: List[str]) -> int:
    """عدّ مرات ظهور الكلمات المفتاحية في النص (بشكل تقريبي)."""
    text_low = safe_lower(text)
    score = 0
    for kw in keywords:
        kw_low = kw.lower()
        # نستخدم بحثاً بسيطاً (يمكن تطويره لاحقاً إلى Regex بكلمات كاملة)
        hits = text_low.count(kw_low)
        score += hits
    return score


def boost_for_city(text: str, preferred_cities: List[str]) -> int:
    """زيادة نقاط إذا ظهر اسم مدينة مفضّلة في النص."""
    text_low = safe_lower(text)
    return sum(text_low.count(city.lower()) for city in preferred_cities)


def heuristic_company_location(title: str, summary: str) -> (str, str):
    """
    استخراج الشركة والمدينة بشكل تقريبي من العنوان والملخص.
    - ملاحظة: هذا مجرد تخمين بسيط، قد لا يكون دقيقاً دائماً.
    """
    combined = f"{title} // {summary}"
    # محاولة استخراج المدينة (كلمات تنتهي بـ GmbH ليست مدن!)
    loc_match = re.search(r"\b(Berlin|Dresden|München|Munich|Hamburg|Erlangen|Nürnberg|Frankfurt|Stuttgart|Leipzig)\b", combined)
    location = loc_match.group(0) if loc_match else ""

    # محاولة استخراج الشركة (كلمات قبل GmbH/AG/SE وما شابه)
    comp_match = re.search(r"\b([A-Z][A-Za-z0-9&.\- ]{1,40})\s+(GmbH|AG|SE|KG|GmbH & Co\. KG)", combined)
    company = comp_match.group(0) if comp_match else ""

    return company, location


def score_job_entry(entry: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Berechnet die Punktzahl einer Stelle und bereitet die Felder (Firma/Stadt/Zusammenfassung) vor."""
    
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    link = entry.get("link", "")
    published = entry.get("published", "")
    source = entry.get("source", "")

    # Versucht, den vollständigen Text der Webseite zu laden, um die Genauigkeit zu erhöhen
    page_text = fetch_page_text(link, cfg["http_timeout"], cfg["user_agent"])
    combined_text = " ".join([title, summary, page_text])

    # 🔍 Neue Funktion: prüft, ob der Text eine Verneinung enthält (z. B. kein, nicht, ...)
    if contains_negation(combined_text):
        print(f"⏩ Anzeige übersprungen (enthält Verneinung): {title}")
        return {
            "title": title,
            "company": "",
            "location": "",
            "link": link,
            "published": published,
            "summary": summary,
            "score": 0.0,   # keine Punkte, weil irrelevant
            "source": source,
        }

    # Wenn keine Verneinung vorhanden ist → Punkte normal berechnen
    base_score = count_keyword_hits(combined_text, cfg["keywords"])
    city_boost = boost_for_city(combined_text, cfg["user"]["preferred_cities"])
    final_score = base_score + city_boost

    company, location = heuristic_company_location(title, summary)

    # Kürzere Zusammenfassung
    short_summary = (summary[:280] + "…") if len(summary) > 300 else summary

    return {
        "title": title,
        "company": company,
        "location": location,
        "link": link,
        "published": published,
        "summary": short_summary,
        "score": float(final_score),
        "source": source,
    }

# ----------------------------------------
# 6) التصدير إلى CSV وتوليد خطابات التقديم
# ----------------------------------------
def export_to_csv(db_path: str, csv_path: str) -> None:
    """تصدير كل الوظائف إلى ملف CSV مرتّبة حسب النقاط."""
    rows = fetch_all_jobs(db_path)
    if not rows:
        print("لا توجد وظائف لحفظها بعد.")
        return
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, quoting=csv.QUOTE_ALL)
    print(f"✅ تم إنشاء الملف: {csv_path}")


def generate_cover_letter(job: Dict[str, Any], user: Dict[str, Any]) -> str:
    """توليد خطاب تقديم (بالألمانية) مبني على القالب والمعلومات المتاحة."""
    company = job.get("company") or "Ihr Unternehmen"
    job_title = job.get("title") or "Ihre Stelle"
    city = job.get("location") or "Ihre Stadt"
    summary = job.get("summary") or ""

    letter = f"""Sehr geehrte Damen und Herren,

auf die Stelle als *{job_title}* bei *{company}* in *{city}* bin ich mit großem Interesse gestoßen.
Kurz zu mir: {user.get('profile_summary','')}

Aus der Stellenbeschreibung (Auszug):
{summary}

Ich bin überzeugt, dass mein Profil und meine Motivation gut zu den Anforderungen passen.
Gerne überzeuge ich Sie in einem persönlichen Gespräch.

Mit freundlichen Grüßen,
{user.get('name','')}
{user.get('email','')} | {user.get('phone','')}
"""
    return letter


def generate_top_letters(db_path: str, user: Dict[str, Any], top_n: int = 3) -> List[str]:
    """توليد خطابات تقديم لأعلى N وظائف حسب النقاط، وإرجاع النصوص."""
    rows = fetch_all_jobs(db_path)[:top_n]
    letters = []
    for idx, job in enumerate(rows, 1):
        letter = generate_cover_letter(job, user)
        # حفظ كل خطاب في ملف نصّي منفصل
        fname = f"anschreiben_{idx}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(letter)
        print(f"✉️  تم إنشاء الخطاب: {fname}")
        letters.append(letter)
    if not letters:
        print("لا توجد وظائف كافية لتوليد خطابات تقديم بعد.")
    return letters

# ------------------------------
# ------------------------------
# 7) الدالة الرئيسية لتنفيذ الخطوات
# ------------------------------
def main():
    # Datenbank vorbereiten
    init_db(CONFIG["db_path"])

    # -------------------------------
    # 1️⃣ RSS-Feeds (wie bisher)
    # -------------------------------
    total_found = 0
    for feed in CONFIG["feeds"]:
        print(f"📥 Lese RSS-Feed: {feed}")
        entries = fetch_rss_entries(feed)
        print(f"  ↳ {len(entries)} Einträge gefunden.")

        for e in entries:
            job_row = score_job_entry(e, CONFIG)
            upsert_job(CONFIG["db_path"], job_row)
            total_found += 1
            time.sleep(CONFIG["sleep_between_requests"])

    # -------------------------------
    # 2️⃣ Neue Online-Suche (Google)
    # -------------------------------
    print("\n🌍 Starte erweiterte Internetsuche ...")
    keywords_to_search = [
        "Medizintechnik Praktikum Deutschland",
        "Werkstudent Biomedical Engineering",
        "Embedded Systems Engineer",
        "Python Developer MedTech",
    ]

    for query in keywords_to_search:
        print(f"🔎 Suche: {query}")
        links = search_jobs_online(query)
        print(f"  ↳ {len(links)} Ergebnisse gefunden.")

        for link in links:
            page_text = fetch_page_text(link, CONFIG["http_timeout"], CONFIG["user_agent"])
            if not page_text:
                continue

            entry = {
                "title": query,
                "link": link,
                "summary": page_text[:500],
                "published": datetime.utcnow().isoformat(timespec="seconds"),
                "source": "Google Search",
            }

            job_row = score_job_entry(entry, CONFIG)
            upsert_job(CONFIG["db_path"], job_row)
            total_found += 1
            time.sleep(CONFIG["sleep_between_requests"])

    # -------------------------------
    # 3️⃣ Ergebnisse anzeigen und speichern
    # -------------------------------
    print(f"\n✅ Gesamtanzahl verarbeiteter Anzeigen: {total_found}")

    rows = fetch_all_jobs(CONFIG["db_path"])[:10]
    if not rows:
        print("⚠️ Keine passenden Jobs gefunden.")
    else:
        print("\n🏆 Top 10 Ergebnisse:")
        for i, r in enumerate(rows, 1):
            print(f"{i:02d}. [{r.get('score',0):>3}] {r.get('title','')} — {r.get('company','')} — {r.get('location','')}")
            print(f"     {r.get('link','')}")

    # Export
    export_to_csv(CONFIG["db_path"], CONFIG["csv_path"])
    generate_top_letters(CONFIG["db_path"], CONFIG["user"], CONFIG["top_n_letters"])

    print("\n✅ JobFinder-Skript abgeschlossen.")


# ------------------------------
# 8) نقطة الدخول (Programmstart)
# ------------------------------
if __name__ == "__main__":
    print("🚀 JobFinder wurde gestartet!")
    main()

