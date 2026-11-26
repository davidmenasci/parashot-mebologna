#!/usr/bin/env python3
"""Invia la notifica push (OneSignal) per un commento nuovo, una sola volta.

- Il registro dei commenti già "gestiti" sta in data/notificati.json. Alla prima esecuzione
  il registro viene creato con tutti i commenti esistenti, senza inviare nulla.
- Si notifica solo un commento pubblicato negli ultimi 7 giorni.
- Orario: le notifiche partono solo il venerdì tra le 9:00 e le 14:00 (ora italiana). Un commento
  che esce dopo non viene notificato (comportamento cambiabile con NOTIFICA_TARDIVA).
- Senza ONESIGNAL_APP_ID / ONESIGNAL_API_KEY (segreti di GitHub) non fa nulla.
- `--prova` invia una notifica di prova a tutti gli iscritti, ignorando orario e registro.

Uso:  python scripts/notifica.py data [--prova]
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

APP = "https://davidmenasci.github.io/parashot-mebologna/"
ORA_INIZIO = 9              # ore, ora italiana: non si notifica prima
ORA_LIMITE = 14             # ore, ora italiana: non si notifica dopo
GIORNO_INVIO = 4            # venerdì (lunedì = 0)
GIORNI_MASSIMI = 7          # età massima di un commento "nuovo"
NOTIFICA_TARDIVA = False    # True: se esce dopo le 14 il venerdì, notifica comunque al controllo successivo
API = "https://api.onesignal.com/notifications?c=push"


def invia(titolo, testo, url):
    app_id = os.environ.get("ONESIGNAL_APP_ID", "").strip()
    chiave = os.environ.get("ONESIGNAL_API_KEY", "").strip()
    if not app_id or not chiave:
        print("Chiavi di OneSignal non impostate: nessuna notifica inviata.")
        return None
    corpo = {
        "app_id": app_id,
        "target_channel": "push",
        "included_segments": ["Subscribed Users"],
        "headings": {"en": titolo, "it": titolo},
        "contents": {"en": testo, "it": testo},
        "url": url,
    }
    r = requests.post(API, json=corpo, timeout=30,
                      headers={"Authorization": f"Key {chiave}", "Content-Type": "application/json"})
    print(f"OneSignal: HTTP {r.status_code} {r.text[:300]}")
    return r.ok


def main(cartella, prova=False):
    if prova:
        ok = invia("Prova di notifica", "Se leggi questo messaggio, le notifiche funzionano.", APP)
        sys.exit(0 if ok in (None, True) else 1)

    with open(os.path.join(cartella, "data.json"), encoding="utf-8") as f:
        dati = json.load(f)
    commenti = dati["commenti"]
    nomi = {p["slug"]: p["nome"] for l in dati["libri"] for p in l["parashot"]}
    percorso = os.path.join(cartella, "notificati.json")

    if not os.path.exists(percorso):
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump({"ids": sorted(c["id"] for c in commenti)}, f)
        print("Registro delle notifiche creato con i commenti esistenti: nessun invio.")
        return
    with open(percorso, encoding="utf-8") as f:
        registro = json.load(f)
    gestiti = set(registro["ids"])
    nuovi = [c for c in commenti if c["id"] not in gestiti]
    if not nuovi:
        print("Nessun commento da notificare.")
        return

    adesso = datetime.now(ZoneInfo("Europe/Rome"))
    recenti = [c for c in nuovi if c.get("data") and
               date.fromisoformat(c["data"]) >= adesso.date() - timedelta(days=GIORNI_MASSIMI)]
    if not recenti:
        print("I commenti nuovi sono vecchi: registrati senza notifica.")
    else:
        c = max(recenti, key=lambda x: (x["data"], x["id"]))
        if adesso.weekday() == GIORNO_INVIO and adesso.hour < ORA_INIZIO:
            print("Troppo presto per la notifica: si riprova al primo controllo delle 9.")
            return  # non si registra niente
        orario_ok = adesso.weekday() == GIORNO_INVIO and adesso.hour < ORA_LIMITE
        if not orario_ok and NOTIFICA_TARDIVA and adesso.weekday() != 5:
            orario_ok = True
        if not orario_ok:
            print(f"Fuori orario ({adesso:%A %H:%M}): commento {c['id']} registrato senza notifica.")
        else:
            nome = nomi.get(c["parasha"], c["parasha"])
            sotto = " · ".join(x for x in [c.get("autore"), "tocca per leggere"] if x)
            esito = invia(f"Nuovo commento: {nome}", sotto, f"{APP}#/c/{c['id']}")
            if esito is False:
                sys.exit(1)  # non si registra: il controllo successivo riprova
    registro["ids"] = sorted(gestiti | {c["id"] for c in nuovi})
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(registro, f)


if __name__ == "__main__":
    argomenti = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(argomenti[0] if argomenti else "data", "--prova" in sys.argv)
