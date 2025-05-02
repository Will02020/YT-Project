import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Rimuovo la costante ANSA_SECTION_URL, la logica cercherà sempre l'articolo sulla pagina fornita
# ANSA_SECTION_URL = "https://www.ansa.it/sito/notizie/cronaca/cronaca.shtml"

def find_latest_article_url(page_soup: BeautifulSoup, base_url: str) -> str | None:
    """Trova l'URL del primo articolo principale sulla pagina fornita (homepage o sezione)."""
    # Selettori aggiornati per cercare link articoli sia su homepage che sezioni (da più specifico a più generico)
    selectors = [
        'article.article-teaser-first h2 a',           # Articolo principale in alto (comune)
        'div.hp-block-rowTopLeft article.article-teaser h2 a', # Blocco sinistra homepage
        'div.news-block-main article.article-teaser-first h2 a', # Sezione: Blocco grande
        'div.widget-latest-news ul li h3.news-title a', # Sezione: Widget ultime notizie
        'ul.latest-articles li a',                     # Lista generica ultime notizie
        'div.article-content h2.title a',             # Trovato in precedenza, generico
        'h3.news-title a',                             # Titolo generico H3
        'article a[href*="/sito/notizie/"]'             # Link generico verso una notizia ANSA
    ]
    
    logging.debug(f"Tentativo di trovare link articolo su {base_url} con i selettori: {selectors}")
    for selector in selectors:
        latest_news_link = page_soup.select_one(selector)
        if latest_news_link and latest_news_link.has_attr('href'):
            relative_url = latest_news_link['href']
            # Evita link javascript o non validi
            if relative_url.startswith('javascript:') or not relative_url.strip():
                continue
            absolute_url = urljoin(base_url, relative_url)
            # Evita di ritornare la pagina base stessa se il link è solo '/'
            if absolute_url.strip('/') == base_url.strip('/'):
                continue
            logging.info(f"Trovato link potenziale articolo ({selector}): {absolute_url}")
            # Aggiungi un controllo per assicurarsi che sembri un articolo valido
            # Es: contiene /sito/notizie/ o una data nel path?
            if '/notizie/' in absolute_url:
                 logging.info(f"Link valido trovato: {absolute_url}")
                 return absolute_url
            else:
                 logging.debug(f"Link {absolute_url} scartato (non sembra un articolo - manca '/notizie/')")
                 
    logging.error(f"Impossibile trovare un link valido all'articolo più recente su {base_url} con i selettori provati.")
    return None

def extract_article_text(article_soup: BeautifulSoup, url: str) -> str | None:
    """Estrae il testo principale da una pagina articolo già parsata."""
    # Selettori comuni per il corpo dell'articolo su ANSA (da verificare/adattare)
    article_body_selectors = [
        'div.news-txt',         # Classe comune per il testo
        'div.post-entry',       # Usato in precedenza
        'div.article-body',     # Classe generica
        'article .body',        # Dentro un tag article
        'div[itemprop="articleBody"]' # Attributo schema.org
    ]
    
    article_body = None
    for selector in article_body_selectors:
        article_body = article_soup.select_one(selector)
        if article_body:
            logging.info(f"Trovato contenitore testo articolo con selettore: '{selector}'")
            break
            
    if not article_body:
        logging.error(f"Impossibile trovare il corpo dell'articolo principale per {url} con i selettori noti.")
        return None
        
    # Rimuovi elementi non desiderati (script, style, figure, etc.)
    for element in article_body(['script', 'style', 'aside', 'nav', 'figure', 'figcaption', 'video', 'iframe']):
        element.decompose()

    # Estrai il testo, unendo i paragrafi
    paragraphs = article_body.find_all('p', recursive=False) # Solo p diretti figli
    if not paragraphs: # Fallback: cerca p ovunque nel container
         paragraphs = article_body.find_all('p')
         
    text = '\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

    if text:
        # Pulizia finale: rimuovi la dicitura standard di copyright ANSA se presente alla fine
        copyright_string = "Riproduzione riservata © Copyright ANSA"
        cleaned_text = text.strip() # Rimuovi spazi bianchi iniziali/finali
        if cleaned_text.endswith(copyright_string):
            cleaned_text = cleaned_text[:-len(copyright_string)].strip()
            logging.debug(f"Rimossa stringa di copyright finale.")
        else:
            # A volte potrebbe esserci un punto dopo. Proviamo anche quello.
            copyright_string_dot = copyright_string + "."
            if cleaned_text.endswith(copyright_string_dot):
                 cleaned_text = cleaned_text[:-len(copyright_string_dot)].strip()
                 logging.debug(f"Rimossa stringa di copyright finale con punto.")
        
        logging.debug(f"Testo estratto (primi 300 caratteri): {cleaned_text[:300]}...")
        return cleaned_text # Restituisci il testo pulito
    else:
        logging.warning(f"Trovato corpo articolo ({selector}) ma nessun paragrafo (<p>) con testo significativo per {url}")
        return None

def extract_article_title(article_soup: BeautifulSoup, url: str) -> str | None:
    """Estrae il titolo principale da una pagina articolo già parsata."""
    title_selectors = [
        'h1.title',             # Titolo con classe specifica
        'h1.article-title',    # Altra classe comune
        'header h1',            # H1 dentro un header
        'h1[itemprop="headline"]', # Schema.org
        'h1'                   # H1 generico (meno specifico)
    ]
    for selector in title_selectors:
        title_element = article_soup.select_one(selector)
        if title_element:
            title_text = title_element.get_text(strip=True)
            if title_text:
                logging.info(f"Trovato titolo articolo con selettore '{selector}': '{title_text}'")
                return title_text
    logging.warning(f"Impossibile trovare un titolo H1 significativo per {url} con i selettori noti.")
    return None # O potremmo restituire una stringa vuota

def extract_news_content(start_url: str, config) -> dict | None:
    """
    Estrae il titolo e il contenuto testuale principale dall'articolo più recente trovato
    partendo dall'URL fornito (che può essere la homepage o una pagina di sezione).
    Restituisce un dizionario {'title': titolo, 'text': testo} o None in caso di errore.
    """
    logging.info(f"Avvio estrazione contenuto partendo da: {start_url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    article_url = None # Inizializza article_url
    try:
        # --- Fase 1: Scarica l'HTML della pagina iniziale (homepage o sezione) ---
        logging.debug(f"Scarico pagina iniziale: {start_url}")
        response = requests.get(start_url, headers=headers, timeout=15)
        response.raise_for_status()
        initial_soup = BeautifulSoup(response.content, 'html.parser')
        
        # --- Fase 2: Trova l'URL dell'articolo più recente su questa pagina ---
        article_url = find_latest_article_url(initial_soup, start_url)
        
        if not article_url:
            return None # Errore già loggato nella funzione helper
        
        # --- Fase 3: Scarica l'HTML dell'articolo specifico ---
        logging.info(f"Scarico contenuto dell'articolo da: {article_url}")
        response = requests.get(article_url, headers=headers, timeout=15)
        response.raise_for_status()
        article_soup = BeautifulSoup(response.content, 'html.parser')

        # --- Fase 4: Estrai titolo e testo dall'HTML dell'articolo ---
        logging.debug(f"Estrazione titolo e testo dall'articolo: {article_url}")
        article_title = extract_article_title(article_soup, article_url)
        article_text = extract_article_text(article_soup, article_url)

        if article_text: # Se abbiamo almeno il testo, procediamo
            return {'title': article_title if article_title else "", 'text': article_text}
        else:
            logging.error(f"Estrazione del testo fallita per l'articolo {article_url}, annullamento.")
            return None

    except requests.exceptions.RequestException as e:
        failed_url = article_url if article_url else start_url
        logging.error(f"Errore di rete durante il fetch di {failed_url}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Errore imprevisto durante l'estrazione (URL iniziale: {start_url}): {e}")
        return None
