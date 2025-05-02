import logging
import openai
import os
import re # Importa modulo regex per split più avanzato
import json # Assicurati che json sia importato

def add_pauses_to_long_segments(text: str, max_words_no_pause: int = 18) -> str:
    """Aggiunge virgole a segmenti di frase troppo lunghi senza punteggiatura.

    Args:
        text: Il testo da elaborare.
        max_words_no_pause: Numero massimo di parole consentite in un segmento
                             senza una pausa (virgola, punto, ecc.).

    Returns:
        Il testo modificato con virgole aggiunte.
    """
    sentences = re.split(r'([.?!])', text) # Divide mantenendo i delimitatori
    output_sentences = []
    
    # Ricostruisce le frasi dai pezzi splittati
    processed_text = ""
    temp_sentence = ""
    for i, part in enumerate(sentences):
        if i % 2 == 0: # Parte di testo
            temp_sentence += part
        else: # Delimitatore
            temp_sentence += part
            if temp_sentence.strip(): # Processa la frase completa
                words = temp_sentence.split()
                if len(words) > max_words_no_pause:
                    # Controlla se ci sono già pause interne
                    has_internal_pause = any(p in temp_sentence for p in [",", ";", ":", "..."])
                    if not has_internal_pause:
                        # Non ci sono pause, inserisci una virgola circa a metà
                        insert_pos = len(words) // 2
                        # Trova lo spazio più vicino a metà frase per inserire la virgola
                        word_indices = [match.start() for match in re.finditer(r'\s+', temp_sentence)]
                        if insert_pos < len(word_indices):
                            split_index = word_indices[insert_pos]
                            # Inserisci la virgola
                            temp_sentence = temp_sentence[:split_index] + "," + temp_sentence[split_index:]
                            logging.debug(f"Aggiunta pausa a frase lunga: {temp_sentence[:50]}...")
                        else:
                             logging.warning(f"Non è stato possibile trovare un punto di inserimento valido per la pausa in: {temp_sentence[:50]}...")
                processed_text += temp_sentence
            temp_sentence = "" # Resetta per la prossima frase
    
    # Aggiungi eventuali parti rimanenti (se il testo non finisce con un delimitatore)
    if temp_sentence.strip():
         processed_text += temp_sentence
         
    # TODO: La logica sopra per lo split e rejoin è complessa.
    # Un approccio più semplice potrebbe essere iterare sulle parole e 
    # inserire una virgola se un contatore supera max_words_no_pause
    # e non si incontra punteggiatura, ma potrebbe essere meno preciso.
    # Per ora, usiamo un approccio conservativo: aggiungiamo solo se *l'intera* frase
    # non ha pause ed è troppo lunga.
    # --- Approccio Semplificato Alternativo (da testare se il precedente è problematico) ---
    # final_text = []
    # words = text.split()
    # word_count_since_pause = 0
    # for word in words:
    #     final_text.append(word)
    #     word_count_since_pause += 1
    #     # Se la parola finisce con punteggiatura che indica pausa, resetta contatore
    #     if word.endswith(( '.', ',', '?', '!', ';', ':')):
    #         word_count_since_pause = 0
    #     # Se superiamo il limite e la parola corrente non è l'inizio di una nuova frase
    #     elif word_count_since_pause >= max_words_no_pause and not word[0].isupper(): 
    #         # Inserisci una virgola prima dell'ultimo spazio aggiunto
    #         if final_text:
    #             final_text.insert(-1, ",") # Inserisce prima dell'ultima parola aggiunta
    #             logging.debug(f"Aggiunta pausa dopo {max_words_no_pause} parole vicino a: ...{' '.join(final_text[-5:])}")
    #             word_count_since_pause = 0 # Resetta contatore
    # return " ".join(final_text)
    # --- Fine Approccio Semplificato ---
    
    # Per ora restituiamo l'output dell'approccio con re.split (più conservativo)
    return processed_text.strip() # Assicura che non ci siano spazi extra all'inizio/fine

def process_text(text: str, config) -> dict | None:
    """Utilizza OpenAI per generare un riassunto, parole chiave, titolo thumbnail, titolo YouTube e descrizione YouTube."""
    logging.info("Avvio elaborazione testo con OpenAI...")
    api_key = config.get('API_KEYS', 'OPENAI_API_KEY', fallback=None)
    if not api_key:
        logging.error("Chiave API OpenAI non configurata.")
        return None

    # --- PULIZIA CHIAVE API ---
    # Rimuovi eventuali virgolette iniziali/finali lette dal config
    cleaned_api_key = api_key.strip().strip('"')
    if cleaned_api_key != api_key:
        logging.debug("Rimosse virgolette dalla chiave API letta.")
    if not cleaned_api_key.startswith("sk-"):
        logging.warning("La chiave API pulita non sembra iniziare con 'sk-'. Potrebbe esserci un problema.")
    # --- FINE PULIZIA ---

    # Usa la chiave pulita
    # openai.api_key = cleaned_api_key # Vecchio modo, non necessario con nuovo client
    model_raw = config.get('AI_PROCESSOR', 'MODEL', fallback='gpt-3.5-turbo')
    # Pulisci eventuali spazi extra o virgolette dal nome del modello
    model = model_raw.strip().strip('"')
    logging.info(f"Utilizzo del modello OpenAI: '{model}' (letto come '{model_raw}')") # Log del modello

    target_words = config.getint('AI_PROCESSOR', 'SUMMARY_TARGET_WORDS', fallback=350)
    num_keywords = config.getint('AI_PROCESSOR', 'NUM_KEYWORDS', fallback=7)

    try:
        # Costruzione del prompt (AGGIORNATO per titolo/descrizione YouTube)
        instructions = f"""
        Dato il seguente testo di un articolo di notizie, esegui questi **cinque** compiti:
        1.  Crea una **rielaborazione narrativa MOLTO dettagliata ed estesa** del testo in italiano, adatta per essere letta ad alta voce in un video della durata di **ALMENO 2 minuti, idealmente 2.5-3 minuti**. Per raggiungere questa lunghezza, **EVITA ECCESSIVA CONCISIONE**: elabora i punti chiave, aggiungi dettagli contestuali o di background se pertinenti e possibili, descrivi gli eventi in modo più approfondito, e usa un linguaggio più descrittivo. L'output dovrebbe essere indicativamente tra **{int(target_words * 2.0)}-{int(target_words * 2.0 + 200)} parole**. Mantieni le informazioni chiave ma rendi il testo scorrevole e coinvolgente come una narrazione. **IMPORTANTE: Inserisci pause naturali nel testo usando virgole o puntini di sospensione (...) nei punti in cui un lettore farebbe una pausa per respiro o enfasi, specialmente per spezzare frasi lunghe. Allunga il discorso anche a costo di ripeterti.**
        2.  Estrai esattamente {num_keywords} parole chiave o brevi frasi chiave (massimo 3 parole per frase) semanticamente rilevanti dal testo originale. Elencale separate da virgola.
        3.  Crea un **titolo molto breve e accattivante** per una thumbnail video, basato sul contenuto principale dell'articolo. Il titolo deve essere composto da **massimo 4 parole**.
        4.  Crea un **titolo ottimizzato per YouTube** (massimo 70 caratteri) che sia informativo ma anche **fortemente clickbait** per massimizzare i click, basato sul contenuto principale dell'articolo. Non usare emoticons.
        5.  Crea una **descrizione per YouTube** che riassuma l'articolo in modo conciso e includa alcune delle parole chiave più importanti. La descrizione deve essere scritta in terza persona e deve avere un tono professionale..
        6.  Genera una lista di **circa 10-15 tag aggiuntivi** ottimizzati per la ricerca e la scoperta su YouTube, pertinenti al contenuto dell'articolo. Elencali separati da virgola.

        Fornisci la risposta **ESATTAMENTE** nel seguente formato JSON (senza ```json all'inizio o alla fine):
        {{
          "Narrazione": "[La tua rielaborazione narrativa MOLTO dettagliata ed estesa qui]",
          "Keywords": "[keyword1, keyword2, ...]",
          "TitoloThumbnail": "[Il tuo titolo breve per thumbnail qui]",
          "TitoloYouTube": "[Il tuo titolo clickbait per YouTube qui]",
          "DescrizioneYouTube": "[La tua breve descrizione per YouTube qui]",
          "TagYouTube": "[tag1, tag2, tag_aggiuntivo1, ...]"
        }}
        """
        
        # Combina istruzioni e testo in modo più semplice
        # Rimuovo il vecchio prompt_content
        # prompt_content = instructions + "\n\nTesto dell'articolo:\n---\n" + text + "\n---"

        logging.debug(f"Invio prompt a OpenAI (modello {model}). Lunghezza testo input: {len(text)} caratteri.")
        
        # Passa la chiave pulita al client
        client = openai.OpenAI(api_key=cleaned_api_key) 
        
        # Usa la variabile 'model' pulita
        response = client.chat.completions.create(
             model=model,
             messages=[
                 {"role": "system", "content": "Sei un assistente AI specializzato nell'elaborazione di testi giornalistici e nella creazione di contenuti per video YouTube (titoli, descrizioni, narrazioni). Rispondi SEMPRE nel formato JSON richiesto."}, # Ruolo di sistema aggiornato
                 {"role": "user", "content": f"{instructions}\n\nTesto dell'articolo:\n---\n{text}\n---"} # Passa istruzioni e testo direttamente
             ],
             temperature=0.8, # Aumentata ulteriormente per favorire lunghezza/varietà
             # max_tokens=1200 # Aumentare se necessario per risposte più lunghe
             # response_format={ "type": "json_object" } # Abilita se il modello lo supporta e dà problemi di formato
         )

        logging.debug("Risposta ricevuta da OpenAI.")
        content = response.choices[0].message.content.strip()

        # Parsing della risposta (AGGIORNATO per nuovi campi)
        youtube_title_part = None # Inizializza nuovi campi
        youtube_desc_part = None
        youtube_tags_part = None # NUOVO: Inizializza tag YouTube
        try:
            parsed_response = json.loads(content)
            summary_part = parsed_response.get("Narrazione")
            keywords_part = parsed_response.get("Keywords")
            thumbnail_title_part = parsed_response.get("TitoloThumbnail")
            youtube_title_part = parsed_response.get("TitoloYouTube")
            youtube_desc_part = parsed_response.get("DescrizioneYouTube")
            youtube_tags_part = parsed_response.get("TagYouTube") # NUOVO: Estrai tag YouTube

            # Verifica che tutti i campi richiesti siano presenti
            # Modificato per includere anche youtube_tags_part nella verifica principale
            if not all([summary_part, keywords_part, thumbnail_title_part, youtube_title_part, youtube_desc_part, youtube_tags_part]):
                missing_fields = [k for k, v in parsed_response.items() if not v]
                logging.error(f"Formato JSON ricevuto ma campi mancanti o vuoti: {missing_fields} in \n{content}")
                # Se mancano campi essenziali (narrazione, keywords base, titolo thumb), fallisci
                if not summary_part or not keywords_part or not thumbnail_title_part:
                     return None
                # Se mancano solo campi YT (titolo, desc, tags), avvisa ma procedi con fallback
                logging.warning("Campi TitoloYouTube, DescrizioneYouTube o TagYouTube mancanti o vuoti nella risposta AI.")
        except json.JSONDecodeError:
            logging.error(f"Errore nel parsing JSON della risposta da OpenAI: \n{content}")
            # Tentativo di fallback (meno probabile che funzioni per tutti i campi)
            logging.warning("Tentativo di parsing fallback con delimitatori...")
            summary_part, keywords_part, thumbnail_title_part = None, None, None
            youtube_title_part, youtube_desc_part = None, None # Assicura siano None
            youtube_tags_part = None # Assicura sia None

            lines = content.split('\n')
            # Logica di fallback migliorata (cerca chiavi JSON-like anche senza parsing)
            for line in lines:
                 line_lower = line.lower()
                 if ':"' in line: # Cerca coppie chiave-valore
                     try:
                         # Rimuovi eventuali virgole finali e spazi, poi splitta
                         key_value = line.strip().rstrip(',').split(':', 1)
                         if len(key_value) == 2:
                             key = key_value[0].strip().strip('"').lower()
                             value = key_value[1].strip().strip('"')
                             if key == "narrazione": summary_part = value
                             elif key == "keywords": keywords_part = value
                             elif key == "titolothumbnail": thumbnail_title_part = value
                             elif key == "titoloyoutube": youtube_title_part = value
                             elif key == "descrizioneyoutube": youtube_desc_part = value
                             elif key == "tagyoutube": youtube_tags_part = value # NUOVO: Fallback tags
                     except Exception:
                         continue # Ignora linee malformate

            if not summary_part or not keywords_part or not thumbnail_title_part:
                 logging.error("Parsing di fallback fallito per campi essenziali.")
                 return None
            else:
                 logging.info("Parsing di fallback riuscito per campi essenziali (ma formato JSON preferibile).")
                 if not youtube_title_part or not youtube_desc_part or not youtube_tags_part: # Aggiunto controllo tags nel log
                     logging.warning("Parsing di fallback non ha trovato TitoloYouTube, DescrizioneYouTube o TagYouTube.")

        # Pulizia keywords (invariato per le keywords principali)
        keywords_list = [k.strip().rstrip('.') for k in keywords_part.split(',') if k.strip()] if keywords_part else []
        # NUOVO: Pulizia Tag YouTube
        youtube_tags_list = [tag.strip() for tag in youtube_tags_part.split(',') if tag.strip()] if youtube_tags_part else []

        # --- AGGIUNTA PAUSE --- (invariato)
        logging.debug("Testo originale AI (Narrazione): %s...", summary_part[:100] if summary_part else "N/A")
        processed_summary = add_pauses_to_long_segments(summary_part) if summary_part else None
        logging.debug("Testo (Narrazione) con pause aggiunte: %s...", processed_summary[:100] if processed_summary else "N/A")
        # --- FINE AGGIUNTA PAUSE ---
        
        # Log dei nuovi campi
        logging.info(f"Rielaborazione ({len(processed_summary.split()) if processed_summary else 0} parole), "
                     f"Titolo Thumbnail ('{thumbnail_title_part}'), "
                     f"Titolo YouTube ('{youtube_title_part}'), "
                     f"Keywords: {keywords_list}, "
                     f"Tag YouTube: {youtube_tags_list}, " # Log aggiornato
                     f"Descrizione YouTube: '{youtube_desc_part[:50]}...'")
        
        # Restituisci il dizionario aggiornato con i nuovi campi
        return {
            'summary': processed_summary, # Può essere None se AI fallisce
            'keywords': keywords_list,    # Keywords principali
            'thumbnail_title': thumbnail_title_part, # Può essere None
            'youtube_title': youtube_title_part,     # Può essere None
            'youtube_description': youtube_desc_part, # Può essere None
            'youtube_tags': youtube_tags_list # NUOVO: Lista tag per YouTube
        }

    except openai.APIError as e:
        logging.error(f"Errore API OpenAI: {e}")
        return None
    except Exception as e:
        logging.exception(f"Errore imprevisto durante l'interazione con OpenAI: {e}")
        return None
