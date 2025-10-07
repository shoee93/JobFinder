# JobFinder

Ein intelligentes Python-Tool zur automatischen Jobsuche, Bewertung und Generierung von Anschreiben.  
Das Projekt wurde entwickelt, um den Bewerbungsprozess zu vereinfachen und KI-gestützt relevante Stellenanzeigen zu finden und zu analysieren.

---

##  Ziel des Projekts

Der JobFinder durchsucht automatisch Jobbörsen und RSS-Feeds, filtert passende Stellen nach bestimmten Kriterien (z. B. Ort, Berufsfeld, Keywords)  
und kann anschließend mit Hilfe von **Künstlicher Intelligenz (AI/NLP) ein passendes Anschreiben generieren.

Dadurch soll der zeitaufwändige Prozess der Jobsuche und Bewerbung deutlich effizienter und automatisierter werden.


##  Funktionen

✅ Automatische Jobsuche über RSS-Feeds oder Websuche  
✅ Bewertung der gefundenen Stellenanzeigen nach Relevanz  
✅ Speicherung der Ergebnisse in einer **SQLite-Datenbank 
✅ Generierung individueller Anschreiben mit Hilfe von NLP (Natural Language Processing)**  
✅ Mehrsprachige Ausgabe (Deutsch / Arabisch)  
✅ Möglichkeit zur Erweiterung mit APIs von Indeed, Stepstone oder LinkedIn

---

## 🧰 Technologien

- Programmiersprache: Python  
- Bibliotheken:  
  - `feedparser` – zum Auslesen von RSS-Feeds  
  - `spacy` – für Textanalyse und Sprachverarbeitung  
  - `sqlite3` – zur Speicherung von Jobdaten  
  - `time`, `json`, `requests` – für Datenmanagement und Webabfragen  
- Künstliche Intelligenz: just try
  Nutzung von Textverarbeitung und NLP-Methoden zur Bewertung von Jobangeboten

---

## Aufbau des Projekts

| Datei | Beschreibung |
|-------|---------------|
| `jobfinder_optimized.py` | Hauptskript mit der KI-Logik für Suche, Bewertung und Datenbankverwaltung |
| `jobfinder_arabic.py` | Version mit arabischer Ausgabe und Sprachunterstützung |
| `jobs.db` | SQLite-Datenbank mit gespeicherten Jobangeboten |
| `test_spacy.py` | Testdatei für die Sprachverarbeitung mit spaCy |
| `README.md` | Diese Dokumentation |
| `LICENSE` | MIT-Lizenz |

---

## ▶️ Nutzung

1. Repository klonen:
   ```bash
   git clone https://github.com/shoee93/JobFinder.git
