import os
import logging
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from pathlib import Path

# Definisci gli scope richiesti per l'upload su YouTube
# youtube.upload: permette l'upload dei video
# youtube.readonly: potrebbe essere utile per verificare lo stato, ma upload è sufficiente per iniziare
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

# Funzione per ottenere/creare le credenziali
def get_authenticated_service(client_secrets_file: Path, credentials_file: Path):
    """Autentica l'utente usando OAuth 2.0 e restituisce l'oggetto service per l'API YouTube."""
    credentials = None
    # Il file credentials_file (es. token.json) salva i token di accesso/refresh dell'utente.
    # Viene creato automaticamente alla prima autorizzazione.
    if credentials_file.exists():
        try:
            credentials = google.oauth2.credentials.Credentials.from_authorized_user_file(str(credentials_file), SCOPES)
            logging.info(f"Credenziali caricate da {credentials_file}")
        except Exception as e:
             logging.warning(f"Errore caricando le credenziali da {credentials_file}: {e}. Procedo con nuovo flusso OAuth.")
             credentials = None # Forza nuovo flusso

    # Se non ci sono credenziali valide disponibili, lascia che l'utente faccia il login.
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                logging.info("Credenziali scadute, tentativo di refresh...")
                credentials.refresh(Request())
                logging.info("Refresh token riuscito.")
            except Exception as e:
                logging.error(f"Refresh token fallito: {e}. Avvio nuovo flusso OAuth.")
                # Se il refresh fallisce, elimina il vecchio token file per sicurezza
                try:
                    credentials_file.unlink(missing_ok=True)
                except OSError as unlink_err:
                     logging.error(f"Impossibile eliminare il file token scaduto {credentials_file}: {unlink_err}")
                credentials = None # Forza nuovo flusso
        else:
             # Avvia il flusso OAuth 2.0 per ottenere nuove credenziali
             # --- DEBUG: Verifica percorso secrets file QUI --- #
             logging.debug(f"[Uploader] Tento di usare client_secrets_file: {client_secrets_file}")
             logging.debug(f"[Uploader] Percorso assoluto: {client_secrets_file.resolve()}")
             logging.debug(f"[Uploader] Esiste? {client_secrets_file.exists()}")
             
             # --- FORZA USO PATH ASSOLUTO --- #
             absolute_secrets_path = Path("/Users/ruben/Desktop/YT Project/client_secrets.json")
             logging.debug(f"[Uploader] Tento con percorso assoluto forzato: {absolute_secrets_path}")
             logging.debug(f"[Uploader] Esiste (forzato)? {absolute_secrets_path.exists()}")
             # --- FINE FORZA USO --- #
             
             # --- MODIFICA: Usa absolute_secrets_path per il check e il flusso --- #
             if not absolute_secrets_path.exists():
             # --- FINE DEBUG --- #
             # if not client_secrets_file.exists():
                 # --- MODIFICA LOGGING: Fornisce percorso assoluto --- #
                 logging.error(f"File client secrets '{absolute_secrets_path.resolve()}' non trovato (percorso forzato). Impossibile autenticare.")
                 # --- FINE MODIFICA --- #
                 return None

             logging.info(f"Avvio flusso OAuth 2.0 usando {absolute_secrets_path}. Seguire le istruzioni nel browser.")
             flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                 str(absolute_secrets_path), SCOPES) # Usa il percorso assoluto
             # port=0 cercherà una porta libera
             # --- RIPRISTINA FLUSSO CON SERVER LOCALE --- #
             try:
                 # Genera l'URL di autorizzazione
                 # auth_url, _ = flow.authorization_url(prompt='consent') # COMMENTATO
                 # print(f"Visita questo URL per autorizzare l'applicazione:\n{auth_url}")

                 # Chiedi all'utente il codice di autorizzazione
                 # code = input("Inserisci il codice di autorizzazione ottenuto dal browser: ")

                 # Scambia il codice per le credenziali
                 # flow.fetch_token(code=code)
                 # credentials = flow.credentials
                 
                 # RIPRISTINA run_local_server
                 credentials = flow.run_local_server(port=0) 
             except Exception as e_flow:
                  logging.exception(f"Errore durante il flusso OAuth 2.0 (server locale): {e_flow}")
                  return None
             # --- FINE RIPRISTINO --- #

        # Salva le credenziali per la prossima esecuzione
        if credentials:
            try:
                credentials_file.parent.mkdir(parents=True, exist_ok=True) # Assicura che la dir esista
                with open(credentials_file, 'w') as token:
                    token.write(credentials.to_json())
                logging.info(f"Credenziali salvate in {credentials_file}")
            except Exception as e_save:
                logging.exception(f"Errore durante il salvataggio delle credenziali in {credentials_file}: {e_save}")
                # Non restituiamo None qui, l'autenticazione è comunque avvenuta in memoria
    
    # Costruisci e restituisci l'oggetto service API
    try:
        youtube_service = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
        logging.info("Servizio YouTube autenticato con successo.")
        return youtube_service
    except Exception as e_build:
        logging.exception(f"Errore durante la costruzione del servizio YouTube API: {e_build}")
        return None

# Funzione placeholder per l'upload
def upload_video(youtube_service, video_path: Path, thumbnail_path: Path | None, 
                 title: str, description: str, tags: list[str], 
                 privacy_status: str = 'private', category_id: str = '22') -> str | None:
    """Carica il video su YouTube e restituisce l'ID del video caricato o None in caso di errore."""
    logging.info(f"Avvio upload su YouTube per il video: {video_path.name}")
    
    if not video_path.exists():
        logging.error(f"File video non trovato: {video_path}")
        return None
    if thumbnail_path and not thumbnail_path.exists():
        logging.warning(f"File thumbnail specificato ({thumbnail_path}) ma non trovato. L'upload procederà senza thumbnail personalizzata.")
        thumbnail_path = None # Non tentare l'upload della thumbnail se non esiste

    try:
        # Costruisci il corpo della richiesta API
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category_id # 22 = People & Blogs, vedi API docs per altri ID
            },
            'status': {
                'privacyStatus': privacy_status, # 'private', 'public', 'unlisted'
                'selfDeclaredMadeForKids': False # Importante specificarlo
            }
        }

        # Crea l'oggetto MediaFileUpload per il video
        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)

        # Esegui la richiesta di inserimento (upload)
        logging.info("Caricamento video in corso...")
        request = youtube_service.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        # Gestione della risposta (upload resumable)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logging.info(f"Caricato {int(status.progress() * 100)}%")
        
        video_id = response.get('id')
        logging.info(f"Upload video completato. ID Video: {video_id}")

        # Ora tenta l'upload della thumbnail, se fornita e valida
        if thumbnail_path and video_id:
            logging.info(f"Caricamento thumbnail: {thumbnail_path.name}")
            try:
                thumb_media = MediaFileUpload(str(thumbnail_path))
                thumb_request = youtube_service.thumbnails().set(
                    videoId=video_id,
                    media_body=thumb_media
                )
                thumb_response = thumb_request.execute()
                logging.info(f"Upload thumbnail completato. URL: {thumb_response['items'][0]['default']['url']}")
            except HttpError as e_thumb:
                 # Logga l'errore ma non considerarlo fatale per l'upload principale
                 logging.error(f"Errore durante l'upload della thumbnail per video ID {video_id}: {e_thumb}")
                 # Restituisci comunque l'ID del video
            except Exception as e_thumb_generic:
                 logging.exception(f"Errore imprevisto durante l'upload della thumbnail: {e_thumb_generic}")

        return video_id # Restituisci l'ID del video caricato con successo

    except HttpError as e:
        logging.error(f'Errore HTTP durante l\'upload: {e.resp.status} {e.content}')
        return None
    except Exception as e:
        logging.exception(f"Errore imprevisto durante l'upload del video: {e}")
        return None

# Blocco per testare l'autenticazione (eseguire `python -m youtube_uploader.uploader` dalla root)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    secrets = Path('client_secret.json') # Assumi sia nella root del progetto
    creds = Path('token.json') # Salverà/Leggerà qui le credenziali
    
    if not secrets.exists():
        print(f"ERRORE: File '{secrets}' non trovato. Assicurati di averlo scaricato e posizionato qui.")
    else:
        print("Test autenticazione YouTube...")
        service = get_authenticated_service(secrets, creds)
        if service:
            print("Autenticazione riuscita! Oggetto service creato.")
            # Potresti aggiungere qui un piccolo test API, tipo listare le categorie
            # COMMENTIAMO IL BLOCCO DI TEST API PER EVITARE ERRORI DI SCOPE
            # try:
            #      request = service.videoCategories().list(part="snippet", regionCode="IT") # Esempio IT
            #      response = request.execute()
            #      print("Categorie video disponibili (IT):")
            #      for item in response.get("items", []):
            #          print(f" - ID: {item['id']}, Titolo: {item['snippet']['title']}")
            # except Exception as e_test:
            #      print(f"Errore durante chiamata API di test: {e_test}")
        else:
            print("Autenticazione fallita.") 