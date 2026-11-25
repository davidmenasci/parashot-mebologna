#!/usr/bin/env python3
"""Costruisce l'archivio dei commenti alla parashà della Comunità Ebraica di Bologna.

Uso:  python scripts/build_data.py data

Scrive nella cartella indicata:
  data.json         indice: libri, parashot, commenti (data, anno ebraico, autore, link)
  testi/<id>.json   testo ripulito di ciascun commento (solo tag sicuri)
  ricerca.json      testo semplice di tutti i commenti, per la ricerca nell'app

I testi già scaricati non vengono riscaricati, tranne gli ultimi pubblicati (per
cogliere eventuali correzioni). Se un testo non si riesce a estrarre, l'app mostra
il collegamento alla pagina originale sul sito.
"""
import html as htmllib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString
from pyluach import dates

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:  # lxml è nei requisiti, ma se manca si usa il parser standard
    PARSER = "html.parser"

BASE = "https://www.comunitaebraicabologna.it"
INDICE = BASE + "/it/shabbat/commento-della-parasha"
USER_AGENT = "ParashotMeBologna/1.0 (archivio dei commenti alla parashà)"
INTESTAZIONI = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
}
PAUSA = 0.4                    # secondi tra una richiesta e l'altra, per non pesare sul sito
MIN_COMMENTI = 50              # sotto questa soglia il risultato è considerato sospetto
RIGHE_AUTORE = 12              # righe dopo il titolo, nell'elenco, dove cercare "Di Nome Cognome"
RECENTI_DA_RIAGGIORNARE = 4    # gli ultimi commenti si riscaricano sempre (correzioni)
MIN_CARATTERI_TESTO = 100      # sotto questa lunghezza il testo estratto non è considerato valido

# I due autori dei commenti: qualunque forma del nome viene ricondotta a queste.
AUTORI_NOTI = {"sermoneta": "Rav Alberto Sermoneta", "del monte": "Rav Marco Del Monte"}

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
RE_NIQQUD = re.compile("[֑-ׇ]")  # vocali e cantillazione ebraiche
# Elementi che, nel testo letto da una persona, vanno a capo.
BLOCCHI = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section",
           "article", "table", "tr", "td", "th", "dl", "dt", "dd", "header", "footer",
           "aside", "nav", "blockquote", "main", "figure", "figcaption", "form"]

# ---- estrazione del testo di un commento
SELETTORI_CORPO = [
    '[itemprop="articleBody"]', ".com-content-article__body", ".article-body", ".entry-content",
    ".item-page", "article", "#content", "main", "[role='main']",
]
SELETTORI_RUMORE = (
    "nav, footer, aside, script, style, noscript, form, iframe, "
    ".article-info, .pager, .pagenav, .pagination, .icons, .btn-group, .tags, .jcomments, "
    "[class*='share'], [class*='social'], [class*='addthis'], [class*='breadcrumb']"
)
MARCATORI_MENU = ("Orari funzione in Tempio", "Orari inizio e fine Shabbat", "Bologna ebraica")
TAG_DA_SCARTARE = {"script", "style", "noscript", "iframe", "form", "nav", "footer", "aside",
                   "button", "svg", "img", "picture", "video", "audio", "object", "embed",
                   "input", "select", "textarea", "head", "map", "canvas"}
TAG_TITOLO = {"h1", "h2", "h3", "h4", "h5", "h6"}
TAG_BLOCCO = {"p", "div", "section", "article", "main", "header", "table", "tbody", "thead",
              "tfoot", "tr", "td", "th", "center", "figure", "figcaption", "dl", "dt", "dd",
              "li", "address", "fieldset", "details", "summary"}
TAG_IN_LINEA = {"strong": "strong", "b": "strong", "em": "em", "i": "em", "u": "u",
                "sup": "sup", "sub": "sub"}
RE_RUMORE = re.compile(
    r"^(visite|hits|pubblicato|scritto da|categoria|ultima modifica|data di pubblicazione|"
    r"stampa|e-?mail|leggi tutto|torna su|dettagli)\b", re.I)

ESITO = {}                  # ultimo esito di rete, usato dalla diagnostica
DIAGNOSTICHE_MOSTRATE = 0   # diagnostica degli elenchi: al massimo due volte per esecuzione
DIAG_TESTI_OK = 0           # diagnostica dei testi: i primi due estratti con successo...
DIAG_TESTI_KO = 0           # ...e i primi tre falliti


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


def normalizza_autore(nome):
    """Riporta le varianti ('Marco Del Monte', 'Rav Marco Del Monte') alla forma canonica."""
    if not nome:
        return ""
    chiaro = nome.lower()
    for chiave, canonico in AUTORI_NOTI.items():
        if chiave in chiaro:
            return canonico
    return pulisci(nome)


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


# ---------------------------------------------------------------- elenco degli articoli di una categoria
# L'estrazione parte dai link agli articoli, non da un tipo preciso di intestazione:
# così funziona qualunque sia il tag del titolo e comunque sia annidata la pagina.

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


def righe_pagina(soup, pagina):
    """Il testo della pagina diviso in righe come le leggerebbe una persona.

    I tag "in linea" (span, strong, ecc.) non spezzano la riga; i blocchi e gli a-capo sì.
    Restituisce [(testo, [indirizzi degli articoli linkati in quella riga]), ...]."""
    radice = soup.body or soup
    righe, testo, urls, in_attesa = [], [], [], []
    ultimo_blocco = None

    def chiudi():
        nonlocal testo, urls
        t = pulisci("".join(testo))
        if t or urls:
            righe.append((t, urls))
        testo, urls = [], []

    for nodo in radice.descendants:
        if type(nodo) is NavigableString:  # esclude commenti e simili
            if nodo.find_parent(["script", "style", "noscript"]):
                continue
            blocco = nodo.find_parent(BLOCCHI)
            if blocco is not ultimo_blocco:
                chiudi()
                ultimo_blocco = blocco
            urls.extend(in_attesa)
            in_attesa = []
            testo.append(str(nodo))
        elif nodo.name == "br":
            chiudi()
        elif nodo.name == "a" and nodo.get("href"):
            u = url_articolo(pagina, nodo["href"])
            if u:
                in_attesa.append(u)
    chiudi()
    return righe


def autori_da_righe(righe):
    """Per ogni articolo, la riga 'Di Nome Cognome' che segue il suo titolo (se compare nell'elenco)."""
    prima_riga = {}
    for i, (_, urls) in enumerate(righe):
        for u in urls:
            prima_riga.setdefault(u, i)
    autori = {}
    for u, i in prima_riga.items():
        for testo, urls in righe[i + 1: i + 1 + RIGHE_AUTORE]:
            if any(x != u for x in urls):  # comincia un altro articolo: ci si ferma
                break
            m = re.match(r"Di\s+(.+)$", testo)
            if m and autore_plausibile(m.group(1)):
                autori[u] = m.group(1).strip()
                break
    return autori


def estrai_articoli(soup, pagina):
    base = urlparse(pagina).path.rstrip("/") + "/"
    per_url = {}
    for a in soup.find_all("a", href=True):
        url = url_articolo(pagina, a["href"])
        if url and urlparse(url).path.startswith(base):
            per_url.setdefault(url, []).append(a)

    righe = [(t, [u for u in urls if u in per_url]) for t, urls in righe_pagina(soup, pagina)]
    autori = autori_da_righe(righe)

    return [{
        "id": int(RE_ARTICOLO.search(urlparse(url).path).group(1)),
        "titolo": scegli_titolo(ancore, url),
        "url": url,
        "autore": autori.get(url, ""),
    } for url, ancore in per_url.items()]


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
    p(f"articoli riconosciuti: {len(articoli)}")
    tutti = [urljoin(pagina, a["href"]) for a in soup.find_all("a", href=True)]
    p(f"link con 'start=': {[u for u in tutti if 'start=' in u][:6]}")
    p(f"h1: {[pulisci(h.get_text())[:45] for h in soup.find_all('h1')][:5]}")
    p(f"h2: {[pulisci(h.get_text())[:45] for h in soup.find_all('h2')][:8]}")
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
        if pagina == url and len(articoli) <= 1:
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


# ---------------------------------------------------------------- testo di un commento
# Il corpo della pagina viene convertito in un piccolo insieme di tag sicuri
# (paragrafi, grassetto, corsivo, citazioni, elenchi, link http/https): niente script,
# stili o attributi del sito. Ogni blocco riceve dir="auto" così l'ebraico va da destra a sinistra.

def html_in_linea(n, buf):
    """Accumula in buf il contenuto 'in linea' di un nodo; i tag sconosciuti vengono aperti."""
    if isinstance(n, NavigableString):
        if type(n) is NavigableString:  # esclude commenti e simili
            buf.append(htmllib.escape(str(n).replace("\xa0", " "), quote=False))
        return
    nome = n.name
    if nome in TAG_DA_SCARTARE:
        return
    if nome == "br":
        buf.append("<br>")
        return
    if nome in TAG_IN_LINEA:
        marcatore = TAG_IN_LINEA[nome]
        buf.append(f"<{marcatore}>")
        for c in n.children:
            html_in_linea(c, buf)
        buf.append(f"</{marcatore}>")
        return
    if nome == "a":
        href = (n.get("href") or "").strip()
        if re.match(r"https?://", href, re.I):
            buf.append(f'<a href="{htmllib.escape(href, quote=True)}" target="_blank" rel="noopener">')
            for c in n.children:
                html_in_linea(c, buf)
            buf.append("</a>")
            return
    for c in n.children:  # span, font, ecc.: si conserva solo il contenuto
        html_in_linea(c, buf)
    if nome in TAG_BLOCCO:
        buf.append("<br>")


def solo_testo(html):
    return pulisci(htmllib.unescape(re.sub(r"<[^>]+>", "", html.replace("<br>", " "))))


def converti_blocchi(radice):
    """Il contenuto di un elemento come lista di blocchi: ('p'|'h', html), ('q', [blocchi]), ('ul'|'ol', [html])."""
    blocchi, riga = [], []

    def chiudi():
        html = "".join(riga)
        riga.clear()
        for parte in re.split(r"(?:<br>\s*){2,}", html):
            parte = re.sub(r"^(?:\s|<br>)+|(?:\s|<br>)+$", "", parte)
            if parte and solo_testo(parte):
                blocchi.append(("p", parte))

    def visita(n):
        if isinstance(n, NavigableString):
            if type(n) is NavigableString:
                riga.append(htmllib.escape(str(n).replace("\xa0", " "), quote=False))
            return
        nome = n.name
        if nome in TAG_DA_SCARTARE:
            return
        if nome in TAG_TITOLO:
            chiudi()
            buf = []
            for c in n.children:
                html_in_linea(c, buf)
            html = "".join(buf)
            if solo_testo(html):
                blocchi.append(("h", re.sub(r"^(?:\s|<br>)+|(?:\s|<br>)+$", "", html)))
        elif nome == "blockquote":
            chiudi()
            interni = converti_blocchi(n)
            if interni:
                blocchi.append(("q", interni))
        elif nome in ("ul", "ol"):
            chiudi()
            voci = []
            for li in n.find_all("li", recursive=False):
                buf = []
                for c in li.children:
                    html_in_linea(c, buf)
                voce = re.sub(r"^(?:\s|<br>)+|(?:\s|<br>)+$", "", "".join(buf))
                if solo_testo(voce):
                    voci.append(voce)
            if voci:
                blocchi.append((nome, voci))
        elif nome in TAG_BLOCCO:
            chiudi()
            for c in n.children:
                visita(c)
            chiudi()
        else:
            html_in_linea(n, riga)

    for c in radice.children:
        visita(c)
    chiudi()
    return blocchi


def testo_blocco(blocco):
    tipo, c = blocco
    if tipo in ("p", "h"):
        return solo_testo(c)
    if tipo == "q":
        return " ".join(testo_blocco(b) for b in c)
    return " ".join(solo_testo(v) for v in c)


def rendi_blocchi(blocchi):
    out = []
    for tipo, c in blocchi:
        if tipo == "p":
            out.append(f'<p dir="auto">{c}</p>')
        elif tipo == "h":
            out.append(f'<h4 dir="auto">{c}</h4>')
        elif tipo == "q":
            out.append(f"<blockquote>{rendi_blocchi(c)}</blockquote>")
        else:
            voci = "".join(f'<li dir="auto">{v}</li>' for v in c)
            out.append(f"<{tipo}>{voci}</{tipo}>")
    return "".join(out)


def html_a_testo(html):
    """Testo semplice di un html prodotto da rendi_blocchi, un paragrafo per riga."""
    t = re.sub(r"<br\s*/?>", "\n", html)
    t = re.sub(r"</(?:p|h\d|li|blockquote|ul|ol)>", "\n", t)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", t))
    return "\n".join(r for r in (pulisci(x) for x in t.split("\n")) if r)


def estrai_autore_da_blocchi(blocchi):
    """Cerca la riga 'Di Nome Cognome' tra i primi blocchi; se la trova la toglie dal testo."""
    for i, (tipo, c) in enumerate(blocchi[:4]):
        if tipo not in ("p", "h"):
            continue
        segmenti = re.split(r"<br>\s*", c)
        primo = solo_testo(segmenti[0])
        m = re.match(r"Di\s+(.+)$", primo)
        if m and autore_plausibile(m.group(1)):
            resto = "<br>".join(segmenti[1:]).strip()
            if resto:
                blocchi[i] = (tipo, resto)
            else:
                del blocchi[i]
            return m.group(1).strip()
    return ""


def autore_da_regione(regione):
    righe = [pulisci(r) for r in regione.get_text("\n").splitlines() if r.strip()]
    for r in righe[:25]:
        m = re.match(r"Di\s+(.+)$", r)
        if m and autore_plausibile(m.group(1)):
            return m.group(1).strip()
    return ""


def togli_titolo_e_rumore(blocchi, titolo):
    # il titolo della pagina ("Reeh (8 agosto 2026)") non va ripetuto nel testo
    nome_parasha = titolo.split("(")[0].strip().lower()
    while blocchi and blocchi[0][0] == "h":
        t = testo_blocco(blocchi[0])
        if len(t) < 90 and (leggi_data(t, "") or (nome_parasha and t.lower().startswith(nome_parasha))):
            del blocchi[0]
        else:
            break
    return [b for b in blocchi
            if not (b[0] in ("p", "h") and len(testo_blocco(b)) < 80 and RE_RUMORE.match(testo_blocco(b)))]


def corpo_valido(tag):
    testo = pulisci(tag.get_text(" "))
    return len(testo) >= 150 and not any(m in testo for m in MARCATORI_MENU)


def estrai_testo(soup, titolo):
    """Testo ripulito di un commento: {'html', 'autore', 'selettore', 'caratteri'} oppure None."""
    for el in soup.select(SELETTORI_RUMORE):
        el.extract()
    corpo, selettore = None, None
    for sel in SELETTORI_CORPO:
        for el in soup.select(sel):
            if corpo_valido(el):
                corpo, selettore = el, sel
                break
        if corpo is not None:
            break
    if corpo is None:
        return None

    blocchi = converti_blocchi(corpo)
    autore = estrai_autore_da_blocchi(blocchi)
    if not autore:
        regione = corpo.find_parent("article") or corpo.find_parent(class_="item-page") or corpo.parent or corpo
        autore = autore_da_regione(regione)
    blocchi = togli_titolo_e_rumore(blocchi, titolo)
    while blocchi and re.fullmatch(r"shabbat shalom[\s!.]*", testo_blocco(blocchi[-1]), re.I):
        blocchi.pop()  # la chiusa fissa "Shabbat Shalom" non fa parte del commento

    html = rendi_blocchi(blocchi)
    testo = html_a_testo(html)
    if len(testo) < MIN_CARATTERI_TESTO:
        return None
    return {"html": html, "autore": normalizza_autore(autore), "selettore": selettore,
            "caratteri": len(testo), "blocchi": len(blocchi)}


def diagnostica_testo(art, risultato, soup):
    """Mostra nel log i primi esiti, per controllare che l'estrazione sia sensata."""
    global DIAG_TESTI_OK, DIAG_TESTI_KO
    if risultato:
        if DIAG_TESTI_OK >= 2:
            return
        DIAG_TESTI_OK += 1
    else:
        if DIAG_TESTI_KO >= 3:
            return
        DIAG_TESTI_KO += 1
    p = lambda testo: print("[diagnostica testo] " + testo)
    p("-" * 60)
    p(f"articolo: {art['url']}")
    if risultato:
        p(f"estratto con '{risultato['selettore']}': {risultato['caratteri']} caratteri, "
          f"{risultato['blocchi']} blocchi, autore: {risultato['autore'] or 'non trovato'}")
        for riga in risultato["html"].replace("</p>", "</p>\n").splitlines()[:3]:
            p("   " + solo_testo(riga)[:80])
    else:
        p("testo NON estratto. Elementi candidati:")
        for sel in SELETTORI_CORPO:
            trovati = soup.select(sel)
            if trovati:
                p(f"   {sel}: {len(trovati)} elementi, lunghezze testo "
                  f"{[len(pulisci(t.get_text(' '))) for t in trovati[:3]]}")
    p("-" * 60)


# ---------------------------------------------------------------- archivio dei testi

def aggiorna_testi(sessione, cartella, commenti):
    """Scarica i testi mancanti (e gli ultimi pubblicati); imposta c['testo'] e c['autore_pagina']."""
    cartella_testi = os.path.join(cartella, "testi")
    os.makedirs(cartella_testi, exist_ok=True)
    recenti = {c["id"] for c in sorted(commenti, key=lambda c: (c["data"] or "", c["id"]),
                                       reverse=True)[:RECENTI_DA_RIAGGIORNARE]}
    scaricati = falliti = gia_presenti = 0
    da_fare = [c for c in commenti
               if c["id"] in recenti or not os.path.exists(os.path.join(cartella_testi, f"{c['id']}.json"))]
    print(f"Testi: {len(commenti) - len(da_fare)} già presenti, {len(da_fare)} da scaricare.")

    for c in sorted(commenti, key=lambda c: c["id"], reverse=True):
        percorso = os.path.join(cartella_testi, f"{c['id']}.json")
        esiste = os.path.exists(percorso)
        risultato = None
        if c in da_fare:
            try:
                soup = get(sessione, c["url"])
                risultato = estrai_testo(soup, c["titolo"]) if soup is not None else None
                if soup is not None:
                    diagnostica_testo(c, risultato, soup)
            except Exception as e:  # una pagina difettosa non deve fermare tutto
                print(f"  problema con {c['url']}: {e}", file=sys.stderr)
            if risultato:
                with open(percorso, "w", encoding="utf-8") as f:
                    json.dump({"id": c["id"], "autore": risultato["autore"], "html": risultato["html"],
                               "scaricato": date.today().isoformat()}, f, ensure_ascii=False)
                scaricati += 1
                esiste = True
            else:
                falliti += 1
            if (scaricati + falliti) % 50 == 0:
                print(f"  testi scaricati: {scaricati + falliti}/{len(da_fare)}")
        if esiste:
            c["testo"] = True
            try:
                with open(percorso, encoding="utf-8") as f:
                    c["autore_pagina"] = json.load(f).get("autore", "")
            except (OSError, ValueError):
                c["autore_pagina"] = ""
        else:
            c["testo"] = False
    print(f"Testi: {scaricati} scaricati, {falliti} non estratti, "
          f"{sum(1 for c in commenti if c['testo'])}/{len(commenti)} disponibili.")


def deduci_autori(commenti):
    """Assegna gli autori mancanti in base alla data, dato che gli autori sono due e si sono succeduti."""
    s, d = AUTORI_NOTI["sermoneta"], AUTORI_NOTI["del monte"]
    date_s = [c["data"] for c in commenti if c["autore"] == s and c["data"]]
    date_d = [c["data"] for c in commenti if c["autore"] == d and c["data"]]
    if not date_s or not date_d:
        return 0
    ultimo_s, primo_d = max(date_s), min(date_d)
    n = 0
    for c in commenti:
        if c["autore"] or not c["data"]:
            continue
        if c["data"] < primo_d and c["data"] <= ultimo_s:
            c["autore"] = s
            n += 1
        elif c["data"] > ultimo_s and c["data"] >= primo_d:
            c["autore"] = d
            n += 1
    return n


def scrivi_ricerca(cartella, commenti):
    """ricerca.json: [[id, testo semplice], ...], un commento per riga (diff piccoli su git)."""
    righe = []
    for c in sorted(commenti, key=lambda c: c["id"]):
        if not c.get("testo"):
            continue
        try:
            with open(os.path.join(cartella, "testi", f"{c['id']}.json"), encoding="utf-8") as f:
                html = json.load(f)["html"]
        except (OSError, ValueError, KeyError):
            continue
        righe.append(json.dumps([c["id"], RE_NIQQUD.sub("", html_a_testo(html))], ensure_ascii=False))
    with open(os.path.join(cartella, "ricerca.json"), "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(righe) + "\n]\n")
    return len(righe)


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


def main(destinazione):
    # per compatibilità si accetta anche il vecchio argomento "data/data.json"
    cartella = (os.path.dirname(destinazione) or ".") if destinazione.endswith(".json") else destinazione
    sessione = requests.Session()
    sessione.headers.update(INTESTAZIONI)
    libri, commenti = costruisci(sessione)

    print(f"Totale: {len(commenti)} commenti "
          f"({sum(1 for c in commenti if not c['data'])} senza data).")
    if len(commenti) < MIN_COMMENTI:
        sys.exit(f"Risultato sospetto: solo {len(commenti)} commenti (minimo {MIN_COMMENTI}). "
                 "Non aggiorno i dati.")

    os.makedirs(cartella, exist_ok=True)
    aggiorna_testi(sessione, cartella, commenti)

    for c in commenti:
        c["autore"] = normalizza_autore(c.pop("autore_pagina", "") or c["autore"])
    dedotti = deduci_autori(commenti)
    conteggio = {}
    for c in commenti:
        conteggio[c["autore"] or "(mancante)"] = conteggio.get(c["autore"] or "(mancante)", 0) + 1
    print(f"Autori: {conteggio} (di cui {dedotti} dedotti dalla data)")

    piu_recente = max(commenti, key=lambda c: (c["data"] or "", c["id"]))
    dati = {
        "generato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corrente": piu_recente["parasha"],
        "libri": libri,
        "commenti": commenti,
    }
    with open(os.path.join(cartella, "data.json"), "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=1)
    n_ricerca = scrivi_ricerca(cartella, commenti)
    print(f"Scritti data.json e ricerca.json ({n_ricerca} testi) in {cartella}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
