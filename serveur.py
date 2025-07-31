# serveur.py

try:
    # --- Imports ---
    import sys
    import os
    from flask import Flask, render_template, Response, request, redirect, url_for, send_from_directory, jsonify
    import jinja2
    import cv2, json, uuid, numpy as np, traceback, threading, time, math, requests
    from datetime import datetime, timedelta
    from unidecode import unidecode
    import shutil
    from functools import wraps

    # ==============================================================================
    # <<< GESTION DES CHEMINS (Version Ultime qui fonctionne) >>>
    # ==============================================================================
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    os.chdir(base_path)
    app = Flask(__name__)
    template_folder_path = os.path.join(base_path, 'templates')
    my_loader = jinja2.FileSystemLoader(template_folder_path)
    app.jinja_loader = my_loader
    # ==============================================================================
        
    persistent_data_path = base_path

    # --- CONSTANTES ---
    APP_VERSION = "1.2.0.0"
    UPDATE_URL = "https://raw.githubusercontent.com/lancienanubis/vms/main/version.json"
    RECORDINGS_DIR, CONFIG_FILE, SETTINGS_FILE, THUMBNAILS_DIR, ARCHIVES_DIR, UPDATE_DIR, RESTART_SIGNAL_FILE = "recordings", "cameras.json", "settings.json", "thumbnails", "archives", "update", "restart_signal.txt"
    COOLDOWN_SECONDS, VIDEO_FPS, STABILIZATION_DELAY = 10, 15.0, 5

    camera_threads, thread_lock = {}, threading.Lock()
    for d in [RECORDINGS_DIR, THUMBNAILS_DIR, ARCHIVES_DIR, UPDATE_DIR]:
        os.makedirs(d, exist_ok=True)

    # ======================================================================
    # --- SECTION DES FONCTIONS UTILITAIRES ---
    # ======================================================================

    @app.context_processor
    def inject_global_vars():
        return dict(app_version=APP_VERSION)

    def sanitize_filename(name):
        sanitized_name = unidecode(name); return "".join(c if c.isalnum() else '_' for c in sanitized_name)

    def get_camera_paths(cam_name_safe, date_str=None):
        paths = { 'recordings_base': os.path.join(RECORDINGS_DIR, cam_name_safe), 'thumbnails_base': os.path.join(THUMBNAILS_DIR, cam_name_safe), 'archives_base': os.path.join(ARCHIVES_DIR, cam_name_safe) }
        if date_str:
            paths['recordings_date'] = os.path.join(paths['recordings_base'], date_str); paths['thumbnails_date'] = os.path.join(paths['thumbnails_base'], date_str); paths['archives_date'] = os.path.join(paths['archives_base'], date_str)
        return paths

    def create_thumbnail_for_video(video_filepath, thumb_filepath):
        try:
            cap = cv2.VideoCapture(video_filepath)
            if not cap.isOpened(): return False
            success, frame = cap.read(); cap.release()
            if success: os.makedirs(os.path.dirname(thumb_filepath), exist_ok=True); cv2.imwrite(thumb_filepath, frame); return True
        except Exception as e: print(f"[ERREUR_THUMBNAIL] Impossible de créer la miniature pour {video_filepath}: {e}")
        return False
    
    def _extract_camera_data_from_form(form_data):
        return { 'name': form_data['camera_name'], 'url_sd': form_data['camera_url_sd'], 'url_hd': form_data['camera_url_hd'], 'sensitivity': int(form_data.get('sensitivity', 1000)), 'is_active': 'is_active' in form_data, 'is_recording_enabled': 'is_recording_enabled' in form_data, 'show_detection': 'show_detection' in form_data, 'min_recording_time': int(form_data.get('min_recording_time', 15)), 'retention_days': int(form_data.get('retention_days', 0)) }

    def camera_required(f):
        @wraps(f)
        def decorated_function(cam_id, *args, **kwargs):
            camera_info = load_cameras_config().get(cam_id)
            if not camera_info: return jsonify({"error": "Camera non trouvee"}), 404
            kwargs['camera_info'] = camera_info; return f(cam_id, *args, **kwargs)
        return decorated_function

    # ======================================================================
    # --- GESTION DE LA CONFIGURATION ET MAINTENANCE ---
    # ======================================================================
    def save_settings(settings):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(settings, f, indent=4)
    def load_settings():
        try:
            if not os.path.exists(SETTINGS_FILE): raise FileNotFoundError
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            default_settings = {"purge_hour": 3}; save_settings(default_settings); return default_settings
    def load_cameras_config():
        try:
            if not os.path.exists(CONFIG_FILE): return {}
            with open(CONFIG_FILE,'r',encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, Exception) as e: print(f"!!! ERREUR LECTURE {CONFIG_FILE}: {e} !!!"); return {}
    def save_cameras_config(cameras):
        with open(CONFIG_FILE,'w',encoding='utf-8') as f: json.dump(cameras, f, indent=4)
    def purge_old_recordings():
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Lancement de la purge...")
        today = datetime.now().date()
        for cam_config in load_cameras_config().values():
            retention_days = int(cam_config.get("retention_days", 0))
            if retention_days <= 0: continue
            cam_name_safe = sanitize_filename(cam_config['name']); paths = get_camera_paths(cam_name_safe)
            for base_dir in [paths['recordings_base'], paths['thumbnails_base']]:
                if not os.path.isdir(base_dir): continue
                for date_folder in os.listdir(base_dir):
                    try:
                        folder_date = datetime.strptime(date_folder, '%Y-%m-%d').date()
                        if (today - folder_date).days >= retention_days:
                            folder_to_delete = os.path.join(base_dir, date_folder)
                            print(f"  -> Suppression: '{folder_to_delete}' (rétention: {retention_days}j)"); shutil.rmtree(folder_to_delete)
                    except (ValueError, OSError) as e: print(f"  -> Erreur sur dossier '{date_folder}': {e}")
        print("Purge terminée."); return "Purge terminée."
    def maintain_thumbnails():
        print("--- Début de la maintenance des miniatures ---"); count = 0
        for cam_config in load_cameras_config().values():
            cam_name_safe = sanitize_filename(cam_config['name']); cam_rec_path = get_camera_paths(cam_name_safe)['recordings_base']
            if not os.path.isdir(cam_rec_path): continue
            for date_folder in os.listdir(cam_rec_path):
                date_rec_path = os.path.join(cam_rec_path, date_folder)
                if not os.path.isdir(date_rec_path): continue
                for video_filename in os.listdir(date_rec_path):
                    if not video_filename.endswith('.mp4'): continue
                    thumb_folder_path = get_camera_paths(cam_name_safe, date_folder)['thumbnails_date']
                    thumb_filepath = os.path.join(thumb_folder_path, video_filename.replace('.mp4', '.jpg'))
                    if not os.path.exists(thumb_filepath):
                        video_filepath = os.path.join(date_rec_path, video_filename)
                        if create_thumbnail_for_video(video_filepath, thumb_filepath): count += 1; print(f"[MAINTENANCE] Miniature créée : {thumb_filepath}")
        result_message = f"Maintenance des miniatures terminée. {count} miniatures créées."; print(result_message); return result_message
    
    def maintenance_thread_worker():
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [MAINTENANCE] Le thread de purge automatique a démarré."); last_purge_date = None
        while True:
            time.sleep(600); now = datetime.now()
            if now.date() == last_purge_date: continue
            settings = load_settings(); purge_hour = int(settings.get("purge_hour", 3))
            if now.hour == purge_hour:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [MAINTENANCE] Heure de purge ({purge_hour}h) détectée. Lancement...")
                try: purge_old_recordings(); last_purge_date = now.date(); print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [MAINTENANCE] Purge terminée.")
                except Exception as e: print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [MAINTENANCE][ERREUR] La purge a échoué: {e}"); traceback.print_exc()

    # ======================================================================
    # --- CLASSE CAMERA & GESTION DES THREADS ---
    # ======================================================================
    class CameraThread(threading.Thread):
        def __init__(self, cam_id, cam_config):
            super().__init__(); self.cam_id, self.config, self.is_running = cam_id, cam_config, True
            self.latest_frame, self.is_recording, self.last_motion_time, self.video_writer = None, False, 0, None
            self.recording_enabled = self.config.get('is_recording_enabled', True); self.show_detection = self.config.get('show_detection', True)
            self.status, self.motion_detected_in_frame = "Initializing", False
            self.min_recording_time = int(self.config.get('min_recording_time', 15)); self.recording_start_time = 0
        def run(self):
            url, sensitivity = self.config['url_sd'], int(self.config.get('sensitivity', 1000))
            source = int(url) if url.isdigit() else url
            while self.is_running:
                self.status = "Connecting"; cap = cv2.VideoCapture(source)
                if not cap.isOpened(): self.status = "Connection Failed"; print(f"[{self.config['name']}] Echec connexion. Nouvelle tentative dans {COOLDOWN_SECONDS}s."); time.sleep(COOLDOWN_SECONDS); continue
                self.status = "Connected"; print(f"[{self.config['name']}] Connexion reussie.")
                bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=128, detectShadows=False); start_time = time.time()
                while self.is_running and cap.isOpened():
                    success, frame = cap.read()
                    if not success: self.status = "Stream Lost"; print(f"[{self.config['name']}] Flux perdu. Reconnexion..."); break
                    self.motion_detected_in_frame, detected_contours = False, []
                    if time.time() - start_time > STABILIZATION_DELAY:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY); gray = cv2.GaussianBlur(gray, (21, 21), 0)
                        mask = bg_subtractor.apply(gray); mask = cv2.threshold(mask, 25, 255, cv2.THRESH_BINARY)[1]; mask = cv2.dilate(mask, None, iterations=2)
                        contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        for c in contours:
                            if cv2.contourArea(c) > sensitivity: self.motion_detected_in_frame = True; detected_contours.append(c)
                    frame_for_display = frame.copy()
                    if self.recording_enabled and self.motion_detected_in_frame:
                        self.last_motion_time = time.time()
                        if not self.is_recording: self.start_recording(frame)
                    if self.is_recording and (time.time() - self.last_motion_time > COOLDOWN_SECONDS) and (time.time() - self.recording_start_time >= self.min_recording_time): self.stop_recording()
                    if self.show_detection and self.motion_detected_in_frame:
                        for c in detected_contours: (x, y, w, h) = cv2.boundingRect(c); cv2.rectangle(frame_for_display, (x, y), (x + w, y + h), (0, 0, 255), 2)
                        cv2.putText(frame_for_display, "MOUVEMENT", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    if self.is_recording:
                        cv2.putText(frame_for_display, "REC", (frame.shape[1] - 70, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
                        if self.video_writer and self.video_writer.isOpened(): self.video_writer.write(frame)
                    with thread_lock: self.latest_frame = frame_for_display
                cap.release(); self.stop_recording()
        def start_recording(self, first_frame):
            self.is_recording, self.recording_start_time = True, time.time(); now = datetime.now()
            cam_name_safe = sanitize_filename(self.config['name']); date_folder, time_str = now.strftime('%Y-%m-%d'), now.strftime('%H-%M-%S')
            paths = get_camera_paths(cam_name_safe, date_folder)
            os.makedirs(paths['recordings_date'], exist_ok=True); os.makedirs(paths['thumbnails_date'], exist_ok=True)
            video_filepath = os.path.join(paths['recordings_date'], f"{time_str}.mp4"); thumb_filepath = os.path.join(paths['thumbnails_date'], f"{time_str}.jpg")
            height, width, _ = first_frame.shape; self.video_writer = cv2.VideoWriter(video_filepath, cv2.VideoWriter_fourcc(*'avc1'), VIDEO_FPS, (width, height))
            if self.video_writer.isOpened(): print(f"[{self.config['name']}] Début de l'enregistrement : {video_filepath}"); cv2.imwrite(thumb_filepath, first_frame)
            else: print(f"[{self.config['name']}] Erreur initialisation enregistreur."); self.is_recording = False
        def stop_recording(self):
            if self.is_recording: self.is_recording = False; time.sleep(0.1);
            if self.video_writer is not None: self.video_writer.release(); self.video_writer = None; print(f"[{self.config['name']}] Fin de l'enregistrement.")
        def stop(self): self.is_running = False; self.stop_recording()
    def sync_camera_threads():
        print("[SYNC] Synchronisation des caméras..."); config = load_cameras_config()
        with thread_lock:
            running_ids = set(camera_threads.keys()); config_ids = {cid for cid, cconf in config.items() if cconf.get('is_active', False)}
            ids_to_stop = running_ids - config_ids; ids_to_start = config_ids - running_ids
            ids_to_restart = {cid for cid in running_ids.intersection(config_ids) if camera_threads[cid].config != config[cid]}
            for cam_id in ids_to_stop.union(ids_to_restart):
                if cam_id in camera_threads: print(f"[SYNC] Arrêt de: {camera_threads[cam_id].config.get('name', cam_id)}"); camera_threads[cam_id].stop(); camera_threads[cam_id].join(timeout=2.0); camera_threads.pop(cam_id, None)
            for cam_id in ids_to_start.union(ids_to_restart):
                cam_config = config[cam_id]; print(f"[SYNC] Démarrage de: {cam_config.get('name', cam_id)}"); thread = CameraThread(cam_id, cam_config); thread.start(); camera_threads[cam_id] = thread
        print(f"[SYNC] Synchronisation terminée. {len(camera_threads)} thread(s) actif(s).")
    def generate_frames(cam_id, quality):
        if quality == 'sd':
            thread = camera_threads.get(cam_id)
            if not thread: return
            while True:
                with thread_lock: frame = thread.latest_frame
                if frame is None: time.sleep(0.1); continue
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if _: yield (b'--frame\r\n'b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'); time.sleep(1 / VIDEO_FPS)
        elif quality == 'hd':
            cam_config = load_cameras_config().get(cam_id)
            if not cam_config or not cam_config.get('url_hd'): return
            url = cam_config['url_hd']; source = int(url) if url.isdigit() else url; cap = cv2.VideoCapture(source)
            if not cap.isOpened(): return
            while True:
                success, frame = cap.read()
                if not success: break
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if _: yield (b'--frame\r\n'b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            cap.release()

    # ======================================================================
    # --- ROUTES FLASK ---
    # ======================================================================
    @app.route('/')
    def index():
        active_cameras = {k: v for k, v in load_cameras_config().items() if v.get('is_active', False)}
        return render_template('index.html', cameras=active_cameras)

    @app.route('/config')
    def config():
        def get_dir_size(path):
            try:
                if not os.path.isdir(path): return "0 B"
                total = sum(os.path.getsize(os.path.join(dirpath, f)) for dirpath, _, filenames in os.walk(path) for f in filenames if not os.path.islink(os.path.join(dirpath, f)))
                if total == 0: return "0 B"
                size_name = ("B", "Ko", "Mo", "Go", "To"); i = int(math.floor(math.log(total, 1024))) if total > 0 else 0
                return f"{round(total / math.pow(1024, i), 2)} {size_name[i]}"
            except OSError: return "N/A"
        cameras = load_cameras_config()
        for cam_config in cameras.values():
            safe_name = sanitize_filename(cam_config.get('name', ''))
            paths = get_camera_paths(safe_name)
            cam_config['recordings_usage'] = get_dir_size(paths['recordings_base'])
            cam_config['archives_usage'] = get_dir_size(paths['archives_base'])
        return render_template('config.html', cameras=cameras, settings=load_settings())

    @app.route('/add_camera_form')
    def add_camera_form(): return render_template('add_camera.html')

    @app.route('/add_camera', methods=['POST'])
    def add_camera():
        cameras = load_cameras_config(); cameras[str(uuid.uuid4())] = _extract_camera_data_from_form(request.form)
        save_cameras_config(cameras); sync_camera_threads(); return redirect(url_for('config'))

    @app.route('/update/<cam_id>', methods=['POST'])
    def update_camera(cam_id):
        cameras = load_cameras_config()
        if cam_id in cameras:
            cameras[cam_id].update(_extract_camera_data_from_form(request.form))
            save_cameras_config(cameras); sync_camera_threads()
        return redirect(url_for('config'))
    
    @app.route('/update_settings', methods=['POST'])
    def update_settings():
        settings = load_settings(); settings['purge_hour'] = int(request.form.get('purge_hour', 3))
        save_settings(settings); return redirect(url_for('config'))
    
    @app.route('/delete_camera', methods=['POST'])
    def delete_camera():
        cameras = load_cameras_config(); cam_id = request.form['cam_id']
        if cam_id in cameras:
            cam_name_safe = sanitize_filename(cameras[cam_id]['name']); paths = get_camera_paths(cam_name_safe)
            shutil.rmtree(paths['recordings_base'], ignore_errors=True); shutil.rmtree(paths['thumbnails_base'], ignore_errors=True); shutil.rmtree(paths['archives_base'], ignore_errors=True)
            del cameras[cam_id]; save_cameras_config(cameras); sync_camera_threads()
        return redirect(url_for('config'))

    @app.route('/edit/<cam_id>')
    @camera_required
    def edit_camera(cam_id, camera_info): return render_template('edit_camera.html', camera=camera_info, cam_id=cam_id)
    
    @app.route('/playback/<cam_id>')
    @camera_required
    def playback_page(cam_id, camera_info):
        camera_info['safe_name'] = sanitize_filename(camera_info['name'])
        return render_template('playback.html', camera_info=camera_info, cam_id=cam_id, today=datetime.now().strftime('%Y-%m-%d'))
    
    @app.route('/fullscreen/<cam_id>')
    @camera_required
    def fullscreen(cam_id, camera_info): return render_template('fullscreen.html', cam_id=cam_id, camera_info=camera_info)
    
    @app.route('/recordings/<cam_id>')
    @camera_required
    def recordings_page(cam_id, camera_info):
        camera_info['safe_name'] = sanitize_filename(camera_info['name'])
        today = datetime.now().strftime('%Y-%m-%d')
        return render_template('recordings.html', camera_info=camera_info, cam_id=cam_id, today=today)

    @app.route('/archives/<cam_id>')
    @camera_required
    def archives_page(cam_id, camera_info):
        safe_cam_name = sanitize_filename(camera_info['name']); cam_path = get_camera_paths(safe_cam_name)['archives_base']
        dates_structure = []
        if os.path.isdir(cam_path):
            for date_folder in sorted(os.listdir(cam_path), reverse=True):
                date_path = os.path.join(cam_path, date_folder)
                if not os.path.isdir(date_path): continue
                date_data = {'date': date_folder, 'files': []}
                for filename in sorted(os.listdir(date_path)):
                    if filename.endswith('.mp4'):
                        comment = ""
                        meta_path = os.path.join(date_path, filename.replace('.mp4', '.meta.json'))
                        if os.path.exists(meta_path):
                            try:
                                with open(meta_path, 'r', encoding='utf-8') as f: comment = json.load(f).get('comment', '')
                            except (IOError, json.JSONDecodeError): comment = "Erreur lecture"
                        date_data['files'].append({ 'filename': filename, 'thumb_filename': filename.replace('.mp4', '.jpg'), 'time': filename.replace('.mp4', '').replace('-', ':'), 'comment': comment })
                if date_data['files']: dates_structure.append(date_data)
        return render_template('archives.html', camera_info=camera_info, safe_cam_name=safe_cam_name, dates=dates_structure)

    @app.route('/maintenance')
    def maintenance_page(): return render_template('maintenance.html')
    @app.route('/maintenance/purge', methods=['POST'])
    def manual_purge(): return jsonify({"status": "success", "message": purge_old_recordings()})
    @app.route('/maintenance/thumbnails', methods=['POST'])
    def manual_thumbnails(): return jsonify({"status": "success", "message": maintain_thumbnails()})
    
    @app.route('/maintenance/restart', methods=['POST'])
    def manual_restart():
        print("[RESTART] Demande de redémarrage manuel reçue.")
        try:
            with open(RESTART_SIGNAL_FILE, 'w') as f:
                f.write(f"Restart triggered at {datetime.now()}")
            print("[RESTART] Fichier signal de redémarrage créé.")
            def shutdown_server():
                time.sleep(1)
                print("[RESTART] Arrêt du serveur pour redémarrage...")
                os._exit(0)
            threading.Thread(target=shutdown_server).start()
            return jsonify({"status": "success", "message": "Signal de redémarrage envoyé. Le serveur va s'arrêter et redémarrer."})
        except Exception as e:
            print(f"[RESTART] Erreur critique lors de la tentative de redémarrage: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route('/update_page')
    def update_page():
        update_info = { "current_version": APP_VERSION, "update_available": False }
        try:
            response = requests.get(UPDATE_URL, timeout=5); response.raise_for_status()
            latest_version_info = response.json(); latest_version = latest_version_info.get("version")
            current_v = tuple(map(int, (APP_VERSION.split('.')))); latest_v = tuple(map(int, (latest_version.split('.'))))
            if latest_v > current_v:
                update_info.update({ "update_available": True, "latest_version": latest_version, "notes": latest_version_info.get("notes", "Pas de notes de version.") })
            else: update_info["notes"] = "Votre application est à jour."
        except Exception as e: update_info["notes"] = f"Impossible de vérifier les mises à jour. Erreur : {e}"
        return render_template('update.html', update_info=update_info)

    # --- API et routes de service ---
    @app.route('/api/status')
    def api_status():
        with thread_lock: statuses = {cid: {"id": cid, "name": th.config.get('name', 'N/A'), "status": th.status, "is_recording": th.is_recording, "motion_detected": th.motion_detected_in_frame} for cid, th in camera_threads.items()}
        return jsonify(statuses)
    @app.route('/api/check_update')
    def check_update():
        try:
            response = requests.get(UPDATE_URL, timeout=5); response.raise_for_status()
            latest_version_info = response.json(); latest_version = latest_version_info.get("version")
            if latest_version and tuple(map(int, (latest_version.split('.')))) > tuple(map(int, (APP_VERSION.split('.')))): return jsonify({ "update_available": True, "latest_version": latest_version})
            else: return jsonify({"update_available": False})
        except Exception: return jsonify({"update_available": False, "error": "network_error"})
    @app.route('/api/initiate_update', methods=['POST'])
    def initiate_update():
        print("[UPDATE] Demande de mise à jour reçue. Préparation de l'arrêt.")
        try:
            response = requests.get(UPDATE_URL, timeout=5); response.raise_for_status()
            download_url = response.json().get("download_url")
            if not download_url: return jsonify({'status': 'error', 'message': 'URL de mise à jour introuvable.'}), 500
            update_signal_file = os.path.join(persistent_data_path, "update_signal.txt")
            with open(update_signal_file, "w") as f: f.write(download_url)
            print("[UPDATE] Fichier signal créé.")
            def force_shutdown(): time.sleep(1); print("[UPDATE] Exécution de l'arrêt forcé (os._exit)."); os._exit(0)
            threading.Thread(target=force_shutdown).start()
            return jsonify({'status': 'success', 'message': 'Signal de mise à jour envoyé. Le serveur va s\'arrêter.'})
        except Exception as e: print(f"[UPDATE] Erreur lors de l'initialisation de la mise à jour: {e}"); return jsonify({'status': 'error', 'message': str(e)}), 500
    @app.route('/api/recordings_by_hour/<cam_id>/<date>')
    @camera_required
    def api_recordings_by_hour(cam_id, date, camera_info):
        safe_name = sanitize_filename(camera_info['name']); date_folder_path = get_camera_paths(safe_name, date)['recordings_date']
        hourly_summary = {}
        if os.path.isdir(date_folder_path):
            for filename in sorted(os.listdir(date_folder_path)):
                if filename.endswith('.mp4'):
                    hour = filename.split('-')[0]
                    if hour not in hourly_summary: hourly_summary[hour] = {"count": 0, "thumb": filename.replace('.mp4', '.jpg')}
                    hourly_summary[hour]["count"] += 1
        return jsonify(hourly_summary)
    @app.route('/api/events_for_hour/<cam_id>/<date>/<hour>')
    @camera_required
    def api_events_for_hour(cam_id, date, hour, camera_info):
        safe_name = sanitize_filename(camera_info['name']); date_folder_path = get_camera_paths(safe_name, date)['recordings_date']
        events = []
        if os.path.isdir(date_folder_path):
            for filename in sorted(os.listdir(date_folder_path)):
                if filename.startswith(hour) and filename.endswith('.mp4'): events.append({"time": filename.replace('.mp4', '').replace('-', ':'), "filename": filename, "thumb": filename.replace('.mp4', '.jpg')})
        return jsonify(events)
    @app.route('/api/timeline/<cam_id>/<date>')
    @camera_required
    def api_timeline(cam_id, date, camera_info):
        safe_name = sanitize_filename(camera_info.get('name', '')); date_folder_path = get_camera_paths(safe_name, date)['recordings_date']
        recordings = []
        if os.path.isdir(date_folder_path):
            for filename in sorted(os.listdir(date_folder_path)):
                if filename.endswith('.mp4'):
                    filepath = os.path.join(date_folder_path, filename)
                    try:
                        cap = cv2.VideoCapture(filepath)
                        if not cap.isOpened(): cap.release(); continue
                        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps = cap.get(cv2.CAP_PROP_FPS); cap.release()
                        if fps > 0 and frame_count > 0: duration = frame_count / fps; recordings.append({"start_time": filename.replace('.mp4', '').replace('-', ':'), "duration": round(duration), "filename": filename})
                    except Exception as e: print(f"Erreur lecture metadata {filepath}: {e}"); continue
        return jsonify(recordings)
    @app.route('/api/available_dates/<cam_id>')
    @camera_required
    def api_available_dates(cam_id, camera_info):
        safe_camera_name = sanitize_filename(camera_info['name']); recordings_cam_dir = get_camera_paths(safe_camera_name)['recordings_base']
        available_dates = []
        if os.path.isdir(recordings_cam_dir):
            for date_folder in os.listdir(recordings_cam_dir):
                full_path = os.path.join(recordings_cam_dir, date_folder)
                if os.path.isdir(full_path) and len(os.listdir(full_path)) > 0: available_dates.append(date_folder)
        return jsonify(available_dates)
    @app.route('/video_feed/<quality>/<cam_id>')
    def video_feed(quality, cam_id): return Response(generate_frames(cam_id, quality), mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # ======================================================================
    # --- ROUTES CORRIGÉES POUR SERVIR LES FICHIERS ---
    # ======================================================================
    @app.route('/thumbnail/<camera_name>/<date>/<thumb_filename>')
    def serve_thumbnail(camera_name, date, thumb_filename):
        path_info = get_camera_paths(sanitize_filename(camera_name), date)
        return send_from_directory(os.path.abspath(path_info['thumbnails_date']), thumb_filename)

    @app.route('/archives/thumbnail/<camera_name>/<date>/<thumb_filename>')
    def serve_archive_thumbnail(camera_name, date, thumb_filename):
        path_info = get_camera_paths(sanitize_filename(camera_name), date)
        return send_from_directory(os.path.abspath(path_info['archives_date']), thumb_filename)

    @app.route('/archives/play/<camera_name>/<date>/<filename>')
    def play_archive_video(camera_name, date, filename):
        path_info = get_camera_paths(sanitize_filename(camera_name), date)
        return send_from_directory(os.path.abspath(path_info['archives_date']), filename)

    @app.route('/play/<camera_name>/<date>/<filename>')
    def play_video(camera_name, date, filename):
        path_info = get_camera_paths(sanitize_filename(camera_name), date)
        return send_from_directory(os.path.abspath(path_info['recordings_date']), filename)

    @app.route('/poster/<cam_id>')
    def poster(cam_id):
        thread = camera_threads.get(cam_id)
        if thread and thread.latest_frame is not None:
            with thread_lock: frame = thread.latest_frame
            _, buffer = cv2.imencode('.jpg', frame); return Response(buffer.tobytes(), mimetype='image/jpeg')
        return "", 204

    # ======================================================================
    # --- DÉMARRAGE DE L'APPLICATION ---
    # ======================================================================
    if __name__ == '__main__':
        maintenance_thread = threading.Thread(target=maintenance_thread_worker, daemon=True)
        maintenance_thread.start()
        sync_camera_threads()
        print(f"\n--- Lancement du serveur VMS (Version {APP_VERSION}) ---")
        print(f"--- Accédez à l'interface via http://127.0.0.1:5200 ---")
        app.run(host='0.0.0.0', port=5200, debug=True, threaded=True, use_reloader=False)

except Exception as e:
    print(f"\n\n!!! ERREUR FATALE AU DEMARRAGE: {e} !!!\n\n"); traceback.print_exc()
    time.sleep(15)