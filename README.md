## Specifiche Funzionali e Moduli

Il progetto è suddiviso in moduli distinti, ciascuno con responsabilità specifiche:

### Modulo `news_extractor`
- **Input:** URL della fonte di notizie (configurabile).
- **Compiti:** Identificare e accedere agli articoli recenti, estrarre il testo completo pulito utilizzando web scraping (`requests`, `BeautifulSoup4`). Gestisce User-Agent e potenziali blocchi.
- **Output:** Stringa contenente il testo pulito dell'articolo più recente.

### Modulo `ai_processor`
- **Input:** Testo completo dell'articolo.
- **Compiti:** Interfacciarsi con l'API di OpenAI (`gpt-3.5-turbo` o `gpt-4`) per generare un riassunto del testo (durata di lettura configurabile) e estrarre parole chiave/frasi chiave rilevanti. Gestisce risposte ed errori API.
- **Output:** Dizionario `{'summary': '...', 'keywords': [...]}`.

### Modulo `image_finder`
- **Input:** Lista di parole chiave, Titolo articolo (opzionale).
- **Compiti:** Utilizzare una libreria di ricerca immagini (default: `duckduckgo-search`) per trovare e scaricare immagini pertinenti. Utilizza `Pillow` per specchiare orizzontalmente le immagini e salvarle in formato JPEG pulito.
- **Output:** Lista dei percorsi file locali delle immagini scaricate e modificate.

### Modulo `tts_generator`
- **Input:** Testo del riassunto.
- **Compiti TTS:** Convertire il riassunto in audio utilizzando un provider TTS configurabile (`pyttsx3`, `gTTS`, `google-cloud-texttospeech`). Salva l'audio localmente (MP3/WAV).
- **Compiti Sottotitoli (SRT):** Utilizzare la libreria offline `vosk` per generare un file `.srt` sincronizzato dall'audio TTS. Richiede un modello Vosk pre-scaricato. Converte l'audio in formato WAV compatibile con Vosk (`ffmpeg-python`).
- **Output:** Dizionario `{'audio_path': '...', 'srt_path': '...'}`.

### Modulo `video_assembler`
- **Input:** Percorsi file di immagini modificate, audio, SRT, video intro (opzionale).
- **Compiti:** Utilizzare `ffmpeg-python` per assemblare il video:
    - Gestire e concatenare un video introduttivo (se presente).
    - Creare una slideshow dalle immagini con durata calcolata.
    - Concatenare video intro e slideshow.
    - Gestire e mixare l'audio (intro e TTS principale, applicando ritardo se necessario).
    - Applicare i sottotitoli (traslando i timestamp se c'è un intro) utilizzando il filtro `subtitles` di FFmpeg.
    - Esportare il video finale in formato MP4.
- **Output:** Percorso del file video finale.

### Orchestratore Principale (`main.py`)
- **Compiti:**
    - Gestire gli argomenti da riga di comando (`argparse`).
    - Caricare la configurazione da `config.ini` e sovrascrivere con variabili d'ambiente (`python-dotenv`).
    - Invocare sequenzialmente gli altri moduli.
    - Gestire il passaggio dei dati tra i moduli.
    - Implementare logging configurabile.
    - Gestire errori di workflow.
    - Gestire directory temporanee.
    - **NOVITÀ:** Generare un titolo breve per thumbnail tramite AI (`ai_processor`).
    - **NOVITÀ:** Salvare metadati di ogni esecuzione (`generation_log.json`) per persistenza.
    - **NOVITÀ:** Implementare un controllo di duplicazione basato sul titolo dell'articolo nel log.
    - **NOVITÀ:** Aggiungere supporto per un video di outro configurabile.
- **Input:** Argomenti da riga di comando, file di configurazione.
- **Output:** Stato di avanzamento, log, percorso video finale o errori.

### Modulo `thumbnail_generator` (NOVITÀ)
- **Input:** Titolo (generato da AI), immagine chiave, configurazione.
- **Compiti:** Creare un'immagine di thumbnail per il video, opzionalmente aggiungendo testo (il titolo generato da AI) e altri elementi grafici.
- **Output:** Percorso del file immagine della thumbnail generata.

## Stack Tecnologico

- **Linguaggio:** Python 3.11
- **Librerie Core:** `requests`, `beautifulsoup4`, `openai`, `Pillow`, `ffmpeg-python`, `configparser`, `python-dotenv`, `google-cloud-texttospeech`, `vosk`, `srt`, `lxml`.
- **Librerie Opzionali/Configurabili:** `duckduckgo-search`, `gTTS`, `pyttsx3`.
- **Altre Dipendenze:** `cffi`, `numpy`, `setuptools`.
- **Strumenti Esterni:** FFmpeg (eseguibile), Modello Linguistico Vosk.

## Prerequisiti

Prima di eseguire il progetto, assicurati di avere quanto segue:

1.  **Python 3.11:** Installato sul tuo sistema. È fortemente raccomandato l'uso di un ambiente virtuale (`venv`).
2.  **FFmpeg:** L'eseguibile FFmpeg deve essere installato e accessibile dal PATH del tuo sistema. Puoi scaricarlo dal [sito ufficiale di FFmpeg](https://ffmpeg.org/download.html).
3.  **Modello Linguistico Vosk:** Devi scaricare un modello linguistico Vosk per l'italiano (es. `vosk-model-small-it-0.22`). Puoi trovare i modelli [qui](https://alphacephei.com/vosk/models). Configura il percorso in `config.ini`.
4.  **API Key OpenAI:** Necessaria per il modulo `ai_processor`. Ottenila dal [sito di OpenAI](https://platform.openai.com/).
5.  **Credenziali Google Cloud:** Necessarie se usi `google-cloud-texttospeech` come provider TTS. Crea un *Account di Servizio* in Google Cloud Platform e scarica il file JSON della chiave. Configura il percorso in `config.ini`.
6.  **File di Configurazione:** Un file `config.ini` configurato correttamente (vedi sezione Configurazione).
7.  **(Opzionale) File .env:** Un file `.env` per sovrascrivere le chiavi API sensibili (raccomandato).

## Installazione

1.  Clona il repository (o scarica i file del progetto).
2.  Naviga nella directory del progetto tramite terminale.
3.  Crea un ambiente virtuale (raccomandato per isolare le dipendenze):
    ```bash
    python3.11 -m venv venv
    ```
4.  Attiva l'ambiente virtuale:
    - Su macOS/Linux:
      ```bash
      source venv/bin/activate
      ```
    - Su Windows:
      ```bash
      .\venv\Scripts\activate
      ```
5.  Installa le dipendenze Python:
    ```bash
    pip install -r requirements.txt
    ```
6.  Installa FFmpeg (se non lo hai già fatto) e rendilo accessibile nel tuo PATH.
7.  Scarica il modello linguistico Vosk desiderato e posizionalo in una directory a tua scelta.
8.  Configura il file `config.ini` e opzionalmente il file `.env` (vedi sezione Configurazione).

## Configurazione

Il progetto utilizza un file `config.ini` per la maggior parte delle impostazioni e opzionalmente un file `.env` per le chiavi API sensibili.

-   **`config.ini`:**
    -   Crea un file chiamato `config.ini` nella root del progetto.
    -   Contiene sezioni per API Keys, fornitori di servizi (TTS, Immagini), percorsi file (Vosk model, intro/outro video, credenziali Google), parametri di generazione (parole target riassunto, numero immagini, FPS video, ecc.).
    -   **Gestione Credenziali Google Cloud:** Assicurati che la sezione `[GOOGLE_TTS_SETTINGS]` contenga `GOOGLE_APPLICATION_CREDENTIALS = "percorso/alla/tua/chiave/google-data.json"`.
    -   **Modello Vosk:** Assicurati che la sezione `[VOSK_SETTINGS]` contenga `MODEL_PATH = "percorso/alla/tua/directory/vosk-model-small-it-0.22"`.
    -   **Video Extra:** Configura `INTRO_VIDEO_PATH` e `OUTRO_VIDEO_PATH` nelle rispettive sezioni se vuoi usarli.
    -   **Thumbnail:** Configura le impostazioni nella sezione `[THUMBNAIL]`, inclusi i percorsi degli asset (overlay, font) che dovrebbero essere relativi alla root del progetto (es. `thumbnail_generator/assets/font.ttf`).
    -   **Logging:** Configura il livello di logging in `config.ini`.

-   **`.env` (Opzionale, ma Raccomandato):**
    -   Crea un file chiamato `.env` nella root del progetto.
    -   Puoi usarlo per sovrascrivere le API keys specificate in `config.ini`, mantenendole fuori dal controllo di versione. Ad esempio:
      ```dotenv
      OPENAI_API_KEY=la_tua_chiave_openai
      # Se usi Google TTS con variabili d'ambiente invece del file:
      # GOOGLE_APPLICATION_CREDENTIALS_JSON={"type": "service_account", ...}
      ```
    -   Il file `.gitignore` è configurato per ignorare `config.ini`, `.env` e i file di credenziali come `google-data.json` per motivi di sicurezza.

## Utilizzo

Esegui lo script principale da riga di comando:

```bash
python main.py [opzioni]
