import argparse
import configparser
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import shutil # Aggiungi import shutil
import json # NUOVO IMPORT
from datetime import datetime, date, timedelta # MODIFICATO IMPORT
import time # <-- NUOVO IMPORT
import requests # Aggiungo import per scaricare HTML

# Importa i moduli (assumendo che le funzioni principali siano definite lì)
# from news_extractor.extractor import extract_news_content # RIMOSSO VECCHIO ESTRATTORE
from scraper import get_latest_tgcom_article_content # NUOVO ESTRATTORE TGCOM24
from ai_processor.processor import process_text
from image_finder.finder import find_and_download_images
from tts_generator.generator import generate_speech, create_srt_with_vosk
from video_assembler.assembler import assemble_video
# Importa il nuovo modulo thumbnail
from thumbnail_generator.generator import create_thumbnail
# --- NUOVO IMPORT YOUTUBE UPLOADER --- #
from youtube_uploader.uploader import get_authenticated_service, upload_video

# Configurazione del logging
def setup_logging(log_level="INFO"):
    """Configura il logging di base."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
            # Aggiungere FileHandler se si vuole loggare su file
            # logging.FileHandler("app.log")
        ]
    )
    logging.getLogger("moviepy").setLevel(logging.WARNING) # Riduci verbosità di MoviePy
    logging.getLogger("urllib3").setLevel(logging.WARNING) # Riduci verbosità di requests


# Caricamento della configurazione
def load_configuration(config_file="config.ini"):
    """Carica la configurazione da un file .ini e variabili d'ambiente."""
    config = configparser.ConfigParser()
    
    # Carica prima dal file .ini
    if os.path.exists(config_file):
        config.read(config_file)
        logging.info(f"Caricata configurazione da {config_file}")
    else:
        logging.warning(f"File di configurazione {config_file} non trovato. Utilizzo solo variabili d'ambiente e defaults.")

    # Sovrascrivi/Aggiungi da variabili d'ambiente (caricate da .env se presente)
    load_dotenv() # Carica variabili da .env se esiste
    using_env_var = False # Flag per tracciare la fonte

    # Esempio di come sovrascrivere/impostare da env vars
    # Le chiavi API sono prioritarie da env vars
    if 'OPENAI_API_KEY' in os.environ:
        if 'API_KEYS' not in config: config.add_section('API_KEYS')
        config['API_KEYS']['OPENAI_API_KEY'] = os.environ['OPENAI_API_KEY']
        logging.info("Trovata OPENAI_API_KEY nelle variabili d'ambiente.")
        using_env_var = True
    else:
        logging.info("Nessuna OPENAI_API_KEY trovata nelle variabili d'ambiente, uso config.ini (se presente).")

    if 'UNSPLASH_ACCESS_KEY' in os.environ:
        if 'API_KEYS' not in config: config.add_section('API_KEYS')
        config['API_KEYS']['UNSPLASH_ACCESS_KEY'] = os.environ['UNSPLASH_ACCESS_KEY']
        logging.info("Trovata UNSPLASH_ACCESS_KEY nelle variabili d'ambiente.")

    # Aggiungere controlli simili per PEXELS_API_KEY, GOOGLE_APPLICATION_CREDENTIALS, AWS etc.
    
    # Verifica che le chiavi API essenziali siano presenti
    openai_key = None
    try:
        openai_key = config.get('API_KEYS', 'OPENAI_API_KEY')
        if not openai_key:
            raise ValueError("OPENAI_API_KEY è vuota nel file di configurazione.")
        
        # DEBUGGING: Stampa parziale della chiave letta
        source = "variabili d'ambiente" if using_env_var else "config.ini"
        if len(openai_key) > 9:
            logging.info(f"Sto usando la chiave OpenAI da [{source}]: inizia con '{openai_key[:5]}', finisce con '{openai_key[-4:]}'")
        else:
             logging.info(f"Sto usando la chiave OpenAI da [{source}], ma sembra troppo corta: '{openai_key}'")
            
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
        # Se non trovata nè in env nè in config
        logging.error(f"OPENAI_API_KEY non trovata o vuota nel file di configurazione [{config_file}] e non presente nelle variabili d'ambiente. Errore: {e}")
        raise ValueError("OPENAI_API_KEY non trovata o non valida.") from e
       
    # Potrebbe essere necessario verificare anche la chiave dell'API immagini scelta

    return config

# Gestione directory temporanea
def setup_temp_dir(config):
    """Crea o pulisce la directory temporanea."""
    temp_dir = Path(config.get('SETTINGS', 'TEMP_DIR', fallback='temp'))
    if temp_dir.exists():
        logging.info(f"Pulizia directory temporanea esistente: {temp_dir}")
        for item in temp_dir.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                logging.warning(f"Impossibile eliminare {item} dalla directory temp: {e}")
    else:
        temp_dir.mkdir(parents=True)
        logging.info(f"Directory temporanea creata: {temp_dir}")
    # Assicurati che esista dopo la pulizia/creazione
    temp_dir.mkdir(parents=True, exist_ok=True) 
    return temp_dir

# NUOVA FUNZIONE per controllare il log JSON
def check_if_already_processed(article_title: str, log_file_path: Path) -> bool:
    """Controlla se un titolo articolo esiste già nel file di log JSON."""
    if not log_file_path.exists():
        return False # Il file non esiste, quindi l'articolo non può essere già stato processato

    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
        
        if not isinstance(log_data, list):
            logging.warning(f"Il file di log {log_file_path} non contiene una lista JSON valida. Ignoro il controllo.")
            return False

        # Normalizza il titolo corrente per il confronto
        normalized_current_title = article_title.strip().lower()

        for record in log_data:
            if isinstance(record, dict):
                logged_title = record.get('extracted_title')
                if logged_title:
                    # Normalizza il titolo loggato per il confronto
                    normalized_logged_title = logged_title.strip().lower()
                    if normalized_current_title == normalized_logged_title:
                        logging.info(f"Titolo trovato nel log: '{logged_title}'")
                        return True # Trovato un match!
            else:
                logging.warning(f"Record non valido trovato nel file di log: {record}")

    except json.JSONDecodeError:
        logging.error(f"Errore nel decodificare il file JSON di log {log_file_path}. Impossibile controllare i titoli precedenti.")
        return False # Non possiamo essere sicuri, quindi procediamo
    except Exception as e:
        logging.exception(f"Errore imprevisto durante la lettura/controllo del file di log {log_file_path}: {e}")
        return False # Errore generico, meglio procedere
        
    return False # Nessun match trovato

# NUOVA FUNZIONE PER CONTROLLO LIMITE UPLOAD
def check_daily_upload_limit(log_file_path: Path, limit: int = 6) -> bool:
    """Controlla se il limite di upload giornaliero è stato raggiunto leggendo il log."""
    if not log_file_path.exists():
        return False # Nessun log, nessun limite raggiunto

    today = date.today()
    upload_count_today = 0

    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            try:
                log_data = json.load(f)
            except json.JSONDecodeError:
                logging.error(f"Errore nel decodificare {log_file_path}, impossibile controllare il limite upload.")
                return False # Non possiamo controllare, meglio permettere l'upload

        if not isinstance(log_data, list):
            logging.warning(f"Il file di log {log_file_path} non contiene una lista JSON valida. Ignoro controllo limite.")
            return False

        for record in log_data:
            if isinstance(record, dict):
                # Controlla se c'è un ID video (indica upload riuscito)
                # E se il timestamp è di oggi
                if record.get("youtube_video_id"):
                    timestamp_str = record.get("generation_timestamp")
                    if timestamp_str:
                        try:
                            # Converte il timestamp ISO in oggetto datetime
                            record_datetime = datetime.fromisoformat(timestamp_str)
                            if record_datetime.date() == today:
                                upload_count_today += 1
                        except ValueError:
                            logging.warning(f"Timestamp non valido nel record: {timestamp_str}")

    except Exception as e:
        logging.exception(f"Errore imprevisto durante controllo limite upload: {e}")
        return False # Errore generico, meglio permettere l'upload

    logging.info(f"Upload effettuati oggi ({today}): {upload_count_today}/{limit}")
    return upload_count_today >= limit

def main():
    # --- Parsing Argomenti ---
    parser = argparse.ArgumentParser(description="Genera video riassuntivi da articoli di notizie.")
    parser.add_argument("news_url", nargs='?', help="URL dell'articolo di notizie da processare (Opzionale se impostato nel config e si usa la modalità loop).")
    parser.add_argument("-c", "--config", default="config.ini", help="Percorso del file di configurazione (default: config.ini).")
    parser.add_argument("-o", "--output", help="Nome del file video di output (senza estensione). Se omesso in modalità loop, usa un nome di default.")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Livello di logging.")
    parser.add_argument("--run-once", action='store_true', help="Esegui lo script una sola volta e poi esci (ignora CHECK_INTERVAL_SECONDS).") # <-- NUOVO ARGOMENTO

    args = parser.parse_args()

    # --- Setup Logging (ANTICIPATO) ---
    # Determina il livello di log PRIMA di caricare la configurazione completa
    # così possiamo loggare anche durante il caricamento della config.
    # Prima prova dall'argomento, poi un default ragionevole.
    log_level_arg_early = args.log_level if args.log_level else 'INFO' 
    # Se vuoi leggere il log level dal config *prima*, dovremmo fare un parsing parziale
    # ma per ora usiamo l'argomento o INFO come default iniziale.
    setup_logging(log_level_arg_early)
    logging.debug(f"Argomenti ricevuti: {args}") # Log degli argomenti

    # --- Caricamento Configurazione ---
    try:
        config = load_configuration(args.config)
        # Ora possiamo eventualmente ri-settare il log level se specificato DIVERSAMENTE nel config
        log_level_config = config.get('SETTINGS', 'LOG_LEVEL', fallback=log_level_arg_early)
        if log_level_config.upper() != log_level_arg_early.upper():
            logging.info(f"Aggiorno livello di logging a {log_level_config} come da file di configurazione.")
            # Riconfigura se necessario - SBAGLIATO: basicConfig funziona solo la prima volta
            # setup_logging(log_level_config) 
            # CORREZIONE: Aggiorna il livello del logger root
            new_level = getattr(logging, log_level_config.upper(), logging.INFO)
            logging.getLogger().setLevel(new_level)

    except ValueError as e:
        # L'errore di chiave API mancante viene già loggato dentro load_configuration
        # logging.error(f"Errore durante il caricamento della configurazione: {e}")
        sys.exit(1)
    except Exception as e:
        logging.exception(f"Errore imprevisto durante il caricamento della configurazione: {e}")
        sys.exit(1)

    # Rimosso setup_logging da qui

    # --- Gestione URL e Intervallo Loop (MODIFICATO) ---
    url_from_config = config.get('SETTINGS', 'NEWS_SOURCE_URL', fallback=None)
    if url_from_config:
        url_from_config = url_from_config.strip('"')
        
    news_url_to_process = args.news_url if args.news_url else url_from_config
    if args.run_once and not news_url_to_process:
        logging.error("URL delle notizie necessario quando si usa --run-once e non è specificato nel config.")
        sys.exit(1)
    elif not news_url_to_process:
        logging.error("Nessun URL specificato né come argomento né nel file di configurazione. Impossibile procedere.")
        sys.exit(1)
        
    run_once = args.run_once
    try:
        check_interval = int(config.get('SETTINGS', 'CHECK_INTERVAL_SECONDS', fallback=60))
    except ValueError:
        logging.error("Valore non valido per CHECK_INTERVAL_SECONDS nel config. Uso default 60.")
        check_interval = 60
        
    # --- Setup Directory Temporanea ---
    temp_dir = setup_temp_dir(config)
    output_dir = Path(config.get('SETTINGS', 'OUTPUT_DIR', fallback='output-final'))
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = output_dir / "processed_articles_log.json"
    
    # Ottieni il percorso del file delle credenziali YouTube (come stringhe)
    youtube_secrets_file_str = config.get('YOUTUBE', 'CLIENT_SECRETS_FILE', fallback='client_secrets.json')
    youtube_credentials_file_str = config.get('YOUTUBE', 'CREDENTIALS_FILE', fallback='youtube_credentials.json')
    # --- NUOVO: Converti in Path oggetti --- #
    youtube_secrets_file = Path(youtube_secrets_file_str.strip('"'))
    youtube_credentials_file = Path(youtube_credentials_file_str.strip('"'))
    # --- FINE CONVERSIONE --- #
    
    # --- RIMOSSO DEBUG DA QUI --- #

    # --- Loop Principale (MODIFICATO) ---
    stop_requested = False
    try:
        # --- NUOVO: DEBUG SPOSTATO QUI --- #
        logging.debug(f"Percorso Client Secrets letto da config: '{youtube_secrets_file_str}'")
        logging.debug(f"Percorso Client Secrets (Path object): {youtube_secrets_file}")
        logging.debug(f"Percorso Client Secrets assoluto: {youtube_secrets_file.resolve()}")
        logging.debug(f"File Client Secrets esiste ({youtube_secrets_file.resolve()}): {youtube_secrets_file.exists()}")
        logging.debug(f"Percorso Credentials letto da config: '{youtube_credentials_file_str}'")
        logging.debug(f"Percorso Credentials (Path object): {youtube_credentials_file}")
        logging.debug(f"Percorso Credentials assoluto: {youtube_credentials_file.resolve()}")
        logging.debug(f"File Credentials esiste ({youtube_credentials_file.resolve()}): {youtube_credentials_file.exists()}")
        # --- FINE DEBUG --- #
        
        while not stop_requested:
            logging.info(f"--- Inizio ciclo controllo per URL: {news_url_to_process} ---")
            
            # --- Pulisci e ricrea temp dir ad ogni ciclo --- 
            # (setup_temp_dir fa già la pulizia, qui assicuriamo che esista)
            temp_dir = setup_temp_dir(config)
            
            # --- Logica di uscita e pausa --- 
            if run_once and 'extracted_title' in locals(): # Se è già stato fatto un ciclo in run_once
                 logging.info("Esecuzione singola completata (--run-once).")
                 break

            current_article_title = None
            current_article_text = None
            status_message = "OK"
            try:
                logging.info("1. Download e Estrazione Contenuto...")
                
                # --- NUOVA LOGICA DOWNLOAD e SALVATAGGIO HTML --- #
                # Scarica l'HTML della pagina di cronaca
                downloaded_html_content = None
                try:
                    headers = {'User-Agent': 'Mozilla/5.0'} # Simula un browser
                    response = requests.get(news_url_to_process, headers=headers, timeout=15)
                    response.raise_for_status() # Controlla errori HTTP
                    downloaded_html_content = response.text # Usa .text per contenuto testuale
                    logging.info(f"Pagina HTML scaricata con successo da {news_url_to_process}")
                except requests.exceptions.RequestException as e:
                    logging.error(f"Errore durante il download della pagina {news_url_to_process}: {e}")
                    status_message = f"Errore download: {e}"
                    # Vai al prossimo ciclo dopo l'attesa
                    
                # Salva l'HTML scaricato nel file atteso dallo scraper
                temp_html_path = None
                if downloaded_html_content:
                    try:
                        temp_html_path = temp_dir / "cronaca.html" # Nome file atteso da scraper.py
                        with open(temp_html_path, 'w', encoding='utf-8') as f_html:
                            f_html.write(downloaded_html_content)
                        logging.info(f"HTML scaricato salvato in: {temp_html_path}")
                    except IOError as e:
                        logging.error(f"Errore durante il salvataggio dell'HTML scaricato in {temp_html_path}: {e}")
                        status_message = f"Errore salvataggio HTML: {e}"
                        temp_html_path = None # Impedisce chiamata allo scraper
                        
                # --- FINE NUOVA LOGICA DOWNLOAD --- #
                
                # --- CHIAMA NUOVO ESTRATTORE (se HTML salvato) --- #
                if temp_html_path:
                    # Chiama la funzione da scraper.py, passando il percorso del file salvato
                    # --- MODIFICA: Unpack di 3 valori --- #
                    current_article_title, current_article_text, specific_article_url = get_latest_tgcom_article_content(html_filepath=str(temp_html_path))
                    # --- FINE MODIFICA --- #
                    
                    if current_article_title and current_article_text:
                        logging.info(f"Contenuto estratto con successo da TGCOM24 (Titolo: '{current_article_title}')")
                    else:
                        # La funzione get_latest_tgcom_article_content logga già l'errore specifico
                        logging.error("Estrazione contenuto TGCOM24 fallita.")
                        status_message = "Errore estrazione TGCOM24"
                        # Resetta i valori per evitare processi successivi falliti
                        current_article_title = None
                        current_article_text = None
                else:
                    # Se il download o il salvataggio HTML sono falliti, non chiamare lo scraper
                     logging.warning("Salto estrazione TGCOM24 a causa di errori precedenti (download/salvataggio).")
                     if status_message == "OK": # Aggiorna status se non già impostato
                         status_message = "Errore download/salvataggio HTML"
                # --- FINE CHIAMATA NUOVO ESTRATTORE --- #

                # --- Controllo Titolo e Log (MODIFICATO per usare current_article_title) ---
                if not current_article_title:
                    # Se l'estrazione ha fallito, status_message dovrebbe già essere impostato
                    # Altrimenti, imposta un messaggio generico
                    if status_message == "OK": status_message = "Estrazione fallita (titolo non trovato)"
                    logging.warning(f"Estrazione fallita o titolo non trovato. Status: {status_message}")
                    # Salta il resto del ciclo corrente e attendi
                    # continue # Sostituito con la logica di pausa alla fine
                else:
                     # --- CONTROLLO SE GIA' PROCESSATO --- #
                     if check_if_already_processed(current_article_title, log_file_path):
                         logging.warning(f"L'articolo '{current_article_title}' è già stato processato. Salto.")
                         status_message = "Articolo già processato"
                         # Salta il resto del ciclo corrente e attendi
                         # continue # Sostituito con la logica di pausa alla fine
                     else:
                        # L'articolo è nuovo e valido, procedi con gli altri step
                        logging.info("2. Processamento Testo (AI)...")
                        # --- MODIFICA: Gestione output dizionario da process_text ---
                        ai_result = process_text(current_article_text, config)

                        if ai_result:
                            summary = ai_result.get('summary')
                            keywords = ai_result.get('keywords', []) # Default a lista vuota se manca
                            # Estrai anche gli altri campi se necessario per passaggi successivi
                            # (es. thumbnail_title, youtube_title, ecc. se usati dopo)
                            # Per ora, ci assicuriamo che summary e keywords siano estratti
                            if summary and keywords:
                                 logging.info(f"Testo processato. Riassunto generato, Keywords: {keywords}")
                            else:
                                 # Se mancano campi essenziali dal dizionario restituito
                                 logging.error("Elaborazione AI riuscita ma risultato incompleto (manca summary o keywords nel dizionario restituito).")
                                 status_message = "Errore AI: risultato incompleto"
                                 summary, keywords = None, None # Azzera per evitare errori dopo
                        else:
                            # Se process_text ha restituito None (errore interno)
                            logging.error("Processamento Testo (AI) fallito.")
                            status_message = "Errore AI Processor"
                            summary, keywords = None, None # Azzera per evitare errori dopo
                        # --- FINE MODIFICA ---

                        # --- Continua solo se summary e keywords sono validi --- #
                        if summary and keywords:
                            logging.info("3. Ricerca e Download Immagini...")
                            # --- MODIFICA: Passa anche il titolo per la ricerca immagini --- #
                            image_paths = find_and_download_images(
                                keywords,
                                temp_dir,
                                config,
                                article_title=current_article_title # Passa il titolo effettivo
                            )
                            # --- FINE MODIFICA --- #
                            if not image_paths:
                                logging.warning("Nessuna immagine trovata o scaricata. Il video potrebbe essere vuoto o breve.")
                                status_message = "Nessuna immagine trovata"
                            else:
                                logging.info(f"{len(image_paths)} immagini scaricate in {temp_dir}")

                            logging.info("4. Generazione Audio (TTS)...")
                            # --- MODIFICA: Gestione return di generate_speech e chiamata SRT separata --- #
                            audio_path = generate_speech(summary, temp_dir, config)
                            srt_path = None # Inizializza srt_path a None - CORRETTA INDENTAZIONE

                            if not audio_path:
                                logging.error("Generazione audio fallita. Impossibile creare il video.")
                                status_message = "Errore generazione audio"
                                # Salta il resto del ciclo se l'audio fallisce
                            else:
                                logging.info(f"Audio generato: {audio_path}")

                                # --- CHIAMA GENERAZIONE SRT (se Vosk configurato/disponibile) --- #
                                vosk_model_path_raw = config.get('VOSK_SETTINGS', 'MODEL_PATH', fallback=None)
                                if vosk_model_path_raw:
                                    vosk_model_path = Path(vosk_model_path_raw.strip('"'))
                                    if vosk_model_path.exists():
                                        logging.info("4.5 Generazione File Sottotitoli (.srt) con Vosk...")
                                        srt_filename = audio_path.stem + ".srt"
                                        output_srt_path = temp_dir / srt_filename
                                        # Chiama la funzione create_srt_with_vosk (importata all'inizio)
                                        srt_path = create_srt_with_vosk(audio_path, output_srt_path, config)
                                        if srt_path:
                                            logging.info(f"SRT generato: {srt_path}")
                                        else:
                                            logging.warning("Generazione SRT fallita (Vosk). Procedo senza SRT.")
                                    else:
                                        logging.warning(f"Percorso modello Vosk specificato ({vosk_model_path}) ma non trovato. Salto generazione SRT.")
                                else:
                                    logging.info("Generazione SRT saltata (VOSK_SETTINGS -> MODEL_PATH non configurato).")
                                # --- FINE GENERAZIONE SRT --- #

                            # --- Solo se audio è ok (SRT è opzionale) --- #
                            if audio_path:
                                logging.info("5. Assemblaggio Video...")
                                # Determina il nome file di output
                                if args.output:
                                    output_video_name = args.output
                                else:
                                    # Crea un nome file dal titolo (semplificato)
                                    safe_title = "".join(c for c in current_article_title if c.isalnum() or c in (' ','-')).rstrip()
                                    safe_title = safe_title.replace(' ', '_')[:50] # Limita lunghezza
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                                    output_video_name = f"{safe_title}_{timestamp}"

                                output_video_path = output_dir / f"{output_video_name}.mp4"

                                # --- CORREZIONE ORDINE ARGOMENTI --- #
                                # --- NUOVO: Leggi e controlla path Intro/Outro --- #
                                intro_path_str = config.get('VIDEO_EXTRAS', 'INTRO_VIDEO_PATH', fallback='').strip('"')
                                outro_path_str = config.get('VIDEO_EXTRAS', 'OUTRO_VIDEO_PATH', fallback='').strip('"')
                                intro_path = Path(intro_path_str) if intro_path_str and Path(intro_path_str).exists() else None
                                outro_path = Path(outro_path_str) if outro_path_str and Path(outro_path_str).exists() else None

                                if intro_path_str and not intro_path:
                                    logging.warning(f"Video intro specificato ({intro_path_str}) ma non trovato.")
                                if outro_path_str and not outro_path:
                                    logging.warning(f"Video outro specificato ({outro_path_str}) ma non trovato.")
                                # --- FINE LETTURA INTRO/OUTRO --- #

                                final_video_path = assemble_video(
                                    image_paths=image_paths if image_paths else [],
                                    audio_path=audio_path,
                                    output_path=output_video_path,
                                    config=config, # 4° argomento: config
                                    srt_path=srt_path, # 5° argomento: srt_path
                                    intro_video_path=intro_path, # 6° argomento: intro
                                    outro_video_path=outro_path # 7° argomento: outro
                                )
                                # --- FINE CORREZIONE --- #

                                if final_video_path:
                                    logging.info(f"Video assemblato con successo: {final_video_path}")

                                    # --- NUOVA LOGICA THUMBNAIL --- #
                                    thumbnail_config = config['THUMBNAIL'] if 'THUMBNAIL' in config else None
                                    if thumbnail_config and thumbnail_config.getboolean('ENABLED', False):
                                        logging.info("6. Generazione Thumbnail...")
                                        thumbnail_image_path = image_paths[thumbnail_config.getint('BACKGROUND_IMAGE_INDEX', 0)] if image_paths else None
                                        if thumbnail_image_path:
                                            # --- PULIZIA SUFFISSO --- #
                                            output_suffix_raw = thumbnail_config.get('OUTPUT_SUFFIX', '_thumbnail.png')
                                            output_suffix = output_suffix_raw.strip('"') # Rimuovi virgolette
                                            # --- FINE PULIZIA --- #
                                            thumbnail_output_path = output_dir / f"{output_video_name}{output_suffix}"

                                            # --- Lettura parametri aggiuntivi dal config --- #
                                            overlay_path_str = thumbnail_config.get('OVERLAY_PATH', 'thumbnail_generator/overlay.png').strip('"')
                                            overlay_path = Path(overlay_path_str)
                                            font_path_str = thumbnail_config.get('FONT_PATH', 'thumbnail_generator/Gotham-Medium.otf').strip('"')
                                            font_path = Path(font_path_str) if font_path_str else None
                                            font_size = thumbnail_config.getint('FONT_SIZE', 80)
                                            bold_text = thumbnail_config.getboolean('BOLD_TEXT', True)
                                            text_color_str = thumbnail_config.get('TEXT_COLOR', '255, 255, 255').strip('"')
                                            text_pos_str = thumbnail_config.get('TEXT_POSITION', '40, 570').strip('"')

                                            try:
                                                color_parts = [int(c.strip()) for c in text_color_str.split(',')]
                                                text_color = tuple(color_parts) if len(color_parts) == 3 else (255, 255, 255)
                                            except ValueError:
                                                logging.warning(f"Formato TEXT_COLOR non valido ('{text_color_str}'), uso default (255, 255, 255).")
                                                text_color = (255, 255, 255)

                                            try:
                                                pos_parts = [int(p.strip()) for p in text_pos_str.split(',')]
                                                text_position = tuple(pos_parts) if len(pos_parts) == 2 else (40, 570)
                                            except ValueError:
                                                logging.warning(f"Formato TEXT_POSITION non valido ('{text_pos_str}'), uso default (40, 570).")
                                                text_position = (40, 570)

                                            # Verifica esistenza file opzionali
                                            if not overlay_path.exists():
                                                 logging.error(f"File overlay per thumbnail non trovato: {overlay_path}. Salto generazione thumbnail.")
                                                 created_thumb_path = None
                                            elif font_path and not font_path.exists():
                                                 logging.warning(f"File font per thumbnail specificato ({font_path}) ma non trovato. Verrà usato il font di default.")
                                                 font_path = None # Forza uso default

                                            # --- Chiamata CORRETTA a create_thumbnail --- #
                                            if overlay_path.exists(): # Prosegui solo se l'overlay esiste
                                                # --- NUOVO: Tronca titolo per thumbnail --- #
                                                thumbnail_text = current_article_title
                                                # --- MODIFICA LIMITE --- #
                                                if len(thumbnail_text) > 32: # Nuovo limite
                                                     thumbnail_text = thumbnail_text[:29] + "..." # Troncamento a 29 + ...
                                                     # --- CORREZIONE INDENTAZIONE --- #
                                                     logging.debug(f"Titolo troncato per thumbnail: '{thumbnail_text}'")
                                                # --- FINE CORREZIONE --- #
                                                # --- FINE MODIFICA --- #
                                                # --- FINE TRONCAMENTO --- #

                                                created_thumb_path = create_thumbnail(
                                                    text=thumbnail_text, # Usa il titolo troncato
                                                    background_image_path=thumbnail_image_path, # Immagine di sfondo
                                                    overlay_image_path=overlay_path, # Immagine overlay sopra cui scrivere
                                                    font_path=font_path, # Percorso del font (o None)
                                                    font_size=font_size, # Dimensione font
                                                    text_color=text_color, # Colore testo (tupla RGB)
                                                    text_position=text_position, # Posizione testo (tupla XY)
                                                    output_path=thumbnail_output_path, # Dove salvare il risultato
                                                    bold=bold_text # Se usare stile grassetto (simulato)
                                                )
                                            # --- FINE CHIAMATA CORRETTA --- #

                                            if created_thumb_path:
                                                logging.info(f"Thumbnail creato: {created_thumb_path}")
                                            else:
                                                # L'errore specifico è già loggato dentro create_thumbnail o dal controllo overlay
                                                if overlay_path.exists(): # Logga solo se l'errore non era l'overlay mancante
                                                     logging.error("Creazione thumbnail fallita.")
                                                     status_message = "Errore creazione thumbnail"
                                        else:
                                            logging.warning("Nessuna immagine di sfondo disponibile per il thumbnail.")
                                    else:
                                        logging.debug("Generazione Thumbnail disabilitata nel config.")
                                    # --- FINE LOGICA THUMBNAIL --- #

                                    # --- NUOVA LOGICA UPLOAD YOUTUBE --- #
                                    youtube_config = config['YOUTUBE'] if 'YOUTUBE' in config else None
                                    youtube_upload_enabled = config.getboolean('YOUTUBE_UPLOAD', 'ENABLED', fallback=False)
                                    video_id_uploaded = None # Inizializza video ID

                                    if youtube_upload_enabled and youtube_config:
                                        logging.info("7. Upload su YouTube...")
                                        # Controlla limite giornaliero PRIMA di tentare l'upload
                                        upload_limit = youtube_config.getint('DAILY_UPLOAD_LIMIT', 6)
                                        if check_daily_upload_limit(log_file_path, upload_limit):
                                            logging.warning(f"Limite giornaliero di {upload_limit} upload raggiunto. Salto upload.")
                                            status_message = "Limite upload giornaliero raggiunto"
                                            # --- NUOVO: Termina lo script --- #
                                            logging.info("Limite giornaliero di upload raggiunto. Arresto dello script come richiesto.")
                                            stop_requested = True # Imposta flag per uscita pulita
                                            break # Esci dal loop while principale
                                            # --- FINE MODIFICA --- #
                                        else:
                                            try:
                                                # --- MODIFICA: Passa oggetti Path --- #
                                                youtube = get_authenticated_service(youtube_secrets_file, youtube_credentials_file)
                                                # --- FINE MODIFICA --- #
                                                
                                                # --- NUOVO CONTROLLO: Verifica se l'autenticazione è riuscita --- #
                                                if youtube is None:
                                                    logging.error("Autenticazione YouTube fallita (servizio non ottenuto). Salto upload.")
                                                    status_message = "Errore autenticazione YouTube"
                                                    # Non procedere con l'upload
                                                else:
                                                    # --- MODIFICA: Aggiunta CTA fisso alla descrizione --- #
                                                    ai_desc = ai_result.get('youtube_description', '') # Prendi desc AI (o stringa vuota)
                                                    cta_text = "\nSe non l'hai ancora fatto, iscriviti al canale e attiva le notifiche cliccando sulla campanella 🔔. Così sarai sempre aggiornato sui nostri nuovi contenuti!"
                                                    full_description = ai_desc + cta_text
                                                    # Limita la lunghezza totale (YouTube ha un limite di 5000 caratteri)
                                                    full_description = full_description[:5000]
                                                    # --- FINE MODIFICA --- #

                                                    # --- CORREZIONE CHIAMATA upload_video --- #
                                                    # Estrai valori necessari dai dizionari
                                                    upload_title = current_article_title # Titolo articolo originale
                                                    upload_tags = ai_result.get('youtube_tags', keywords[:10]) # Usa tag specifici o fallback
                                                    upload_category_id = youtube_config.get('VIDEO_CATEGORY_ID', '22')
                                                    # --- PULIZIA PRIVACY STATUS --- #
                                                    privacy_status_raw = youtube_config.get('VIDEO_PRIVACY_STATUS', 'private')
                                                    # Rimuovi virgolette e parti di commento (#...)
                                                    upload_privacy_status = privacy_status_raw.split('#')[0].strip().strip('"')
                                                    # --- FINE PULIZIA --- #
                                                    
                                                    # Recupera il percorso della thumbnail (se creata)
                                                    upload_thumbnail_path = None
                                                    if 'created_thumb_path' in locals() and created_thumb_path and created_thumb_path.exists():
                                                        upload_thumbnail_path = created_thumb_path
                                                        
                                                    # Chiama la funzione con argomenti separati
                                                    video_id_uploaded = upload_video(
                                                        youtube_service=youtube, 
                                                        video_path=final_video_path, 
                                                        thumbnail_path=upload_thumbnail_path, # Passa il percorso thumbnail (o None)
                                                        title=upload_title, 
                                                        description=full_description, 
                                                        tags=upload_tags,
                                                        category_id=upload_category_id,
                                                        privacy_status=upload_privacy_status
                                                    )
                                                    # --- FINE CORREZIONE --- #

                                                    if video_id_uploaded:
                                                        logging.info(f"Video caricato con successo! ID: {video_id_uploaded}")

                                                        # --- NUOVO: Elimina file dopo upload --- #
                                                        logging.info(f"Tentativo di eliminare file locali dopo upload riuscito...")
                                                        try:
                                                            final_video_path.unlink() # Equivalente a os.remove
                                                            logging.info(f"File video locale eliminato: {final_video_path}")
                                                        except OSError as e_del_vid:
                                                            logging.warning(f"Impossibile eliminare file video locale {final_video_path}: {e_del_vid}")

                                                        # Elimina thumbnail se esiste
                                                        # Usiamo created_thumb_path se è stata generata, altrimenti proviamo con thumbnail_output_path
                                                        thumb_to_delete = None
                                                        if 'created_thumb_path' in locals() and created_thumb_path and created_thumb_path.exists():
                                                            thumb_to_delete = created_thumb_path
                                                        elif 'thumbnail_output_path' in locals() and thumbnail_output_path.exists():
                                                             # Questo potrebbe essere il caso se la generazione è fallita ma il path è stato costruito
                                                             # Controlliamo se esiste prima di tentare la cancellazione
                                                             if thumbnail_output_path.exists():
                                                                  thumb_to_delete = thumbnail_output_path

                                                        if thumb_to_delete:
                                                            try:
                                                                thumb_to_delete.unlink()
                                                                logging.info(f"File thumbnail locale eliminato: {thumb_to_delete}")
                                                            except OSError as e_del_thumb:
                                                                logging.warning(f"Impossibile eliminare file thumbnail locale {thumb_to_delete}: {e_del_thumb}")
                                                        else:
                                                             logging.debug("Nessun file thumbnail locale trovato da eliminare.")
                                                        # --- FINE ELIMINAZIONE FILE --- #

                                                    else:
                                                        logging.error("Upload su YouTube fallito.") # Ripristinato else
                                                        status_message = "Errore upload YouTube" # Ripristinato status

                                            except Exception as upload_err:
                                                logging.exception(f"Errore durante l'autenticazione o l'upload su YouTube: {upload_err}")
                                                status_message = f"Errore YouTube: {upload_err}"
                                    else:
                                         logging.debug("Upload YouTube disabilitato nel config.")
                                    # --- FINE LOGICA UPLOAD YOUTUBE --- #

                                    # --- AGGIORNAMENTO LOG JSON (SOLO SE TUTTO OK O CON ERRORI MINORI) --- #
                                    # Assicurati che video_id_uploaded sia definito anche se l'upload fallisce o viene saltato
                                    if 'video_id_uploaded' not in locals():
                                         video_id_uploaded = None 
                                         
                                    try:
                                        # --- MODIFICA: Log completo --- #
                                        log_entry = {
                                            "generation_timestamp": datetime.now().isoformat(),
                                            # Usa l'URL specifico dell'articolo, non quello della pagina cronaca
                                            "article_url": specific_article_url if specific_article_url else news_url_to_process,
                                            "extracted_title": current_article_title, # OK
                                            # Aggiungi campi AI (assicurati che ai_result sia disponibile qui)
                                            "ai_summary": ai_result.get('summary') if ai_result else None,
                                            "ai_keywords": ai_result.get('keywords') if ai_result else [],
                                            "ai_thumbnail_title": ai_result.get('thumbnail_title') if ai_result else None,
                                            "ai_youtube_title": ai_result.get('youtube_title') if ai_result else None,
                                            "ai_youtube_description": ai_result.get('youtube_description') if ai_result else None,
                                            "ai_youtube_tags": ai_result.get('youtube_tags') if ai_result else [],
                                            # Aggiungi nomi file
                                            "downloaded_image_filenames": [p.name for p in image_paths] if image_paths else [],
                                            "audio_filename": audio_path.name if audio_path else None,
                                            "srt_filename": srt_path.name if srt_path else None,
                                            "output_video_path": str(final_video_path) if final_video_path else None, # Gestisci None
                                            # Assicurati che created_thumb_path sia accessibile o usa thumbnail_output_path
                                            "output_thumbnail_path": str(created_thumb_path) if 'created_thumb_path' in locals() and created_thumb_path else str(thumbnail_output_path) if 'thumbnail_output_path' in locals() else None,
                                            "status": status_message, # OK
                                            "youtube_video_id": video_id_uploaded # OK
                                        }
                                        # --- FINE MODIFICA LOG --- #

                                        full_log = []
                                        if log_file_path.exists():
                                            try:
                                                with open(log_file_path, 'r', encoding='utf-8') as f_log_read:
                                                    full_log = json.load(f_log_read)
                                                    if not isinstance(full_log, list):
                                                        logging.warning(f"Il file di log {log_file_path} non conteneva una lista. Verrà sovrascritto.")
                                                        full_log = []
                                            except json.JSONDecodeError:
                                                logging.warning(f"Errore decodifica JSON in {log_file_path}. Il file verrà sovrascritto.")
                                                full_log = []

                                        full_log.append(log_entry)

                                        with open(log_file_path, 'w', encoding='utf-8') as f_log_write:
                                            json.dump(full_log, f_log_write, indent=4, ensure_ascii=False)
                                        logging.info(f"Log aggiornato in {log_file_path}")

                                    except Exception as log_e:
                                        logging.exception(f"Errore durante l'aggiornamento del file di log JSON: {log_e}")
                                    # --- FINE AGGIORNAMENTO LOG ---

                                else: # Corrisponde a if final_video_path:
                                    logging.error("Assemblaggio video fallito.")
                                    status_message = "Errore assemblaggio video"
                                    # Non aggiornare il log se l'assemblaggio fallisce
                                    # (o loggalo come fallito se preferisci)

            except Exception as e:
                logging.exception(f"Errore imprevisto durante il processamento dell'articolo: {e}")
                status_message = f"Errore generale: {e}"
                # Considera se loggare questo errore anche nel JSON log file

            # --- Logica di Pausa / Uscita dal Loop --- #
            if run_once:
                logging.info("Esecuzione singola completata (--run-once).")
                break # Esci dal loop while
            else:
                # Pausa prima del prossimo ciclo
                logging.info(f"Attesa di {check_interval} secondi prima del prossimo controllo...")
                time.sleep(check_interval)

    except KeyboardInterrupt:
        logging.info("Interruzione richiesta dall'utente (Ctrl+C). Arresto dello script...")
        stop_requested = True
    finally:
        logging.info("Script terminato.")
        # Pulizia finale se necessario (anche se temp_dir viene pulito all'inizio)
        # Considera se eliminare la temp_dir alla fine
        # if temp_dir.exists():
        #    shutil.rmtree(temp_dir)
        #    logging.info(f"Directory temporanea finale rimossa: {temp_dir}")

if __name__ == "__main__":
    # Aggiunta per debug path
    # print("--- DEBUG: sys.path in tts_generator ---")
    # print("\\n".join(sys.path))
    # print("--- FINE DEBUG: sys.path ---")
    main()
