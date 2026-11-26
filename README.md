# Parashot MeBologna

Guida di consultazione ai commenti settimanali alla parashà pubblicati dalla
Comunità Ebraica di Bologna. Due viste:

- **Per parashà**: scegli una parashà e vedi le edizioni dei diversi anni.
- **Per anno**: scegli un anno ebraico e vedi tutti i suoi commenti, da Bereshit in poi.

I commenti si leggono direttamente nell'app (senza rimandi al sito esterno) e si possono cercare per parola o per frase: `"terra promessa"` cerca la frase
esatta; maiuscole e accenti non contano. Gli autori sono Rav Alberto Sermoneta (testi
più vecchi) e Rav Marco Del Monte (testi recenti).

## Come si aggiorna

Ogni venerdì mattina GitHub esegue `scripts/build_data.py`, che legge le pagine
del sito, scarica i testi nuovi (in `data/testi/`), aggiorna l'indice `data/data.json` e il file
di ricerca `data/ricerca.json`, poi ripubblica l'app. Il primo aggiornamento scarica
tutto l'archivio e richiede 10–20 minuti; dopo, pochi secondi. La parashà "di questa
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
- Nel log compaiono anche le righe `[diagnostica testo]` con i primi testi estratti e,
  per i testi non estratti, gli elementi della pagina provati. Un commento senza testo
  compare comunque nell'elenco, con la scritta "Testo non ancora disponibile".
- Se il sito è irraggiungibile o lo script trova meno di 50 commenti, l'aggiornamento
  si ferma e l'app resta com'era: non viene mai pubblicato un archivio svuotato.
- GitHub può sospendere le esecuzioni programmate dopo 60 giorni senza attività. Qui ogni
  esecuzione salva un nuovo commit, quindi non succede; se capitasse, basta riattivare
  il workflow dalla scheda Actions.

## Notifiche push (OneSignal)

Il venerdì, tra le 9:00 e le 14:00 (ora italiana), un controllo leggero gira ogni 30 minuti:
se sul sito c'è un commento nuovo, aggiorna l'archivio, ripubblica l'app e invia **una sola**
notifica a chi le ha attivate (non dopo le 14:00; un commento che esce più tardi non viene
notificato). Il registro dei commenti già gestiti è in `data/notificati.json`.

Messa in funzione (una volta sola):
1. Crea un'app Web su onesignal.com, con l'indirizzo dell'app.
2. In `index.html` incolla l'**App ID** in `const ONESIGNAL_APP_ID = "…"` (non è segreto).
3. In GitHub: Settings → Secrets and variables → Actions → New repository secret, e crea
   `ONESIGNAL_APP_ID` (lo stesso App ID) e `ONESIGNAL_API_KEY` (la chiave REST di OneSignal).
4. Prova: Actions → Aggiorna e pubblica → Run workflow → spunta "Invia una notifica di prova".

Il servizio di OneSignal viene contattato solo da chi sceglie di attivare le notifiche.
