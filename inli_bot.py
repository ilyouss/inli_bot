"""
Bot de surveillance inli.fr + Action Logement → Notification Telegram
Vérifie toutes les 30 minutes les nouvelles offres de location
"""

import requests
import json
import time
import os
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
#  ⚙️  CONFIGURATION
# ============================================================

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TKN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- inli.fr ---
INLI_URL = (
    "https://www.inli.fr/locations/offres/val-doise-departement_d:95"
    "?price_min=0&price_max=1200&area_min=0&area_max=250&bedroom_min=2&bedroom_max=5"
)

# --- Action Logement ---
AL_URL = "https://api.logement-actionlogement.fr/api/v1/demands/public/offers-overview?size=200&page=0"
AL_PAYLOAD = {
    "municipalities": [
        {"code": "95582", "postcode": "95110"},  # Sannois
        {"code": "95252", "postcode": "95130"},  # Franconville
        {"code": "95219", "postcode": "95120"},  # Ermont
        {"code": "95555", "postcode": "95210"},  # Saint-Gratien
        {"code": "95491", "postcode": "95130"},  # Le Plessis-Bouchard
        {"code": "95176", "postcode": "95240"},  # Cormeilles-en-Parisis
        {"code": "95574", "postcode": "95390"},  # Saint-Leu-la-Forêt
        {"code": "95018", "postcode": "95100"},  # Argenteuil
        {"code": "95203", "postcode": "95600"},  # Eaubonne
        {"code": "95306", "postcode": "95220"},  # Herblay
        {"code": "95488", "postcode": "95220"},  # Pierrelaye
    ],
    "searchRadiusInKm": 1,
    "maxRent": 1155,
    "typologyCodes": ["T3"],
    "productGuids": ["712f4424-7590-4912-8ed8-f192b26557f8"],
}

# Fichiers de sauvegarde séparés par source
INLI_DATA_FILE = "inli_seen.json"
AL_DATA_FILE   = "al_seen.json"

# Intervalle de vérification (secondes) — 1800 = 30 min
CHECK_INTERVAL = 1800

# ============================================================


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


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


def load_seen(filepath: str) -> set:
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set, filepath: str):
    with open(filepath, "w") as f:
        json.dump(list(seen), f)


# ============================================================
#  inli.fr — scraping HTML
# ============================================================

def scrape_inli() -> list[dict]:
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
        print(f"[{now()}] ❌ inli.fr — erreur scraping : {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    annonces = []
    seen_hrefs = set()

    for card in soup.select("a[href*='/locations/offre/']"):
        href = card.get("href", "")
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        annonce_id = "inli_" + href.split("/")[-1]

        title_el    = card.select_one("h2, h3, .card-title, [class*='title']")
        title       = title_el.get_text(strip=True) if title_el else "Appartement"

        price_el    = card.select_one("[class*='price'], [class*='loyer'], [class*='rent']")
        price       = price_el.get_text(strip=True) if price_el else "Prix non précisé"

        details_els = card.select("[class*='surface'], [class*='room'], [class*='piece']")
        details     = " | ".join(el.get_text(strip=True) for el in details_els)

        full_url = f"https://www.inli.fr{href}" if href.startswith("/") else href

        annonces.append({
            "id": annonce_id, "title": title,
            "url": full_url,  "price": price, "details": details,
        })

    print(f"[{now()}] 🔍 inli.fr — {len(annonces)} annonce(s) trouvée(s)")
    return annonces


def check_inli():
    seen     = load_seen(INLI_DATA_FILE)
    annonces = scrape_inli()

    if not annonces:
        print(f"[{now()}] ⚠️  inli.fr — aucune annonce récupérée")
        return

    new_ones = [a for a in annonces if a["id"] not in seen]

    if new_ones:
        print(f"[{now()}] 🆕 inli.fr — {len(new_ones)} nouvelle(s) annonce(s) !")
        for a in new_ones:
            msg = f"🏠 <b>Nouvelle offre in'li !</b>\n\n📌 <b>{a['title']}</b>\n💶 {a['price']}\n"
            if a["details"]:
                msg += f"📐 {a['details']}\n"
            msg += f"\n🔗 <a href='{a['url']}'>Voir l'annonce</a>"
            send_telegram(msg)
            seen.add(a["id"])
    else:
        print(f"[{now()}] ✔️  inli.fr — aucune nouvelle annonce")

    save_seen(seen | {a["id"] for a in annonces}, INLI_DATA_FILE)


# ============================================================
#  Action Logement — API REST
# ============================================================

def fetch_action_logement() -> list[dict]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        response = requests.post(AL_URL, json=AL_PAYLOAD, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[{now()}] ❌ Action Logement — erreur API : {e}")
        return []

    annonces = []

    # La réponse contient la liste des logements dans le champ "data"
    offers = data.get("data") or data.get("content") or data.get("offers") or (data if isinstance(data, list) else [])

    for offer in offers:
        guid = str(offer.get("guid") or offer.get("id") or offer.get("offerId") or "")
        if not guid:
            continue

        annonce_id = "al_" + guid

        title   = offer.get("title") or offer.get("label") or "Logement Action Logement"
        rent    = offer.get("totalRentAmountBaseBound") or offer.get("rent") or offer.get("price") or ""
        price   = f"{rent} €/mois" if rent else "Prix non précisé"

        city    = (offer.get("municipality") or {}).get("name") or offer.get("city") or ""
        surface = (offer.get("lodging") or {}).get("area") or offer.get("surface") or ""
        typo    = offer.get("typologyCode") or offer.get("typology") or ""

        raw_date = offer.get("startDateOfPublication") or ""
        if raw_date:
            try:
                from datetime import datetime
                date_pub = datetime.fromisoformat(raw_date[:10]).strftime("%d/%m/%Y")
            except Exception:
                date_pub = raw_date[:10]
        else:
            date_pub = ""

        details = " | ".join(filter(None, [typo, f"{surface} m²" if surface else "", city]))

        offer_url = f"https://logement-actionlogement.fr/search/detail/{guid}"

        annonces.append({
            "id": annonce_id, "title": title,
            "url": offer_url,  "price": price, "details": details,
            "date_pub": date_pub,
        })

    print(f"[{now()}] 🔍 Action Logement — {len(annonces)} annonce(s) trouvée(s)")
    return annonces


def check_action_logement():
    seen     = load_seen(AL_DATA_FILE)
    annonces = fetch_action_logement()

    if not annonces:
        print(f"[{now()}] ⚠️  Action Logement — aucune annonce récupérée")
        return

    new_ones = [a for a in annonces if a["id"] not in seen]

    if new_ones:
        print(f"[{now()}] 🆕 Action Logement — {len(new_ones)} nouvelle(s) annonce(s) !")
        for a in new_ones:
            msg = f"🏢 <b>Nouvelle offre Action Logement !</b>\n\n📌 <b>{a['title']}</b>\n💶 {a['price']}\n"
            if a["details"]:
                msg += f"📐 {a['details']}\n"
            if a.get("date_pub"):
                msg += f"📅 Publié le {a['date_pub']}\n"
            msg += f"\n🔗 <a href='{a['url']}'>Voir l'annonce</a>"
            send_telegram(msg)
            seen.add(a["id"])
    else:
        print(f"[{now()}] ✔️  Action Logement — aucune nouvelle annonce")

    save_seen(seen | {a["id"] for a in annonces}, AL_DATA_FILE)


# ============================================================
#  MAIN
# ============================================================

def main():
    print("=" * 50)
    print("🤖 Bot logement démarré (inli.fr + Action Logement)")
    print(f"⏱️  Vérification toutes les {CHECK_INTERVAL // 60} minutes")
    print("=" * 50)

    send_telegram(
        "✅ <b>Bot logement démarré !</b>\n"
        f"Je surveille <b>inli.fr</b> et <b>Action Logement</b> "
        f"toutes les {CHECK_INTERVAL // 60} min."
    )

    while True:
        print(f"\n[{now()}] === Vérification en cours ===")
        check_inli()
        check_action_logement()
        print(f"[{now()}] ⏳ Prochaine vérification dans {CHECK_INTERVAL // 60} min...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()