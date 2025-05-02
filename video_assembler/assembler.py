import logging
from pathlib import Path
import ffmpeg # Importa ffmpeg-python
from PIL import Image, UnidentifiedImageError # Import specifico
import math
import tempfile # Per file temporanei (lista immagini)
import os # Per usare FFMPEG_BINARY
import shutil # Per rimuovere la directory temporanea
from datetime import timedelta # Per SRT offset

# --- DEBUG: Stampa sys.path prima dell'import MoviePy ---
# import sys
# print("--- DEBUG: sys.path before MoviePy import ---")
# for p in sys.path:
#     print(p)
# print("--- END DEBUG ---")
# --- FINE DEBUG ---

# Aggiungi import per moviepy
# Rimosso blocco try...except per import MoviePy non più necessario

# Aggiungi import per timedelta per SRT
from datetime import timedelta

# Configura il percorso dell'eseguibile ffmpeg se necessario (opzionale)
# Ad esempio, se ffmpeg non è nel PATH di sistema standard
# ffmpeg_path = "/opt/homebrew/bin/ffmpeg" # Esempio macOS Homebrew
# os.environ["FFMPEG_BINARY"] = ffmpeg_path

def get_video_or_audio_duration(file_path: Path) -> float | None:
    """Ottiene la durata di un file video o audio usando ffprobe."""
    try:
        logging.debug(f"Eseguo ffprobe su: {file_path}")
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe['format']['duration'])
        logging.debug(f"Durata rilevata per {file_path}: {duration}s")
        return duration
    except ffmpeg.Error as e:
        err_msg = e.stderr.decode(errors='ignore') if e.stderr else 'Errore ffprobe sconosciuto'
        logging.error(f"Errore ffprobe per {file_path}: {err_msg}")
        return None
    except Exception as e:
        logging.exception(f"Errore imprevisto nell'ottenere la durata di {file_path}: {e}")
        return None

def resize_image(image_path: Path, target_size: tuple[int, int], temp_dir: Path) -> Path | None:
    """Ridimensiona un'immagine per riempire target_size mantenendo l'aspect ratio, ritagliando l'eccesso dal centro."""
    try:
        img = Image.open(image_path).convert('RGB') # Assicurati che sia RGB
        original_width, original_height = img.size
        target_width, target_height = target_size

        img_ratio = original_width / original_height
        target_ratio = target_width / target_height

        if img_ratio > target_ratio:
            scale_height = target_height
            scale_width = int(scale_height * img_ratio)
        else:
            scale_width = target_width
            scale_height = int(scale_width / img_ratio)

        img_resized = img.resize((scale_width, scale_height), Image.Resampling.LANCZOS)

        crop_x = (scale_width - target_width) / 2
        crop_y = (scale_height - target_height) / 2
        crop_box = (crop_x, crop_y, crop_x + target_width, crop_y + target_height)
        img_cropped = img_resized.crop(crop_box)

        resized_filename = f"{image_path.stem}_resized_cropped{image_path.suffix}"
        # Salva sempre come JPEG per consistenza con la pipeline ffmpeg
        output_path = (temp_dir / resized_filename).with_suffix(".jpg") 
        img_cropped.save(output_path, format='JPEG', quality=90)
        logging.debug(f"Immagine ridimensionata/ritagliata salvata in: {output_path}")
        return output_path
    except UnidentifiedImageError:
        logging.error(f"Errore PIL: Impossibile identificare il file immagine {image_path}.")
        return None
    except (IOError, FileNotFoundError) as e:
        logging.error(f"Errore IO durante l'accesso a {image_path}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Errore imprevisto durante il ridimensionamento di {image_path}: {e}")
        return None

# --- NUOVA FUNZIONE HELPER per srt ---
def adjust_srt_timestamps(srt_path: Path, offset_seconds: float, output_srt_path: Path) -> bool:
    """Legge un file SRT, aggiunge un offset ai timestamp e scrive un nuovo file SRT."""
    try:
        import srt # Importa qui per non bloccare tutto se non serve/manca
    except ImportError:
        logging.error("Libreria 'srt' non trovata. Impossibile aggiustare i timestamp dei sottotitoli. Installa con `pip install srt`")
        return False
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            original_subs = list(srt.parse(f))
        adjusted_subs = []
        for sub in original_subs:
            sub.start = sub.start + timedelta(seconds=offset_seconds)
            sub.end = sub.end + timedelta(seconds=offset_seconds)
            adjusted_subs.append(sub)
        adjusted_srt_content = srt.compose(adjusted_subs)
        with open(output_srt_path, 'w', encoding='utf-8') as f:
            f.write(adjusted_srt_content)
        logging.info(f"File SRT con timestamp aggiustati salvato in: {output_srt_path}")
        return True
    except FileNotFoundError:
        logging.error(f"File SRT originale non trovato: {srt_path}")
        return False
    except Exception as e:
        logging.exception(f"Errore durante l'aggiustamento dei timestamp SRT per {srt_path}: {e}")
        return False

# --- Funzione Principale di Assemblaggio (ffmpeg-python con intro) ---
def assemble_video(
    image_paths: list[Path],
    audio_path: Path,
    output_path: Path,
    config,
    srt_path: Path | None = None,
    intro_video_path: Path | None = None,
    outro_video_path: Path | None = None # Mantenuto per firma, ma ignorato
) -> Path | None:
    """Assembla un video con intro, slideshow, outro, audio e sottotitoli usando ffmpeg-python."""
    logging.info("Avvio assemblaggio video con ffmpeg-python (supporto intro/outro)...")

    # Inizializza variabili che potrebbero non essere definite in tutti i branch
    srt_temp_dir = None # <--- INIZIALIZZA QUI

    if not audio_path or not audio_path.exists():
        logging.error(f"File audio principale non trovato o non valido: {audio_path}")
        return None

    main_audio_duration = get_video_or_audio_duration(audio_path)
    if main_audio_duration is None or main_audio_duration <= 0:
        logging.error("Impossibile ottenere durata audio principale valida.")
        return None
    logging.info(f"Durata audio principale: {main_audio_duration:.2f} secondi")

    # Impostazioni video
    resolution_str = config.get('SETTINGS', 'VIDEO_RESOLUTION', fallback='720p')
    video_size = (1920, 1080) if resolution_str == '1080p' else (1280, 720)
    fps = 24

    # Gestione Intro
    intro_input = None
    intro_video_stream = None
    intro_audio_stream = None
    intro_duration = 0.0
    if intro_video_path and intro_video_path.exists():
        logging.info(f"Processamento video intro: {intro_video_path}")
        intro_duration = get_video_or_audio_duration(intro_video_path)
        if intro_duration is None or intro_duration <= 0:
            logging.warning(f"Impossibile ottenere durata valida per intro {intro_video_path}. Verrà ignorato.")
            intro_duration = 0.0
        else:
            try:
                # --- REVISIONE: Selezione esplicita .video / .audio --- #
                intro_input = ffmpeg.input(str(intro_video_path))
                
                # Seleziona stream video e applica filtri
                intro_v_stream_raw = intro_input.video
                intro_video_stream = intro_v_stream_raw.filter(
                    'scale', width=video_size[0], height=video_size[1], force_original_aspect_ratio='decrease'
                ).filter(
                    'pad', width=video_size[0], height=video_size[1], x='(ow-iw)/2', y='(oh-ih)/2', color='black'
                ).filter('fps', fps=fps, round='up').filter('setpts', 'PTS-STARTPTS')

                # Seleziona stream audio e applica filtri (se esiste)
                try:
                    intro_a_stream_raw = intro_input.audio
                    intro_audio_stream = intro_a_stream_raw.filter('asetpts', 'PTS-STARTPTS')
                    logging.debug("Trovato e processato stream audio nell'intro.")
                except ffmpeg.Error: # Gestisce caso di input senza audio
                    intro_audio_stream = None
                    logging.debug("Nessun stream audio trovato nell'intro.")
                # --- FINE REVISIONE --- #
                
                # --- RIMOSSO BLOCCO SPLIT --- #

            except ffmpeg.Error as e:
                logging.error(f"Errore durante il processamento dell'input intro {intro_video_path}: {e.stderr.decode(errors='ignore')}")
                intro_video_stream = None
                intro_audio_stream = None
                intro_duration = 0.0
    else:
         if intro_video_path: logging.warning(f"Percorso intro {intro_video_path} specificato ma non trovato.")

    # Gestione Slideshow Immagini
    if not image_paths:
        logging.warning("Nessuna immagine fornita per lo slideshow.")
        # Potrebbe avere senso creare un video con solo l'intro, ma per ora usciamo se mancano le immagini
        return None

    temp_image_dir = Path(tempfile.mkdtemp(prefix="ffmpeg_slideshow_"))
    logging.debug(f"Directory temporanea per immagini slideshow creata: {temp_image_dir}")

    resized_image_paths = []
    for img_path in image_paths:
        resized_path = resize_image(img_path, video_size, temp_image_dir)
        if resized_path:
            resized_image_paths.append(resized_path)
        else:
            logging.warning(f"Salto immagine {img_path} (errore ridimensionamento).")

    if not resized_image_paths:
        logging.error("Nessuna immagine valida disponibile per lo slideshow dopo il ridimensionamento.")
        try: shutil.rmtree(temp_image_dir)
        except OSError: pass
        return None

    num_images = len(resized_image_paths)
    single_image_duration = main_audio_duration / num_images
    logging.info(f"Slideshow: {num_images} immagini, durata per immagine: {single_image_duration:.2f}s")

    # --- Crea Stream Video Slideshow (NUOVO METODO: concat filter) ---
    slideshow_image_streams = []
    for img_path in resized_image_paths:
        # Crea un input per ogni immagine, loopato per la durata necessaria
        img_input = ffmpeg.input(
            str(img_path),
            loop=1,
            t=single_image_duration,
            framerate=fps
        ).video
        # Resetta i timestamp per ogni clip immagine
        img_stream_pts = img_input.filter('setpts', 'PTS-STARTPTS')
        slideshow_image_streams.append(img_stream_pts)

    # Concatena gli stream delle immagini per creare lo slideshow
    if len(slideshow_image_streams) > 1:
        slideshow_video_stream = ffmpeg.concat(*slideshow_image_streams, v=1, a=0)
    elif slideshow_image_streams:
        slideshow_video_stream = slideshow_image_streams[0]
    else:
        logging.error("Errore critico: nessun stream immagine per lo slideshow.")
        try: shutil.rmtree(temp_image_dir)
        except OSError: pass
        return None

    # --- Gestione Outro --- # NUOVO
    outro_input = None
    outro_video_stream = None
    outro_audio_stream = None
    outro_duration = 0.0
    if outro_video_path and outro_video_path.exists():
        logging.info(f"Processamento video outro: {outro_video_path}")
        outro_duration = get_video_or_audio_duration(outro_video_path)
        if outro_duration is None or outro_duration <= 0:
            logging.warning(f"Impossibile ottenere durata valida per outro {outro_video_path}. Verrà ignorato.")
            outro_duration = 0.0
        else:
            try:
                # --- REVISIONE: Selezione esplicita .video / .audio --- #
                outro_input = ffmpeg.input(str(outro_video_path))
                
                # Seleziona video e applica filtri
                outro_v_stream_raw = outro_input.video
                outro_video_stream = outro_v_stream_raw.filter(
                    'scale', width=video_size[0], height=video_size[1], force_original_aspect_ratio='decrease'
                ).filter(
                    'pad', width=video_size[0], height=video_size[1], x='(ow-iw)/2', y='(oh-ih)/2', color='black'
                ).filter('fps', fps=fps, round='up').filter('setpts', 'PTS-STARTPTS')
                
                # Seleziona audio e applica filtri (se esiste)
                try:
                    outro_a_stream_raw = outro_input.audio
                    outro_audio_stream = outro_a_stream_raw.filter('asetpts', 'PTS-STARTPTS')
                    logging.debug("Trovato e processato stream audio nell'outro.")
                except ffmpeg.Error:
                    outro_audio_stream = None
                    logging.debug("Nessun stream audio trovato nell'outro.")
                # --- FINE REVISIONE --- #
                    
                # --- RIMOSSO BLOCCO SPLIT --- #

            except ffmpeg.Error as e:
                logging.error(f"Errore durante il processamento dell'input outro {outro_video_path}: {e.stderr.decode(errors='ignore')}")
                outro_video_stream = None
                outro_audio_stream = None
                outro_duration = 0.0
    else:
         if outro_video_path: logging.warning(f"Percorso outro {outro_video_path} specificato ma non trovato.")

    # --- Combina Stream Video (Intro + Slideshow + Outro) --- # MODIFICATO
    streams_to_concat_v = []
    if intro_video_stream:
        streams_to_concat_v.append(intro_video_stream)
    streams_to_concat_v.append(slideshow_video_stream)
    if outro_video_stream: # Aggiungi l'outro video se esiste
        streams_to_concat_v.append(outro_video_stream)
        
    if len(streams_to_concat_v) > 1:
        logging.debug(f"Concateno {len(streams_to_concat_v)} stream video (intro/slideshow/outro).")
        concatenated_video = ffmpeg.concat(*streams_to_concat_v, v=1, a=0)
    elif streams_to_concat_v:
        concatenated_video = streams_to_concat_v[0]
    else:
         logging.error("Errore: nessun stream video finale da processare.")
         # Pulizia directory temporanea immagini
         try: shutil.rmtree(temp_image_dir)
         except OSError: pass
         return None
    logging.debug("Stream video concatenato (prima di subs).")
    # --- FINE DEBUG --- #

    # --- Gestione Audio --- # MODIFICATO PER OUTRO
    main_audio_input = ffmpeg.input(str(audio_path))
    # --- RIMOZIONE SPLIT PER MAIN AUDIO --- #
    main_audio_stream = main_audio_input.audio.filter('asetpts', 'PTS-STARTPTS')
    # main_audio_split = main_audio_stream_raw.split()
    # main_audio_stream = main_audio_split[0]
    # --- FINE RIMOZIONE --- #

    # Costruisci la catena audio
    streams_to_concat_a = []
    if intro_audio_stream:
        streams_to_concat_a.append(intro_audio_stream)
    else: 
        # Se l'intro non ha audio, ma esiste un video intro, aggiungi silenzio per quella durata
        if intro_duration > 0:
             logging.debug(f"Aggiungo silenzio iniziale per durata intro ({intro_duration}s).")
             # Usa anullsrc per creare silenzio e aevalsrc per impostare durata
             intro_silence = ffmpeg.input('anullsrc', f='lavfi', r=44100).filter_('atrim', duration=intro_duration).filter_('asetpts', 'PTS-STARTPTS')
             streams_to_concat_a.append(intro_silence)
            
    streams_to_concat_a.append(main_audio_stream)
    
    if outro_audio_stream:
        streams_to_concat_a.append(outro_audio_stream)
    else:
        # Se l'outro non ha audio, ma esiste un video outro, aggiungi silenzio per quella durata
        if outro_duration > 0:
             logging.debug(f"Aggiungo silenzio finale per durata outro ({outro_duration}s).")
             outro_silence = ffmpeg.input('anullsrc', f='lavfi', r=44100).filter_('atrim', duration=outro_duration).filter_('asetpts', 'PTS-STARTPTS')
             streams_to_concat_a.append(outro_silence)

    if len(streams_to_concat_a) > 1:
         logging.debug(f"Concateno {len(streams_to_concat_a)} stream audio (intro/main/outro/silenzi)...")
         concatenated_audio = ffmpeg.concat(*streams_to_concat_a, v=0, a=1)
    elif streams_to_concat_a:
         concatenated_audio = streams_to_concat_a[0]
    else:
         logging.error("Errore: nessun stream audio finale da processare.")
         # Pulizia directory temporanea immagini
         try: shutil.rmtree(temp_image_dir)
         except OSError: pass
         return None
    logging.debug("Stream audio concatenato.")
    # --- FINE DEBUG --- #

    # --- Gestione Sottotitoli (SRT) --- # MODIFICATO per non usare temp_dir globale
    adjusted_srt_path_temp = None # Inizializza
    # --- REVISIONE: Applica subs a video concatenato --- #
    final_video_stream = concatenated_video # Inizia con il video concatenato
    
    if srt_path and srt_path.exists():
        logging.info(f"Trovato file SRT: {srt_path}")
        if intro_duration > 0:
            logging.info(f"Aggiusto timestamp SRT per intro ({intro_duration:.2f}s).")
            # Scrivi il file SRT aggiustato IN UNA NUOVA DIRECTORY TEMPORANEA specifica per SRT
            # Creiamo una directory temporanea solo se l'aggiustamento è necessario
            srt_temp_dir = Path(tempfile.mkdtemp(prefix="ffmpeg_srt_"))
            adjusted_srt_path_temp = srt_temp_dir / f"{srt_path.stem}_adjusted{srt_path.suffix}"
            logging.debug(f"Directory temporanea per SRT creata: {srt_temp_dir}")

            if adjust_srt_timestamps(srt_path, intro_duration, adjusted_srt_path_temp):
                logging.info(f"Utilizzo SRT aggiustato: {adjusted_srt_path_temp}")
                srt_filename_for_ffmpeg = str(adjusted_srt_path_temp.as_posix()) # Usa percorso aggiustato
            else:
                logging.warning("Fallito aggiustamento timestamp SRT. Provo ad usare l'originale.")
                srt_filename_for_ffmpeg = str(srt_path.as_posix()) # Fallback all'originale
                srt_temp_dir = None # Non servirà pulire se l'aggiustamento fallisce
        else:
            logging.info(f"Nessun intro, uso SRT originale: {srt_path}")
            srt_filename_for_ffmpeg = str(srt_path.as_posix())
            srt_temp_dir = None # Non serve directory temp per SRT
            
        # Applica stile sottotitoli dal config
        style_settings = config.get('SETTINGS', 'SUBTITLE_STYLE', fallback='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=1').strip('"')
        logging.info(f"Applico sottotitoli da: {srt_filename_for_ffmpeg}")
        
        # Applica il filtro subtitles DIRETTAMENTE allo stream video GIA' CONCATENATO
        try:
             final_video_stream = concatenated_video.filter('subtitles', filename=srt_filename_for_ffmpeg, force_style=style_settings)
             logging.debug("Filtro subtitles applicato con successo allo stream video concatenato.")
        except ffmpeg.Error as e_sub:
             logging.error(f"Errore ffmpeg durante l'applicazione del filtro subtitles: {e_sub.stderr.decode(errors='ignore')}")
             logging.warning("Procedo senza masterizzare i sottotitoli.")
        except Exception as e_sub_generic:
             logging.exception(f"Errore imprevisto durante l'applicazione del filtro subtitles: {e_sub_generic}")
             logging.warning("Procedo senza masterizzare i sottotitoli.")
    # --- FINE REVISIONE --- #

    # --- Assemblaggio Finale (ffmpeg) --- # MODIFICATO: Rimosso srt_options
    output_options = {
        'c:v': 'libx264',          # Codec video
        'preset': 'medium',          # Bilanciamento velocità/qualità
        'crf': 23,                  # Qualità video (valore più basso = qualità migliore)
        'c:a': 'aac',              # Codec audio
        'b:a': '192k',             # Bitrate audio
        'shortest': None,           # Termina quando lo stream più corto finisce (audio o video)
        'pix_fmt': 'yuv420p',       # Formato pixel per compatibilità
        'loglevel': 'warning'      # Livello di log ffmpeg
    }
    # Non aggiungiamo più srt_options qui
    # output_options.update(srt_options)
    
    logging.info(f"Inizio processo di rendering ffmpeg su: {output_path}")
    
    # --- DEBUG CHECKPOINT 3 --- #
    logging.debug(f"Stream video finale passato a ffmpeg.output: {final_video_stream}")
    # --- REVISIONE: Usa audio concatenato --- #
    logging.debug(f"Stream audio finale passato a ffmpeg.output: {concatenated_audio}")
    logging.debug(f"Opzioni output ffmpeg: {output_options}")
    # --- FINE DEBUG --- #

    # Crea il grafo ffmpeg combinando video (con o senza subs) e audio concatenati
    # Passa direttamente gli stream risultanti dalle concatenazioni (o dal filtro subs)
    stream = ffmpeg.output(final_video_stream, concatenated_audio, str(output_path), **output_options)

    try:
        # Esegui il comando ffmpeg
        stream.run(overwrite_output=True)
        logging.info(f"Video assemblato con successo: {output_path}")
    except ffmpeg.Error as e:
        err_msg = e.stderr.decode(errors='ignore') if e.stderr else 'Errore ffmpeg sconosciuto'
        logging.error(f"Errore durante l'assemblaggio video ffmpeg: {err_msg}")
        # Rimuovi file parziale se fallisce
        if output_path.exists():
            try: output_path.unlink()
            except OSError: pass
        # Pulizia directory temporanee
        try: shutil.rmtree(temp_image_dir)
        except OSError: pass
        if srt_temp_dir: # Pulisci dir SRT solo se è stata creata
             try: shutil.rmtree(srt_temp_dir)
             except OSError: pass
        return None
    except Exception as e:
        logging.exception(f"Errore imprevisto durante l'esecuzione di ffmpeg.run: {e}")
        # Pulizia directory temporanee
        try: shutil.rmtree(temp_image_dir)
        except OSError: pass
        if srt_temp_dir: 
             try: shutil.rmtree(srt_temp_dir)
             except OSError: pass
        return None

    # Pulizia directory temporanee DOPO il successo
    try: shutil.rmtree(temp_image_dir)
    except OSError as e:
         logging.warning(f"Impossibile rimuovere la directory temporanea immagini {temp_image_dir}: {e}")
    if srt_temp_dir: # Pulisci dir SRT solo se è stata creata
         try: shutil.rmtree(srt_temp_dir)
         except OSError as e:
              logging.warning(f"Impossibile rimuovere la directory temporanea SRT {srt_temp_dir}: {e}")

    # Verifica finale dell'esistenza e dimensione del file
    if output_path.exists() and output_path.stat().st_size > 0:
        logging.info(f"Verifica file output {output_path} completata (esiste e non è vuoto).")
        return output_path
    else:
        logging.error(f"Verifica file output {output_path} fallita (non trovato o vuoto dopo il rendering).")
        return None

# --- Funzione Deprecata (MoviePy) ---
# ... (Codice MoviePy omesso per brevità) ...

# --- Esempio di utilizzo (se eseguito come script) ---
# ... (Codice esempio omesso) ...
