import logging
import requests
import os
from pathlib import Path
import time
from duckduckgo_search import DDGS # Importa la libreria DDGS
from urllib.parse import urlparse
from io import BytesIO # Necessario per leggere l'immagine da bytes
from PIL import Image, ExifTags # Importa Pillow

# --- Funzione specifica per DuckDuckGo --- 

def search_duckduckgo_images(query: str, max_results: int) -> list[str]:
    """Cerca immagini su DuckDuckGo e restituisce gli URL delle immagini."""
    logging.info(f"Eseguo ricerca immagini su DuckDuckGo per: '{query}'")
    urls = []
    try:
        # La libreria potrebbe richiedere aggiustamenti sui parametri
        # size='Large', color='color', type_image='photo', layout='Wide'
        # license_image: Any, Creative Commons, Public Domain
        # NOTA: Il filtro licenza potrebbe non essere affidabile!
        with DDGS() as ddgs:
            # Iteriamo sui risultati della ricerca immagini
            # Nota: max_results è un limite superiore, potrebbe restituirne meno
            ddgs_image_gen = ddgs.images(
                query,
                region="wt-wt", # Worldwide
                safesearch="off", # O 'moderate' o 'strict'
                size=None, # Prova None per più risultati, o 'Large'
                # type_image='photo', # Filtra per tipo se necessario
                layout=None, # O 'Wide' per orizzontali
                # license_image="Creative Commons" # !!! ATTENZIONE: filtro non garantito/affidabile !!!
                max_results=max_results + 10 # Chiedi un po' di più per avere margine
            )
            
            if not ddgs_image_gen:
                logging.warning(f"DuckDuckGo non ha restituito risultati immagine per '{query}'")
                return []

            count = 0
            for result in ddgs_image_gen:
                if count >= max_results:
                    break
                if result and 'image' in result:
                    urls.append(result['image']) # Estrai l'URL diretto dell'immagine
                    count += 1
                
        logging.info(f"DuckDuckGo: Trovate {len(urls)} immagini per query '{query}'")

    except Exception as e:
        logging.exception(f"Errore durante la ricerca immagini con DuckDuckGo per '{query}': {e}")
    
    return urls

# --- Funzione per il download (MODIFICATA per specchiare e pulire) ---

def download_image(url: str, save_path: Path) -> bool:
    """Scarica un'immagine, la specchia orizzontalmente, rimuove i metadati e la salva."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, stream=True, timeout=30, headers=headers) 
        response.raise_for_status()
        
        # Leggi i dati dell'immagine in memoria
        image_data = BytesIO(response.content)
        
        # Apri con Pillow
        with Image.open(image_data) as img:
            logging.debug(f"Immagine aperta con Pillow: {url} (formato: {img.format}, modo: {img.mode}, dimensioni: {img.size})")
            
            # Specchia l'immagine orizzontalmente
            img_flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
            logging.debug(f"Immagine specchiata: {save_path.name}")

            # Salva l'immagine specchiata senza metadati EXIF
            # Nota: img.save() di Pillow di solito non include EXIF a meno che specificato.
            # Per sicurezza, assicuriamoci che exif non venga passato.
            # Converto in RGB se necessario per evitare problemi con formati come P (palette)
            if img_flipped.mode == 'P' or img_flipped.mode == 'RGBA':
                 img_flipped = img_flipped.convert('RGB')
                 logging.debug(f"Immagine convertita in RGB per salvataggio JPG: {save_path.name}")

            img_flipped.save(save_path, format='JPEG', quality=90, exif=b'') # Specifica formato, qualità e exif vuoto
            
        logging.debug(f"Immagine scaricata, specchiata e pulita: {save_path}")
        return True
        
    except requests.exceptions.Timeout:
        logging.error(f"Timeout durante il download di {url}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Errore di rete durante il download di {url}: {e}")
        return False
    except Image.UnidentifiedImageError:
        logging.error(f"Impossibile identificare/aprire l'immagine scaricata da {url}. Potrebbe non essere un formato supportato o essere corrotta.")
        # Rimuovi file vuoto/corrotto se creato
        if save_path.exists(): 
             try: save_path.unlink() 
             except OSError: pass
        return False
    except Exception as e:
        logging.exception(f"Errore durante il download/processing/salvataggio di {url} in {save_path}: {e}")
        # Rimuovi file parziale/corrotto se creato
        if save_path.exists(): 
             try: save_path.unlink() 
             except OSError: pass
        return False

# --- Funzione Principale del Modulo (modificata) --- 

def find_and_download_images(keywords: list[str], temp_dir: Path, config, article_title: str | None = None) -> list[Path]:
    """Cerca immagini basate sul titolo o sulle keywords e le scarica."""
    logging.info(f"Ricerca immagini per keywords: {keywords} e Titolo: '{article_title}'")
    
    image_provider = config.get('IMAGE_FINDER', 'API_PROVIDER', fallback='duckduckgo').lower()
    logging.info(f"Provider immagini configurato: '{image_provider}' (letto come '{config.get('IMAGE_FINDER', 'API_PROVIDER', fallback='duckduckgo')}')")
    
    try:
        num_images_total = config.getint('SETTINGS', 'NUM_IMAGES', fallback=10)
    except ValueError:
        logging.warning("NUM_IMAGES non valido nel config, uso default 10")
        num_images_total = 10
    
    downloaded_image_paths = []
    image_urls = []

    if image_provider == 'duckduckgo':
        logging.info("Provider immagini impostato su DuckDuckGo (scraping). Attenzione alle licenze.")
        
        # --- Nuova Logica Query: Priorità al Titolo --- #
        search_query = None
        if article_title and len(article_title.strip()) > 5: # Usa titolo se non vuoto e ragionevolmente lungo
            search_query = article_title.strip()
            logging.info(f"Utilizzo il titolo dell'articolo come query di ricerca immagini: '{search_query}'")
        elif keywords:
            # Fallback: usa la prima keyword significativa se il titolo manca o è corto
            first_keyword = keywords[0].strip('.').strip()
            if first_keyword:
                 search_query = first_keyword
                 logging.warning(f"Titolo mancante o troppo corto. Uso la prima keyword come fallback per la ricerca immagini: '{search_query}'")
            else:
                 logging.error("Titolo mancante/corto e nessuna keyword valida trovata. Impossibile cercare immagini.")
                 return []
        else:
            logging.error("Né titolo né keywords disponibili. Impossibile cercare immagini.")
            return []
        # --- Fine Nuova Logica Query ---
            
        # Esegui la ricerca
        if search_query:
            image_urls = search_duckduckgo_images(search_query, num_images_total)
        else:
             # Già loggato sopra, ma per sicurezza
             logging.error("Nessuna query di ricerca valida determinata.")
             return []

    elif image_provider == 'unsplash':
        logging.warning("Provider Unsplash non ancora implementato.")
        # Qui andrebbe la logica per chiamare l'API Unsplash
        # key = config.get('API_KEYS', 'UNSPLASH_ACCESS_KEY', fallback=None)
        # if not key: logging.error("Chiave API Unsplash non configurata.")
        return [] # Per ora
    elif image_provider == 'pexels':
        logging.warning("Provider Pexels non ancora implementato.")
        # Qui logica per API Pexels
        return [] # Per ora
    else:
        logging.error(f"Provider immagini non supportato: {image_provider}")
        return []

    # --- Download delle immagini trovate --- 
    if not image_urls:
        logging.warning(f"Nessun URL immagine trovato per la query '{search_query if 'search_query' in locals() else 'N/A'}' con provider {image_provider}.")
        return []

    logging.info(f"Trovati {len(image_urls)} URL di immagini. Tentativo di scaricarne fino a {num_images_total}.")
    successful_downloads = 0
    image_index = 0
    processed_urls = set()

    # Cicla finché non abbiamo abbastanza immagini o finiamo gli URL
    while successful_downloads < num_images_total and image_index < len(image_urls):
        url = image_urls[image_index]
        image_index += 1 # Incrementa subito per il prossimo ciclo

        # Salta URL già processati (se DDG restituisce duplicati)
        if url in processed_urls:
            continue
        processed_urls.add(url)

            # Crea un nome file univoco
        try:
            # Prova a estrarre un nome sensato dall'URL, altrimenti usa timestamp
            parsed_url = urlparse(url)
            filename_base = Path(parsed_url.path).stem
            if not filename_base or len(filename_base) < 3: # Nome troppo corto o strano
                filename_base = f"image_{int(time.time() * 1000)}_{successful_downloads}"
            filename = f"{filename_base[:50]}.jpg" # Limita lunghezza, usa jpg come default
        except Exception:
            filename = f"image_{int(time.time() * 1000)}_{successful_downloads}.jpg"
            
        output_path = temp_dir / filename
            
        logging.debug(f"Tentativo download immagine {successful_downloads + 1}/{num_images_total} da: {url}")
        if download_image(url, output_path):
            downloaded_image_paths.append(output_path)
            successful_downloads += 1
        # Se download fallisce, il log è già in download_image

    logging.info(f"Totale immagini scaricate: {successful_downloads}")
    return downloaded_image_paths
