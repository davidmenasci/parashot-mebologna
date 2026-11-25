#!/usr/bin/env python3
"""Costruisce il catalogo dei commenti alla parashà (data.json).

Legge dal sito della Comunità Ebraica di Bologna solo titolo, data, autore e
link di ogni commento. I testi non vengono copiati: l'app rimanda al sito.

Uso:  python scripts/build_data.py data/data.json
"""
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pyluach import dates

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:  # lxml è nei requisiti, ma se manca si usa il parser standard
    PARSER = "html.parser"

BASE = "https://www.comunitaebraicabologna.it"
INDICE = BASE + "/it/shabbat/commento-della-parasha"
USER_AGENT = "ParashotMeBologna/1.0 (catalogo di link ai commenti)"
INTESTAZIONI = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
}
PAUSA = 0.4          # secondi tra una richiesta e l'altra, per non pesare sul sito
MIN_COMMENTI = 50    # sotto questa soglia il risultato è considerato sospetto
RIGHE_AUTORE = 12    # quante righe dopo il titolo cercare la riga "Di Nome Cognome"

# Ordine canonico della lettura della Torah (gli slug sono quelli del sito).
# Categorie non elencate qui vengono messe in coda al loro libro.
ORDINE_LIBRI = [
    "sefer-bereshit-genesi", "sefer-shemot-esodo", "sefer-vaikra-levitico",
    "sefer-bemidbar-numeri", "sefer-devarim-deuteronomio",
]
ORDINE_PARASHOT = [
    # Genesi
    "bereshit", "noach", "lekh-lekha", "va-jera", "chaje-sara", "toledot",
    "va-jezze", "vaishlach", "vayeshev", "mikketz", "vaiggash", "vaishi",
    # Esodo
    "shemot", "vaera", "bo", "beshallach", "itro", "mishpatim", "teruma",
    "tezzave", "ki-tissa", "va-jakhel-pekude",
    # Levitico
    "vaikra", "tzav", "shemini", "tazri-a-mezzora", "achare-mot-kedoshim",
    "emor", "behar", "bechuccotai",
    # Numeri
    "bemidbar", "naso", "beha-alotecha", "shelach-lekha", "korach", "chuccat",
    "balak", "pinechas", "mattot-mas-e",
    # Deuteronomio
    "devarim", "vaetchannan", "ekev", "reeh", "shofetim", "ki-tezze",
    "ki-tavo", "nizzavim-vayelekh",
]

MESI = {"gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
        "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12}
CONNETTIVI = {"de", "del", "della", "di", "da", "dei", "degli", "van", "ben", "bar"}
RE_CATEGORIA = re.compile(r"/commento-della-parasha/(sefer-[^/]+)(?:/([^/]+))?$")
RE_ARTICOLO = re.compile(r"/(\d+)-[^/]+$")

ESITO = {}                  # ultimo esito di rete, usato dalla diagnostica
DIAGNOSTICHE_MOSTRATE = 0   # la diagnostica compare al massimo due volte per esecuzione


# ---------------------------------------------------------------- rete

def get(sessione, url):
    """Scarica una pagina e la restituisce come BeautifulSoup (None se fallisce)."""
    for tentativo in range(4):
        try:
            r = sessione.get(url, timeout=30)
            ESITO.update(url=url, status=r.status_code, finale=r.url, byte=len(r.content))
            if r.status_code == 200:
                time.sleep(PAUSA)
                return BeautifulSoup(r.text, PARSER)
            if r.status_code == 404:
                return None
            print(f"  HTTP {r.status_code} su {url}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  errore di rete su {url}: {e}", file=sys.stderr)
        time.sleep(2 * (tentativo + 1))
    return None


# ---------------------------------------------------------------- utilità

def slugify(testo):
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def pulisci(testo):
    return " ".join(testo.split())


def leggi_data(titolo, url):
    """Data dal titolo ('Reeh (8 agosto 2026)') o, in alternativa, dall'indirizzo."""
    for testo in (titolo, urlparse(url).path.replace("-", " ")):
        for g, mese, a in re.findall(r"(\d{1,2})\s+([A-Za-zàèéìòù]+)\s+(\d{4})", testo):
            m = MESI.get(mese.lower()[:3])
            if m:
                try:
                    return date(int(a), m, int(g))
                except ValueError:
                    pass
    return None


def anno_ebraico(d):
    return dates.GregorianDate(d.year, d.month, d.day).to_heb().year


def autore_plausibile(s):
    parole = s.split()
    if not 1 <= len(parole) <= 6 or len(s) > 60:
        return False
    return all(p[0].isupper() or p.lower() in CONNETTIVI for p in parole)


def chiave_ordine(slug, elenco, posizione_scoperta):
    return (elenco.index(slug), 0) if slug in elenco else (len(elenco), posizione_scoperta)


# ---------------------------------------------------------------- scoperta categorie

def raccogli_link_categorie(soup, pagina, libri, parashot):
    """Aggiunge a libri/parashot le categorie trovate nei link della pagina."""
    for a in soup.find_all("a", href=True):
        path = urlparse(urljoin(pagina, a["href"])).path.rstrip("/")
        m = RE_CATEGORIA.search(path)
        if not m:
            continue
        libro, par = m.groups()
        nome = pulisci(a.get_text())
        if par is None:
            if nome:
                libri.setdefault(libro, nome.replace("/", " / "))
        elif nome and nome.lower() not in {"leggi tutto...", "avanti", "indietro", "fine", "inizio"}:
            parashot.setdefault((libro, par), nome)


def scopri_categorie(sessione):
    soup = get(sessione, INDICE)
    if soup is None:
        sys.exit("Impossibile leggere l'indice dei commenti sul sito.")
    libri, parashot = {}, {}
    raccogli_link_categorie(soup, INDICE, libri, parashot)
    # Le pagine dei libri possono elencare categorie che il menu non mostra.
    for libro in list(libri):
        pagina = f"{INDICE}/{libro}"
        soup_libro = get(sessione, pagina)
        if soup_libro is not None:
            raccogli_link_categorie(soup_libro, pagina, libri, parashot)
    return libri, parashot


# ---------------------------------------------------------------- lettura articoli
# L'estrazione parte dai link agli articoli, non da un tipo preciso di intestazione:
# così funziona sia se i titoli sono <h2>, sia <h3>, sia se non hanno intestazione.

def url_articolo(pagina, href):
    """Indirizzo assoluto se il link ha la forma di un articolo (…/1234-titolo), altrimenti None."""
    url = urljoin(pagina, href).split("#")[0]
    return url if RE_ARTICOLO.search(urlparse(url).path) else None


def scegli_titolo(ancore, url):
    """Il testo del link che fa da titolo (non 'Leggi tutto…'); in extremis, ricavato dall'indirizzo."""
    candidati = []
    for a in ancore:
        testo = pulisci(a.get_text())
        if testo and not testo.lower().startswith("leggi"):
            in_titolo = a.find_parent(["h1", "h2", "h3", "h4"]) is not None
            candidati.append((in_titolo, len(testo), testo))
    if candidati:
        return max(candidati)[2]
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    return re.sub(r"^\d+-", "", slug).replace("-", " ").capitalize()


def contenitore_articolo(ancora, pagina, url):
    """Il blocco HTML più grande che contiene solo questo articolo."""
    blocco = ancora
    for _ in range(5):
        padre = blocco.parent
        if padre is None or padre.name in ("body", "html", "[document]"):
            break
        altri = {u for t in padre.find_all("a", href=True)
                 if (u := url_articolo(pagina, t["href"])) and u != url}
        if altri:
            break
        blocco = padre
    return blocco


def leggi_autore(blocco, titolo):
    righe = [r for r in blocco.get_text("\n", strip=True).splitlines() if r]
    inizio = next((i for i, r in enumerate(righe) if titolo in r), -1)
    for r in righe[inizio + 1: inizio + 1 + RIGHE_AUTORE]:
        m = re.match(r"Di\s+(.+)$", r)
        if m and autore_plausibile(m.group(1)):
            return m.group(1).strip()
    return ""


def estrai_articoli(soup, pagina):
    base = urlparse(pagina).path.rstrip("/") + "/"
    per_url = {}
    for a in soup.find_all("a", href=True):
        url = url_articolo(pagina, a["href"])
        if url and urlparse(url).path.startswith(base):
            per_url.setdefault(url, []).append(a)

    articoli = []
    for url, ancore in per_url.items():
        titolo = scegli_titolo(ancore, url)
        articoli.append({
            "id": int(RE_ARTICOLO.search(urlparse(url).path).group(1)),
            "titolo": titolo,
            "url": url,
            "autore": leggi_autore(contenitore_articolo(ancore[0], pagina, url), titolo),
        })
    return articoli


def diagnostica(soup, pagina, articoli):
    """Scrive nel log cosa vede lo script, per capire perché una pagina dà pochi risultati."""
    global DIAGNOSTICHE_MOSTRATE
    if DIAGNOSTICHE_MOSTRATE >= 2:
        return
    DIAGNOSTICHE_MOSTRATE += 1
    p = lambda testo: print("[diagnostica] " + testo)
    p("-" * 60)
    p(f"pagina: {pagina}")
    p(f"esito: HTTP {ESITO.get('status')}, indirizzo finale {ESITO.get('finale')}, "
      f"{ESITO.get('byte')} byte, parser {PARSER}")
    p(f"articoli riconosciuti: {len(articoli)}; con autore: {sum(1 for x in articoli if x['autore'])}")
    for livello in ("h1", "h2", "h3"):
        testi = [pulisci(h.get_text())[:45] for h in soup.find_all(livello)]
        p(f"{livello} ({len(testi)}): {testi[:8]}")
    tutti = [urljoin(pagina, a["href"]) for a in soup.find_all("a", href=True)]
    p(f"link con 'start=': {[u for u in tutti if 'start=' in u][:6]}")
    simili = [u for u in tutti if "/commento-della-parasha/" in u and RE_ARTICOLO.search(urlparse(u).path)]
    p(f"link a forma di articolo: {len(simili)} -> {simili[:8]}")
    prima = soup.find("a", href=lambda h: bool(h) and RE_ARTICOLO.search(urlparse(h).path or ""))
    if prima is not None:
        blocco = prima.find_parent(["article", "div", "li"]) or prima.parent
        p("HTML attorno al primo articolo: " + pulisci(str(blocco))[:1500])
    p("-" * 60)


def start_di(url):
    return int(parse_qs(urlparse(url).query).get("start", ["0"])[0] or 0)


def prossima_pagina(soup, url):
    corrente = start_di(url)
    path = urlparse(url).path.rstrip("/")
    candidati = set()
    for a in soup.find_all("a", href=True):
        h = urljoin(url, a["href"])
        if urlparse(h).path.rstrip("/") == path and "start=" in h and start_di(h) > corrente:
            candidati.add(start_di(h))
    return f"{url.split('?')[0]}?start={min(candidati)}" if candidati else None


def articoli_categoria(sessione, url):
    visti, tutti = set(), []
    pagina = url
    for _ in range(40):  # limite di sicurezza
        soup = get(sessione, pagina)
        if soup is None:
            break
        articoli = estrai_articoli(soup, pagina)
        if pagina == url and (len(articoli) <= 1 or not any(x["autore"] for x in articoli)):
            diagnostica(soup, pagina, articoli)
        nuovi = [x for x in articoli if x["url"] not in visti]
        if not nuovi:
            break
        for x in nuovi:
            visti.add(x["url"])
            tutti.append(x)
        pagina = prossima_pagina(soup, pagina)
        if not pagina:
            break
    return tutti


# ---------------------------------------------------------------- principale

def costruisci(sessione):
    libri, parashot = scopri_categorie(sessione)
    print(f"Trovati {len(libri)} libri e {len(parashot)} parashot sul sito.")

    ordine_scoperta = {chiave: i for i, chiave in enumerate(parashot)}
    commenti, visti = [], set()
    libri_out = []

    for libro in sorted(libri, key=lambda s: chiave_ordine(s, ORDINE_LIBRI, 0)):
        voci = sorted(
            (k for k in parashot if k[0] == libro),
            key=lambda k: chiave_ordine(k[1], ORDINE_PARASHOT, ordine_scoperta[k]),
        )
        elenco = []
        for _, par in voci:
            nome = parashot[(libro, par)]
            articoli = articoli_categoria(sessione, f"{INDICE}/{libro}/{par}")
            aggiunti = 0
            for art in articoli:
                if art["url"] in visti:
                    continue
                visti.add(art["url"])
                d = leggi_data(art["titolo"], art["url"])
                commenti.append({
                    "id": art["id"],
                    "parasha": par,
                    "titolo": art["titolo"],
                    "data": d.isoformat() if d else None,
                    "anno_ebraico": anno_ebraico(d) if d else None,
                    "autore": art["autore"],
                    "url": art["url"],
                })
                aggiunti += 1
            print(f"  {nome:<28} {aggiunti:>3} commenti")
            elenco.append({"slug": par, "nome": nome})
        libri_out.append({"slug": libro, "nome": libri[libro], "parashot": elenco})

    commenti.sort(key=lambda c: c["id"])
    return libri_out, commenti


def main(percorso_uscita):
    sessione = requests.Session()
    sessione.headers.update(INTESTAZIONI)
    libri, commenti = costruisci(sessione)

    senza_data = sum(1 for c in commenti if not c["data"])
    senza_autore = sum(1 for c in commenti if not c["autore"])
    print(f"Totale: {len(commenti)} commenti "
          f"({senza_data} senza data, {senza_autore} senza autore).")

    if len(commenti) < MIN_COMMENTI:
        sys.exit(f"Risultato sospetto: solo {len(commenti)} commenti (minimo {MIN_COMMENTI}). "
                 "Non aggiorno i dati.")

    piu_recente = max(commenti, key=lambda c: (c["data"] or "", c["id"]))
    dati = {
        "generato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corrente": piu_recente["parasha"],
        "libri": libri,
        "commenti": commenti,
    }
    with open(percorso_uscita, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)
    print(f"Scritto {percorso_uscita}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/data.json")
