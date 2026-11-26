#!/usr/bin/env python3
"""Controllo veloce: c'è un commento nuovo sul sito?

Non scarica tutto l'archivio: guarda soltanto le pagine delle prossime parashot
rispetto a quella dell'ultimo commento noto (di norma 3 richieste). Scrive nell'output
di GitHub Actions `completo=true` se trova un commento che non è in data/data.json,
altrimenti `completo=false`. Per sicurezza, in caso di errore di rete risponde false:
il controllo successivo (30 minuti dopo) riprova.

Uso:  python scripts/controlla_nuovo.py data
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests  # noqa: E402

import build_data as b  # noqa: E402

ORDINE = list(b.ORDINE_PARASHOT)
# nel sito Haazinu è una categoria a sé, dopo Nizzavim/Vayelekh
if "nizzavim-vayelekh" in ORDINE and "haazinu" not in ORDINE:
    ORDINE.insert(ORDINE.index("nizzavim-vayelekh") + 1, "haazinu")
PROSSIME = 3
ORA_INIZIO, ORA_FINE = 9, 14   # finestra dei controlli, ora italiana (il venerdì)


def candidate(corrente):
    if corrente in ORDINE:
        i = ORDINE.index(corrente)
        return [ORDINE[(i + k) % len(ORDINE)] for k in range(1, PROSSIME + 1)]
    return ORDINE[:PROSSIME]


def scrivi_esito(completo):
    testo = f"completo={'true' if completo else 'false'}"
    print(testo)
    percorso = os.environ.get("GITHUB_OUTPUT")
    if percorso:
        with open(percorso, "a", encoding="utf-8") as f:
            f.write(testo + "\n")


def main(cartella):
    adesso = datetime.now(ZoneInfo("Europe/Rome"))
    if os.environ.get("IGNORA_ORARIO") != "1" and not (adesso.weekday() == 4 and ORA_INIZIO <= adesso.hour < ORA_FINE):
        print(f"Fuori dalla finestra dei controlli ({adesso:%A %H:%M}).")
        scrivi_esito(False)
        return
    with open(os.path.join(cartella, "data.json"), encoding="utf-8") as f:
        dati = json.load(f)
    noti = {c["id"] for c in dati["commenti"]}
    libro_di = {p["slug"]: l["slug"] for l in dati["libri"] for p in l["parashot"]}

    sessione = requests.Session()
    sessione.headers.update(b.INTESTAZIONI)
    try:
        for par in candidate(dati.get("corrente")):
            libro = libro_di.get(par)
            if not libro:
                continue
            for art in b.articoli_categoria(sessione, f"{b.INDICE}/{libro}/{par}"):
                if art["id"] not in noti:
                    print(f"Commento nuovo: {art['titolo']} ({art['url']})")
                    scrivi_esito(True)
                    return
    except Exception as e:  # rete o struttura del sito: si riprova al controllo successivo
        print(f"Controllo non riuscito: {e}", file=sys.stderr)
        scrivi_esito(False)
        return
    print("Nessun commento nuovo.")
    scrivi_esito(False)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
