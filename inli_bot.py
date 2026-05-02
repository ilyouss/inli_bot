"""
Bot de surveillance inli.fr → Notification Telegram
Vérifie toutes les 30 minutes les nouvelles offres de location
"""

import requests
import json
import time
import os
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
#  ⚙️  CONFIGURATION — À REMPLIR AVANT DE LANCER
# ============================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]          # Token de @BotFather
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]       # Ton Chat ID (voir ci-dessous)

# URL de recherche inli.fr — personnalise selon ta zone
# Exemples :
#   Paris           : https://www.inli.fr/locations/offres/paris_d:75
#   Hauts-de-Seine  : https://www.inli.fr/locations/offres/hauts-de-seine_d:92
#   Île-de-France   : https://www.inli.fr/locations/offres/ile-de-france_r:11
INLI_URL = "https://www.inli.fr/locations/offres/val-doise-departement_d:95?price_min=0&price_max=1200&area_min=0&area_max=250&bedroom_min=2&bedroom_max=5"

# Fichier de sauvegarde des annonces déjà vues
DATA_FILE = "inli_seen.json"

# Intervalle de vérification (secondes) — 1800 = 30 min
CHECK_INTERVAL = 1800

# ============================================================


def send_telegram(message: str):
    """Envoie un message via Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[{now()}] ✅ Notification Telegram envoyée")
    except Exception as e:
        print(f"[{now()}] ❌ Erreur Telegram : {e}")


def load_seen() -> set:
    """Charge les IDs d'annonces déjà vues depuis le fichier JSON."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    """Sauvegarde les IDs d'annonces vues."""
    with open(DATA_FILE, "w") as f:
        json.dump(list(seen), f)


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def scrape_inli() -> list[dict]:
    """
    Scrape la page inli.fr et retourne la liste des annonces.
    Chaque annonce : {"id": str, "title": str, "url": str, "price": str, "details": str}
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9",
    }

    try:
        response = requests.get(INLI_URL, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"[{now()}] ❌ Erreur lors du scraping : {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    annonces = []

    # Sélecteurs CSS inli.fr (cartes d'annonces)
    # Le site utilise des cards avec des liens vers /locations/offre/<id>
    cards = soup.select("a[href*='/locations/offre/']")

    seen_ids = set()
    for card in cards:
        href = card.get("href", "")
        if not href or href in seen_ids:
            continue
        seen_ids.add(href)

        # Extraire l'ID unique depuis l'URL
        annonce_id = href.split("/")[-1]

        # Titre
        title_el = card.select_one("h2, h3, .card-title, [class*='title']")
        title = title_el.get_text(strip=True) if title_el else "Appartement"

        # Prix / loyer
        price_el = card.select_one("[class*='price'], [class*='loyer'], [class*='rent']")
        price = price_el.get_text(strip=True) if price_el else "Prix non précisé"

        # Détails (surface, pièces...)
        details_els = card.select("[class*='surface'], [class*='room'], [class*='piece']")
        details = " | ".join(el.get_text(strip=True) for el in details_els) if details_els else ""

        full_url = f"https://www.inli.fr{href}" if href.startswith("/") else href

        annonces.append({
            "id": annonce_id,
            "title": title,
            "url": full_url,
            "price": price,
            "details": details,
        })

    print(f"[{now()}] 🔍 {len(annonces)} annonce(s) trouvée(s) sur la page")
    return annonces


def check_for_new():
    """Vérifie les nouvelles annonces et envoie une notif si besoin."""
    seen = load_seen()
    annonces = scrape_inli()

    if not annonces:
        print(f"[{now()}] ⚠️  Aucune annonce récupérée (site vide ou structure changée)")
        return

    new_ones = [a for a in annonces if a["id"] not in seen]

    if new_ones:
        print(f"[{now()}] 🆕 {len(new_ones)} nouvelle(s) annonce(s) !")
        for a in new_ones:
            msg = (
                f"🏠 <b>Nouvelle offre in'li !</b>\n\n"
                f"📌 <b>{a['title']}</b>\n"
                f"💶 {a['price']}\n"
            )
            if a["details"]:
                msg += f"📐 {a['details']}\n"
            msg += f"\n🔗 <a href='{a['url']}'>Voir l'annonce</a>"
            send_telegram(msg)
            seen.add(a["id"])
        save_seen(seen)
    else:
        print(f"[{now()}] ✔️  Aucune nouvelle annonce")

    # Met à jour le fichier même sans nouvelle annonce (garde les IDs actuels)
    all_ids = {a["id"] for a in annonces}
    save_seen(seen | all_ids)


def main():
    print("=" * 50)
    print("🤖 Bot inli.fr démarré")
    print(f"🔗 URL surveillée : {INLI_URL}")
    print(f"⏱️  Vérification toutes les {CHECK_INTERVAL // 60} minutes")
    print("=" * 50)

    send_telegram(
        "✅ <b>Bot inli.fr démarré !</b>\n"
        f"Je surveille les nouvelles offres toutes les {CHECK_INTERVAL // 60} min.\n"
        f"🔗 {INLI_URL}"
    )

    while True:
        check_for_new()
        print(f"[{now()}] ⏳ Prochaine vérification dans {CHECK_INTERVAL // 60} min...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
