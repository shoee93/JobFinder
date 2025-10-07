#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JobFinder - Intelligente Jobsuche mit automatischer Bewertung
==============================================================
Dieses Tool durchsucht RSS-Feeds und das Internet nach relevanten Stellenanzeigen,
analysiert diese anhand definierter Schlüsselwörter und generiert automatisch
personalisierte Bewerbungsanschreiben für die besten Treffer.

Autor: Saddam Wahan
Datum: Oktober 2025
"""

import os
import re
import csv
import sqlite3
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote

import feedparser
import requests
from bs4 import BeautifulSoup
import pandas as pd
from dateutil import parser as dateparser
import spacy

# Logging-Konfiguration für bessere Fehlersuche
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Deutsches Sprachmodell laden
try:
    nlp = spacy.load("de_core_news_sm")
except OSError:
    logger.error("Spacy-Modell 'de_core_news_sm' nicht gefunden. Bitte installieren mit: python -m spacy download de_core_news_sm")
    raise


# =============================================================================
# KONFIGURATION
# =============================================================================

CONFIG = {
    "user": {
        "name": "Saddam Wahan",
        "email": "shoyemen2017@gmail.com",
        "phone": "+49 17656774776",
        "profile_summary": (
            "Ich habe Biomedizintechnik studiert und entwickle derzeit meine "
            "Python-Kenntnisse weiter. Meine Interessen liegen in den Bereichen "
            "Künstliche Intelligenz, Embedded Systems und medizinische Gerätetechnik."
        ),
        "preferred_cities": ["Dresden", "Nürnberg", "Erlangen", "Berlin", "München"]
    },
    
    "feeds": [
        "https://de.indeed.com/rss?q=Medizintechnik+Praktikum&l=Dresden",
        "https://de.indeed.com/rss?q=Software+Praktikum&l=Dresden",
        "https://www.stepstone.de/rss/stellenangebote?what=Python&where=Deutschland",
    ],
    
    "keywords": [
        "Medizintechnik", "Biomedical", "Python", "C++", "Embedded",
        "Praktikum", "Werkstudent", "Quality", "Regulatory", "MDR", "FDA",
        "Signalverarbeitung", "Machine Learning", "KI", "Künstliche Intelligenz"
    ],
    
    "search_queries": [
        "Medizintechnik Praktikum Deutschland",
        "Werkstudent Biomedical Engineering",
        "Embedded Systems Praktikum",
        "Python Developer MedTech",
    ],
    
    "top_n_letters": 5,
    "db_path": "jobs.db",
    "csv_path": "jobs_export.csv",
    "http_timeout": 15,
    "sleep_between_requests": 1.0,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


# =============================================================================
# DATENBANKFUNKTIONEN
# =============================================================================

def init_db(db_path: str) -> None:
    """
    Initialisiert die SQLite-Datenbank und erstellt die Tabelle für Stellenanzeigen.
    
    Args:
        db_path: Pfad zur Datenbankdatei
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT,
                location TEXT,
                link TEXT UNIQUE NOT NULL,
                published TEXT,
                summary TEXT,
                score REAL DEFAULT 0,
                source TEXT,
                created_at TEXT NOT NULL,
                last_updated TEXT
            );
        """)
        
        # Index für schnellere Abfragen
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_score ON jobs(score DESC);
        """)
        
        conn.commit()
        logger.info(f"Datenbank erfolgreich initialisiert: {db_path}")
    except Exception as e:
        logger.error(f"Fehler beim Initialisieren der Datenbank: {e}")
        raise
    finally:
        conn.close()


def upsert_job(db_path: str, job: Dict[str, Any]) -> bool:
    """
    Fügt eine neue Stellenanzeige in die Datenbank ein oder aktualisiert sie.
    
    Args:
        db_path: Pfad zur Datenbankdatei
        job: Dictionary mit Stelleninformationen
        
    Returns:
        True wenn erfolgreich eingefügt, False wenn bereits vorhanden
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        
        # Prüfen, ob Job bereits existiert
        cur.execute("SELECT id FROM jobs WHERE link = ?", (job.get("link"),))
        existing = cur.fetchone()
        
        if existing:
            # Update bei besserer Score
            cur.execute("""
                UPDATE jobs SET 
                    score = ?,
                    last_updated = ?
                WHERE link = ? AND score < ?
            """, (
                job.get("score", 0.0),
                datetime.utcnow().isoformat(),
                job.get("link"),
                job.get("score", 0.0)
            ))
            conn.commit()
            return False
        else:
            # Neuen Eintrag erstellen
            cur.execute("""
                INSERT INTO jobs
                (title, company, location, link, published, summary, score, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.get("title"),
                job.get("company"),
                job.get("location"),
                job.get("link"),
                job.get("published"),
                job.get("summary"),
                job.get("score", 0.0),
                job.get("source"),
                datetime.utcnow().isoformat()
            ))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        logger.debug(f"Job bereits vorhanden: {job.get('link')}")
        return False
    except Exception as e:
        logger.error(f"Fehler beim Speichern des Jobs: {e}")
        return False
    finally:
        conn.close()


def fetch_all_jobs(db_path: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Lädt alle Stellenanzeigen aus der Datenbank, sortiert nach Score.
    
    Args:
        db_path: Pfad zur Datenbankdatei
        limit: Optional - maximale Anzahl zurückzugebender Jobs
        
    Returns:
        Liste von Job-Dictionaries
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        query = "SELECT * FROM jobs WHERE score > 0 ORDER BY score DESC, published DESC"
        if limit:
            query += f" LIMIT {limit}"
        
        cur.execute(query)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Fehler beim Laden der Jobs: {e}")
        return []
    finally:
        conn.close()


# =============================================================================
# WEB-SCRAPING UND RSS-FUNKTIONEN
# =============================================================================

def fetch_rss_entries(feed_url: str) -> List[Dict[str, Any]]:
    """
    Lädt und parst einen RSS-Feed.
    
    Args:
        feed_url: URL des RSS-Feeds
        
    Returns:
        Liste von Einträgen aus dem Feed
    """
    try:
        parsed = feedparser.parse(feed_url)
        
        if parsed.bozo:
            logger.warning(f"RSS-Feed möglicherweise fehlerhaft: {feed_url}")
        
        entries = []
        for e in parsed.entries:
            entry = {
                "title": e.get("title", "").strip(),
                "link": e.get("link", "").strip(),
                "summary": (e.get("summary", "") or e.get("description", "")).strip(),
                "published": extract_published(e),
                "source": feed_url,
            }
            if entry["link"]:  # Nur Einträge mit gültigem Link
                entries.append(entry)
        
        return entries
    except Exception as e:
        logger.error(f"Fehler beim Lesen des RSS-Feeds {feed_url}: {e}")
        return []


def extract_published(entry: Any) -> str:
    """
    Extrahiert und normalisiert das Veröffentlichungsdatum aus einem RSS-Eintrag.
    
    Args:
        entry: RSS-Entry-Objekt
        
    Returns:
        ISO-formatiertes Datum als String
    """
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = dateparser.parse(val)
                return dt.isoformat(timespec="seconds")
            except Exception:
                pass
    
    return datetime.utcnow().isoformat(timespec="seconds")


def fetch_page_text(url: str, timeout: int, ua: str) -> str:
    """
    Lädt eine Webseite und extrahiert den Textinhalt.
    
    Args:
        url: URL der Webseite
        timeout: Timeout in Sekunden
        ua: User-Agent String
        
    Returns:
        Extrahierter Text ohne HTML-Tags
    """
    try:
        headers = {"User-Agent": ua}
        resp = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Entfernen von irrelevanten Elementen
        for element in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            element.decompose()
        
        text = soup.get_text(separator=" ", strip=True)
        return text
    except requests.RequestException as e:
        logger.debug(f"Fehler beim Laden der Seite {url}: {e}")
        return ""
    except Exception as e:
        logger.debug(f"Unerwarteter Fehler bei {url}: {e}")
        return ""


def search_jobs_online(query: str, max_results: int = 15) -> List[str]:
    """
    Sucht Jobs über Google und extrahiert relevante URLs.
    
    Args:
        query: Suchanfrage
        max_results: Maximale Anzahl von Ergebnissen
        
    Returns:
        Liste von URLs
    """
    try:
        search_url = (
            f"https://www.google.com/search?q={quote(query)}"
            "+site:indeed.com+OR+site:stepstone.de+OR+site:adzuna.de"
            "+OR+site:workwise.io+OR+site:xing.com"
        )
        
        headers = {"User-Agent": CONFIG["user_agent"]}
        resp = requests.get(search_url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        links = []
        for a in soup.select("a"):
            href = a.get("href", "")
            if href.startswith("/url?q="):
                clean = href.split("/url?q=")[1].split("&")[0]
                if "http" in clean and "google" not in clean:
                    links.append(clean)
        
        return links[:max_results]
    except Exception as e:
        logger.error(f"Fehler bei der Online-Suche für '{query}': {e}")
        return []


# =============================================================================
# TEXTANALYSE UND BEWERTUNG
# =============================================================================

def contains_negation(text: str) -> bool:
    """
    Prüft, ob der Text Verneinungen enthält (z.B. "kein Praktikum", "nicht erforderlich").
    
    Args:
        text: Zu analysierender Text
        
    Returns:
        True wenn Verneinung gefunden wurde
    """
    try:
        doc = nlp(text[:1000])  # Nur ersten Teil analysieren für Performance
        
        negation_words = {"kein", "keine", "keinen", "nicht", "ohne", "nie", "niemals"}
        
        for token in doc:
            if token.dep_ == "neg" or token.text.lower() in negation_words:
                return True
        
        return False
    except Exception as e:
        logger.debug(f"Fehler bei Negationserkennung: {e}")
        return False


def count_keyword_hits(text: str, keywords: List[str]) -> int:
    """
    Zählt die Treffer von Schlüsselwörtern im Text.
    
    Args:
        text: Zu durchsuchender Text
        keywords: Liste von Schlüsselwörtern
        
    Returns:
        Anzahl der Treffer
    """
    text_lower = text.lower()
    score = 0
    
    for keyword in keywords:
        # Wort-Grenzen beachten für genauere Treffer
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        matches = len(re.findall(pattern, text_lower))
        score += matches
    
    return score


def boost_for_city(text: str, preferred_cities: List[str]) -> int:
    """
    Gibt Bonus-Punkte für bevorzugte Städte.
    
    Args:
        text: Text zur Analyse
        preferred_cities: Liste bevorzugter Städte
        
    Returns:
        Bonus-Punktzahl
    """
    text_lower = text.lower()
    return sum(2 for city in preferred_cities if city.lower() in text_lower)


def extract_company_location(title: str, summary: str) -> Tuple[str, str]:
    """
    Extrahiert Firmenname und Standort aus Titel und Zusammenfassung.
    
    Args:
        title: Titel der Stellenanzeige
        summary: Zusammenfassung der Anzeige
        
    Returns:
        Tuple (Firmenname, Standort)
    """
    combined = f"{title} {summary}"
    
    # Standort extrahieren
    location_pattern = r'\b(Berlin|Dresden|München|Munich|Hamburg|Erlangen|Nürnberg|Frankfurt|Stuttgart|Leipzig|Köln|Düsseldorf|Hannover)\b'
    loc_match = re.search(location_pattern, combined, re.IGNORECASE)
    location = loc_match.group(0) if loc_match else ""
    
    # Firmenname extrahieren
    company_pattern = r'\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9&.\- ]{2,40})\s+(GmbH|AG|SE|KG|GmbH & Co\.\s*KG|e\.V\.|Inc\.|Ltd\.)'
    comp_match = re.search(company_pattern, combined)
    company = comp_match.group(0).strip() if comp_match else ""
    
    return company, location


def score_job_entry(entry: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bewertet eine Stellenanzeige basierend auf Schlüsselwörtern und Relevanz.
    
    Args:
        entry: Dictionary mit Stelleninformationen
        cfg: Konfigurationsdictionary
        
    Returns:
        Bewertetes Job-Dictionary mit Score
    """
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    link = entry.get("link", "")
    published = entry.get("published", "")
    source = entry.get("source", "")
    
    # Seitentext laden für bessere Analyse
    page_text = fetch_page_text(link, cfg["http_timeout"], cfg["user_agent"])
    combined_text = f"{title} {summary} {page_text}"
    
    # Verneinungen prüfen (z.B. "kein Praktikum")
    if contains_negation(combined_text[:500]):
        logger.debug(f"Job übersprungen (Verneinung erkannt): {title}")
        return {
            "title": title,
            "company": "",
            "location": "",
            "link": link,
            "published": published,
            "summary": summary[:300],
            "score": 0.0,
            "source": source,
        }
    
    # Score berechnen
    base_score = count_keyword_hits(combined_text, cfg["keywords"])
    city_boost = boost_for_city(combined_text, cfg["user"]["preferred_cities"])
    final_score = base_score + city_boost
    
    # Firma und Standort extrahieren
    company, location = extract_company_location(title, summary)
    
    # Zusammenfassung kürzen
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


# =============================================================================
# EXPORT UND ANSCHREIBEN-GENERIERUNG
# =============================================================================

def export_to_csv(db_path: str, csv_path: str) -> None:
    """
    Exportiert alle Jobs aus der Datenbank in eine CSV-Datei.
    
    Args:
        db_path: Pfad zur Datenbankdatei
        csv_path: Pfad zur Export-CSV-Datei
    """
    try:
        rows = fetch_all_jobs(db_path)
        
        if not rows:
            logger.warning("Keine Jobs zum Exportieren vorhanden.")
            return
        
        df = pd.DataFrame(rows)
        df = df.sort_values('score', ascending=False)
        df.to_csv(csv_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_ALL)
        
        logger.info(f"✅ {len(rows)} Jobs erfolgreich nach {csv_path} exportiert")
    except Exception as e:
        logger.error(f"Fehler beim CSV-Export: {e}")


def generate_cover_letter(job: Dict[str, Any], user: Dict[str, Any]) -> str:
    """
    Generiert ein personalisiertes Bewerbungsanschreiben.
    
    Args:
        job: Job-Dictionary
        user: User-Konfiguration
        
    Returns:
        Anschreiben als String
    """
    company = job.get("company") or "Ihr Unternehmen"
    job_title = job.get("title") or "die ausgeschriebene Position"
    city = job.get("location") or ""
    location_text = f"in {city}" if city else ""
    
    letter = f"""Sehr geehrte Damen und Herren,

mit großem Interesse bin ich auf Ihre Stellenausschreibung "{job_title}" {location_text} aufmerksam geworden.

{user.get('profile_summary', '')}

Meine Qualifikationen und meine Motivation passen hervorragend zu den Anforderungen der Position. Besonders reizt mich die Möglichkeit, meine technischen Kenntnisse in einem innovativen Umfeld einzubringen und weiterzuentwickeln.

Gerne überzeuge ich Sie in einem persönlichen Gespräch von meinen Fähigkeiten und meiner Begeisterung für diese Position.

Mit freundlichen Grüßen

{user.get('name', '')}
E-Mail: {user.get('email', '')}
Telefon: {user.get('phone', '')}

---
Stellenlink: {job.get('link', '')}
Bewertung: {job.get('score', 0)} Punkte
"""
    return letter


def generate_top_letters(db_path: str, user: Dict[str, Any], top_n: int = 5) -> List[str]:
    """
    Generiert Anschreiben für die Top-N-Jobs.
    
    Args:
        db_path: Pfad zur Datenbankdatei
        user: User-Konfiguration
        top_n: Anzahl der zu generierenden Anschreiben
        
    Returns:
        Liste der generierten Anschreiben
    """
    rows = fetch_all_jobs(db_path, limit=top_n)
    letters = []
    
    output_dir = "bewerbungen"
    os.makedirs(output_dir, exist_ok=True)
    
    for idx, job in enumerate(rows, 1):
        letter = generate_cover_letter(job, user)
        
        # Dateiname sicher erstellen
        safe_title = re.sub(r'[^\w\s-]', '', job.get('title', f'job_{idx}'))[:50]
        fname = os.path.join(output_dir, f"anschreiben_{idx:02d}_{safe_title}.txt")
        
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(letter)
            logger.info(f"✉️  Anschreiben erstellt: {fname}")
            letters.append(letter)
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Anschreibens {fname}: {e}")
    
    if not letters:
        logger.warning("Keine passenden Jobs für Anschreiben gefunden.")
    
    return letters


# =============================================================================
# HAUPTPROGRAMM
# =============================================================================

def main():
    """Hauptfunktion: Koordiniert den gesamten Ablauf."""
    
    logger.info("🚀 JobFinder gestartet!")
    start_time = time.time()
    
    # Datenbank initialisieren
    init_db(CONFIG["db_path"])
    
    total_processed = 0
    new_jobs = 0
    
    # -------------------------
    # 1. RSS-Feeds durchsuchen
    # -------------------------
    logger.info("\n📥 Phase 1: RSS-Feeds werden durchsucht...")
    
    for feed in CONFIG["feeds"]:
        logger.info(f"Lese Feed: {feed}")
        entries = fetch_rss_entries(feed)
        logger.info(f"  ↳ {len(entries)} Einträge gefunden")
        
        for entry in entries:
            job_row = score_job_entry(entry, CONFIG)
            if job_row["score"] > 0:
                if upsert_job(CONFIG["db_path"], job_row):
                    new_jobs += 1
            total_processed += 1
            time.sleep(CONFIG["sleep_between_requests"])
    
    # -------------------------
    # 2. Online-Suche
    # -------------------------
    logger.info("\n🌍 Phase 2: Erweiterte Online-Suche...")
    
    for query in CONFIG["search_queries"]:
        logger.info(f"Suche: {query}")
        links = search_jobs_online(query, max_results=10)
        logger.info(f"  ↳ {len(links)} URLs gefunden")
        
        for link in links:
            page_text = fetch_page_text(link, CONFIG["http_timeout"], CONFIG["user_agent"])
            if not page_text:
                continue
            
            entry = {
                "title": query,
                "link": link,
                "summary": page_text[:500],
                "published": datetime.utcnow().isoformat(),
                "source": "Google Suche",
            }
            
            job_row = score_job_entry(entry, CONFIG)
            if job_row["score"] > 0:
                if upsert_job(CONFIG["db_path"], job_row):
                    new_jobs += 1
            total_processed += 1
            time.sleep(CONFIG["sleep_between_requests"])
    
    # -------------------------
    # 3. Ergebnisse anzeigen
    # -------------------------
    elapsed = time.time() - start_time
    logger.info(f"\n✅ Verarbeitung abgeschlossen in {elapsed:.1f} Sekunden")
    logger.info(f"   Verarbeitete Anzeigen: {total_processed}")
    logger.info(f"   Neue relevante Jobs: {new_jobs}")
    
    top_jobs = fetch_all_jobs(CONFIG["db_path"], limit=10)
    
    if not top_jobs:
        logger.warning("⚠️  Keine passenden Jobs gefunden.")
    else:
        logger.info(f"\n🏆 Top {len(top_jobs)} Stellenangebote:")
        print("\n" + "="*100)
        for i, job in enumerate(top_jobs, 1):
            print(f"{i:2d}. Score: {job.get('score', 0):3.0f} | {job.get('title', '')}")
            if job.get('company'):
                print(f"    Firma: {job.get('company')} | Ort: {job.get('location', 'k.A.')}")
            print(f"    Link: {job.get('link', '')}")
            print("-"*100)
    
    # -------------------------
    # 4. Export und Anschreiben
    # -------------------------
    logger.info("\n📄 Phase 3: Export und Anschreiben-Generierung...")
    export_to_csv(CONFIG["db_path"], CONFIG["csv_path"])
    generate_top_letters(CONFIG["db_path"], CONFIG["user"], CONFIG["top_n_letters"])
    
    logger.info("\n✅ JobFinder erfolgreich beendet!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Programm wurde vom Benutzer abgebrochen.")
    except Exception as e:
        logger.error(f"\n❌ Unerwarteter Fehler: {e}", exc_info=True)