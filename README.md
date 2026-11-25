# Parashot MeBologna

Guida di consultazione ai commenti settimanali alla parashà pubblicati dalla
Comunità Ebraica di Bologna. Due viste:

- **Per parashà**: scegli una parashà e vedi le edizioni dei diversi anni.
- **Per anno**: scegli un anno ebraico e vedi tutti i suoi commenti, da Bereshit in poi.

I testi dei commenti **non** sono copiati: l'app mostra titolo, data, autore e
rimanda al sito della Comunità.

## Come si aggiorna

Ogni venerdì mattina GitHub esegue `scripts/build_data.py`, che legge le pagine
del sito, aggiorna `data/data.json` e ripubblica l'app. La parashà "di questa
settimana" è quella con il commento pubblicato più di recente.

Per aggiornare subito: scheda **Actions** → **Aggiorna e pubblica** → **Run workflow**.

## Messa online (una volta sola)

1. Crea su GitHub un repository pubblico chiamato `parashot-mebologna`.
2. Carica tutti i file di questa cartella, compresa la cartella nascosta `.github`.
3. In **Settings → Pages**, alla voce *Source* scegli **GitHub Actions**.
4. Vai in **Actions → Aggiorna e pubblica → Run workflow** e attendi la spunta verde.
5. L'indirizzo dell'app è `https://NOME-UTENTE.github.io/parashot-mebologna/`.

## Se qualcosa non va

- Nel log dell'esecuzione (Actions → clic sull'esecuzione → "Raccogli i commenti dal sito")
  c'è l'elenco delle parashot con il numero di commenti trovati per ciascuna.
- Se il sito è irraggiungibile o lo script trova meno di 50 commenti, l'aggiornamento
  si ferma e l'app resta com'era: non viene mai pubblicato un archivio svuotato.
- GitHub può sospendere le esecuzioni programmate dopo 60 giorni senza attività. Qui ogni
  esecuzione salva un nuovo commit, quindi non succede; se capitasse, basta riattivare
  il workflow dalla scheda Actions.
