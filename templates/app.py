# app.py (Votre code, pointant sur index.html)
try:
    from flask import Flask, render_template, Response, request, redirect, url_for, send_from_directory, jsonify
    import cv2, json, os, uuid, numpy as np, traceback, threading, time
    from datetime import datetime
    from unidecode import unidecode
    import shutil

    # --- CONSTANTES ---
    RECORDINGS_DIR, CONFIG_FILE, THUMBNAILS_DIR = "recordings", "cameras.json", "thumbnails"
    COOLDOWN_SECONDS, VIDEO_FPS, STABILIZATION_DELAY = 10, 15.0, 5

    app = Flask(__name__)
    camera_threads, thread_lock = {}, threading.Lock()
    if not os.path.exists(RECORDINGS_DIR): os.makedirs(RECORDINGS_DIR)
    if not os.path.exists(THUMBNAILS_DIR): os.makedirs(THUMBNAILS_DIR)

    def sanitize_filename(name):
        sanitized_name = unidecode(name)
        return "".join(c if c.isalnum() else '_' for c in sanitized_name)

    # --- CLASSE CameraThread ---
    class CameraThread(threading.Thread):
        def __init__(self, cam_id, cam_config):
            super().__init__()
            self.cam_id, self.config, self.is_running = cam_id, cam_config, True
            self.latest_frame, self.is_recording, self.last_motion_time, self.video_writer = None, False, 0, None
            self.recording_enabled = self.config.get('is_recording_enabled', True)
            self.show_detection = self.config.get('show_detection', True)
            self.status = "Initializing" # Pour les statuts en temps réel
            self.motion_detected_in_frame = False # Pour les statuts en temps réel
        def run(self):
            url, sensitivity = self.config['url_sd'], int(self.config.get('sensitivity', 1000))
            source = int(url) if url.isdigit() else url
            while self.is_running:
                self.status = "Connecting" # Pour les statuts en temps réel
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    self.status = "Connection Failed" # Pour les statuts en temps réel
                    print(f"[{self.config['name']}] Echec connexion. Nouvelle tentative dans {COOLDOWN_SECONDS}s.")
                    time.sleep(COOLDOWN_SECONDS)
                    continue
                self.status = "Connected" # Pour les statuts en temps réel
                print(f"[{self.config['name']}] Connexion reussie.")
                bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=128, detectShadows=False)
                start_time = time.time()
                while self.is_running and cap.isOpened():
                    success, frame = cap.read()
                    if not success: self.status = "Stream Lost"; print(f"[{self.config['name']}] Flux perdu. Reconnexion..."); break
                    self.motion_detected_in_frame = False # Pour les statuts en temps réel
                    detected_contours = []
                    if time.time() - start_time > STABILIZATION_DELAY:
                        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        gray_frame = cv2.GaussianBlur(gray_frame, (21, 21), 0)
                        motion_mask = bg_subtractor.apply(gray_frame)
                        motion_mask = cv2.threshold(motion_mask, 25, 255, cv2.THRESH_BINARY)[1]
                        motion_mask = cv2.dilate(motion_mask, None, iterations=2)
                        contours, _ = cv2.findContours(motion_mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        for c in contours:
                            if cv2.contourArea(c) > sensitivity: self.motion_detected_in_frame = True; detected_contours.append(c)
                    frame_for_display = frame.copy()
                    if self.recording_enabled and self.motion_detected_in_frame:
                        self.last_motion_time = time.time()
                        if not self.is_recording: self.start_recording(frame)
                    if self.is_recording and (time.time() - self.last_motion_time > COOLDOWN_SECONDS): self.stop_recording()
                    if self.show_detection and self.motion_detected_in_frame:
                        for c in detected_contours: (x, y, w, h) = cv2.boundingRect(c); cv2.rectangle(frame_for_display, (x, y), (x + w, y + h), (0, 0, 255), 2)
                        cv2.putText(frame_for_display, "MOUVEMENT DETECTE", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    if self.is_recording:
                        cv2.putText(frame_for_display, "REC", (frame.shape[1] - 70, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
                        if self.video_writer and self.video_writer.isOpened(): self.video_writer.write(frame)
                    with thread_lock: self.latest_frame = frame_for_display
                cap.release()
                self.stop_recording()
        def start_recording(self, first_frame):
            self.is_recording = True; now = datetime.now()
            camera_name_safe = sanitize_filename(self.config['name'])
            date_folder = now.strftime('%Y-%m-%d'); time_str = now.strftime('%H-%M-%S')
            video_filename = f"{time_str}.mp4"; thumb_filename = f"{time_str}.jpg"
            video_folder_path = os.path.join(RECORDINGS_DIR, camera_name_safe, date_folder)
            thumb_folder_path = os.path.join(THUMBNAILS_DIR, camera_name_safe, date_folder)
            os.makedirs(video_folder_path, exist_ok=True); os.makedirs(thumb_folder_path, exist_ok=True)
            video_filepath = os.path.join(video_folder_path, video_filename)
            thumb_filepath = os.path.join(thumb_folder_path, thumb_filename)
            height, width, _ = first_frame.shape; fourcc = cv2.VideoWriter_fourcc(*'avc1')
            self.video_writer = cv2.VideoWriter(video_filepath, fourcc, VIDEO_FPS, (width, height))
            if self.video_writer.isOpened(): print(f"[{self.config['name']}] Début de l'enregistrement : {video_filepath}"); cv2.imwrite(thumb_filepath, first_frame)
            else: print(f"[{self.config['name']}] Erreur initialisation enregistreur."); self.is_recording = False
        def stop_recording(self):
            if self.is_recording:
                self.is_recording = False; time.sleep(0.1)
                if self.video_writer is not None: self.video_writer.release(); self.video_writer = None; print(f"[{self.config['name']}] Fin de l'enregistrement.")
        def stop(self): self.is_running = False; self.stop_recording()

    # --- FONCTIONS UTILITAIRES ET DE SYNCHRONISATION ---
    def load_cameras_config():
        if not os.path.exists(CONFIG_FILE): return {}
        try:
            with open(CONFIG_FILE,'r',encoding='utf-8') as f: return json.load(f)
        except json.JSONDecodeError as e: print(f"!!! ERREUR SYNTAXE {CONFIG_FILE}: {e} !!!"); return {}
        except Exception as e: print(f"!!! ERREUR LECTURE {CONFIG_FILE}: {e} !!!"); return {}
    def save_cameras_config(cameras):
        with open(CONFIG_FILE,'w',encoding='utf-8') as f: json.dump(cameras,f,indent=4)
    def maintain_thumbnails():
        print("--- Début de la maintenance des miniatures ---")
        if not os.path.isdir(RECORDINGS_DIR): return
        for cam_config in load_cameras_config().values():
            cam_name_safe = sanitize_filename(cam_config['name'])
            cam_rec_path = os.path.join(RECORDINGS_DIR, cam_name_safe)
            if not os.path.isdir(cam_rec_path): continue
            for date_folder in os.listdir(cam_rec_path):
                date_rec_path = os.path.join(cam_rec_path, date_folder)
                if not os.path.isdir(date_rec_path): continue
                for video_filename in os.listdir(date_rec_path):
                    if not video_filename.endswith('.mp4'): continue
                    thumb_filename = video_filename.replace('.mp4', '.jpg')
                    thumb_folder_path = os.path.join(THUMBNAILS_DIR, cam_name_safe, date_folder)
                    thumb_filepath = os.path.join(thumb_folder_path, thumb_filename)
                    if not os.path.exists(thumb_filepath):
                        video_filepath = os.path.join(date_rec_path, video_filename)
                        try:
                            cap = cv2.VideoCapture(video_filepath)
                            if cap.isOpened():
                                success, frame = cap.read()
                                if success: os.makedirs(thumb_folder_path, exist_ok=True); cv2.imwrite(thumb_filepath, frame)
                                cap.release()
                                print(f"[MAINTENANCE] Miniature créée : {thumb_filepath}")
                        except Exception as e: print(f"[MAINTENANCE][ERREUR] Impossible de créer la miniature pour {video_filepath}: {e}")
        print("--- Fin de la maintenance des miniatures ---")
    def sync_camera_threads():
        print("[SYNC] Synchronisation des caméras...")
        config = load_cameras_config()
        with thread_lock:
            running_ids = set(camera_threads.keys()); config_ids = set(config.keys())
            ids_to_stop, ids_to_start, ids_to_restart = set(), set(), set()
            for cam_id in running_ids:
                if cam_id not in config_ids or not config.get(cam_id, {}).get('is_active', False): ids_to_stop.add(cam_id)
            for cam_id, cam_config in config.items():
                if not cam_config.get('is_active', False): continue
                if cam_id not in running_ids: ids_to_start.add(cam_id)
                else:
                    if camera_threads[cam_id].config != cam_config: ids_to_restart.add(cam_id)
            for cam_id in ids_to_stop.union(ids_to_restart):
                if cam_id in camera_threads:
                    print(f"[SYNC] Arrêt de: {camera_threads[cam_id].config.get('name', cam_id)}")
                    camera_threads[cam_id].stop(); camera_threads[cam_id].join(timeout=1.0); camera_threads.pop(cam_id)
            for cam_id in ids_to_start.union(ids_to_restart):
                cam_config = config[cam_id]
                print(f"[SYNC] Démarrage de: {cam_config.get('name', cam_id)}")
                thread = CameraThread(cam_id, cam_config); thread.start(); camera_threads[cam_id] = thread
        print(f"[SYNC] Synchronisation terminée. {len(camera_threads)} thread(s) actif(s).")
    
    def generate_frames(cam_id, quality):
        if quality == 'sd':
            thread = camera_threads.get(cam_id)
            if not thread: return
            while True:
                with thread_lock: frame = thread.latest_frame
                if frame is None: time.sleep(0.1); continue
                ret, buffer = cv2.imencode('.jpg', frame);
                if not ret: continue
                yield (b'--frame\r\n'b'Content-Type: image/jpeg\r\r\n' + buffer.tobytes() + b'\r\n'); time.sleep(1/VIDEO_FPS)
        elif quality == 'hd':
            cam_config = load_cameras_config().get(cam_id)
            if not cam_config or not cam_config.get('url_hd'): return
            url = cam_config['url_hd']; source = int(url) if url.isdigit() else url; cap = cv2.VideoCapture(source)
            if not cap.isOpened(): return
            while True:
                success, frame = cap.read()
                if not success: break
                ret, buffer = cv2.imencode('.jpg', frame);
                if ret: yield (b'--frame\r\n'b'Content-Type: image/jpeg\r\r\n' + buffer.tobytes() + b'\r\n')
            cap.release()

    # --- ROUTES ---
    @app.route('/')
    def index():
        # MODIFICATION : Rendu de VOTRE index.html
        return render_template('index.html', cameras={k: v for k, v in load_cameras_config().items() if v.get('is_active', False)})

    # Route pour afficher le formulaire d'ajout de caméra (existante)
    @app.route('/add_camera_form')
    def add_camera_form():
        return render_template('add_camera.html')

    @app.route('/add_camera', methods=['POST'])
    def add_camera():
        cameras = load_cameras_config(); cameras[str(uuid.uuid4())] = {'name': request.form['camera_name'], 'url_sd': request.form['camera_url_sd'], 'url_hd': request.form['camera_url_hd'], 'sensitivity': int(request.form.get('sensitivity', 1000)), 'is_active': 'is_active' in request.form, 'is_recording_enabled': 'is_recording_enabled' in request.form, 'show_detection': 'show_detection' in request.form}; 
        save_cameras_config(cameras); 
        sync_camera_threads(); 
        return redirect(url_for('config'))

    @app.route('/update/<cam_id>', methods=['POST'])
    def update_camera(cam_id):
        cameras = load_cameras_config()
        if cam_id in cameras:
            cameras[cam_id]['name'] = request.form['camera_name']; cameras[cam_id]['url_sd'] = request.form['camera_url_sd']; cameras[cam_id]['url_hd'] = request.form['camera_url_hd']; cameras[cam_id]['sensitivity'] = int(request.form.get('sensitivity', 1000)); cameras[cam_id]['is_active'] = 'is_active' in request.form; cameras[cam_id]['is_recording_enabled'] = 'is_recording_enabled' in request.form; cameras[cam_id]['show_detection'] = 'show_detection' in request.form
        save_cameras_config(cameras); 
        sync_camera_threads(); 
        return redirect(url_for('config'))

    @app.route('/config')
    def config(): return render_template('config.html', cameras=load_cameras_config())
    
    @app.route('/edit/<cam_id>')
    def edit_camera(cam_id):
        camera_to_edit = load_cameras_config().get(cam_id);
        return render_template('edit_camera.html', camera=camera_to_edit, cam_id=cam_id) if camera_to_edit else ("Camera non trouvee", 404)

    @app.route('/delete_camera', methods=['POST'])
    def delete_camera():
        cameras, cam_id = load_cameras_config(), request.form['cam_id'];
        if cam_id in cameras:
            cam_name_safe = sanitize_filename(cameras[cam_id]['name'])
            shutil.rmtree(os.path.join(RECORDINGS_DIR, cam_name_safe), ignore_errors=True)
            shutil.rmtree(os.path.join(THUMBNAILS_DIR, cam_name_safe), ignore_errors=True)
            del cameras[cam_id]; 
            save_cameras_config(cameras); 
            sync_camera_threads()
        return redirect(url_for('config'))
    
    # Nouvelle route pour l'API de statut (Phase 2)
    @app.route('/api/status')
    def api_status():
        statuses = {};
        with thread_lock:
            for cam_id, thread in camera_threads.items():
                statuses[cam_id] = {"id": cam_id, "name": thread.config.get('name', 'N/A'), "status": thread.status, "is_recording": thread.is_recording, "motion_detected": thread.motion_detected_in_frame}
        return jsonify(statuses)
    
    @app.route('/fullscreen/<cam_id>')
    def fullscreen(cam_id): return render_template('fullscreen.html', cam_id=cam_id, camera_info=load_cameras_config().get(cam_id))
    @app.route('/playback/<cam_id>')
    def playback_page(cam_id):
        camera_info = load_cameras_config().get(cam_id);
        if not camera_info: return "Camera non trouvee", 404
        camera_info['safe_name'] = sanitize_filename(camera_info['name'])
        today = datetime.now().strftime('%Y-%m-%d'); return render_template('playback.html', camera_info=camera_info, cam_id=cam_id, today=today)
    @app.route('/recordings/<cam_id>')
    def recordings_page(cam_id):
        camera_info = load_cameras_config().get(cam_id)
        if not camera_info: return "Camera non trouvee", 404
        camera_info['safe_name'] = sanitize_filename(camera_info['name'])
        today = datetime.now().strftime('%Y-%m-%d');
        return render_template('recordings.html', camera_info=camera_info, cam_id=cam_id, today=today)
    @app.route('/api/recordings_by_hour/<cam_id>/<date>')
    def api_recordings_by_hour(cam_id, date):
        camera_info = load_cameras_config().get(cam_id)
        if not camera_info: return jsonify({"error": "Camera non trouvee"}), 404
        camera_name_safe = sanitize_filename(camera_info.get('name', ''))
        date_folder_path = os.path.join(RECORDINGS_DIR, camera_name_safe, date)
        hourly_summary = {}
        if os.path.isdir(date_folder_path):
            for filename in sorted(os.listdir(date_folder_path)):
                if filename.endswith('.mp4'):
                    hour = filename.split('-')[0]
                    if hour not in hourly_summary:
                        first_thumb = filename.replace('.mp4', '.jpg')
                        hourly_summary[hour] = {"count": 0, "thumb": first_thumb}
                    hourly_summary[hour]["count"] += 1
        return jsonify(hourly_summary)
    @app.route('/api/events_for_hour/<cam_id>/<date>/<hour>')
    def api_events_for_hour(cam_id, date, hour):
        camera_info = load_cameras_config().get(cam_id)
        if not camera_info: return jsonify({"error": "Camera non trouvee"}), 404
        camera_name_safe = sanitize_filename(camera_info.get('name', ''))
        date_folder_path = os.path.join(RECORDINGS_DIR, camera_name_safe, date)
        events = []
        if os.path.isdir(date_folder_path):
            for filename in sorted(os.listdir(date_folder_path)):
                if filename.startswith(hour) and filename.endswith('.mp4'):
                    thumb_filename = filename.replace('.mp4', '.jpg')
                    events.append({"time": filename.replace('.mp4', '').replace('-', ':'), "filename": filename, "thumb": thumb_filename})
        return jsonify(events)
    @app.route('/api/timeline/<cam_id>/<date>')
    def api_timeline(cam_id, date):
        camera_info = load_cameras_config().get(cam_id)
        if not camera_info: return jsonify({"error": "Camera non trouvee"}), 404
        camera_name_safe = sanitize_filename(camera_info.get('name', ''))
        date_folder_path = os.path.join(RECORDINGS_DIR, camera_name_safe, date)
        recordings = []
        if os.path.isdir(date_folder_path):
            for filename in sorted(os.listdir(date_folder_path)):
                if filename.endswith('.mp4'):
                    filepath = os.path.join(date_folder_path, filename)
                    try:
                        cap = cv2.VideoCapture(filepath)
                        if not cap.isOpened(): cap.release(); continue
                        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps = cap.get(cv2.CAP_PROP_FPS); cap.release()
                        if fps > 0 and frame_count > 0:
                            duration = frame_count / fps
                            recordings.append({"start_time": filename.replace('.mp4', '').replace('-', ':'), "duration": round(duration), "filename": filename})
                    except Exception as e: print(f"Erreur lecture metadata {filepath}: {e}"); continue
        return jsonify(recordings)
    @app.route('/thumbnail/<camera_name>/<date>/<thumb_filename>')
    def serve_thumbnail(camera_name, date, thumb_filename):
        thumb_path = os.path.join(THUMBNAILS_DIR, sanitize_filename(camera_name), date)
        return send_from_directory(thumb_path, thumb_filename) if os.path.exists(os.path.join(thumb_path, thumb_filename)) else ("", 404)
    @app.route('/play/<camera_name>/<date>/<filename>')
    def play_video(camera_name, date, filename):
        video_path = os.path.join(RECORDINGS_DIR, sanitize_filename(camera_name), date)
        return send_from_directory(video_path, filename)
    @app.route('/poster/<cam_id>')
    def poster(cam_id):
        thread = camera_threads.get(cam_id);
        if thread:
            timeout = time.time() + 2
            while time.time() < timeout:
                with thread_lock: frame = thread.latest_frame
                if frame is not None: ret, buffer = cv2.imencode('.jpg', frame);
                if ret: return Response(buffer.tobytes(), mimetype='image/jpeg')
                time.sleep(0.1)
        return "", 204
    @app.route('/video_feed/<quality>/<cam_id>')
    def video_feed(quality, cam_id): return Response(generate_frames(cam_id, quality), mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # --- DÉMARRAGE DE L'APPLICATION ---
    if __name__ == '__main__':
        maintain_thumbnails()
        sync_camera_threads()
        print("\n--- Lancement du serveur VMS (Phase 2, Ajout Caméra sur Page Dédicacée) ---")
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True) # Mettez debug=True pour le développement
                                                                      # N'oubliez pas de le remettre à False pour la production
except Exception as e:
    print(f"\n\n!!! ERREUR FATALE AU DEMARRAGE: {e} !!!\n\n"); traceback.print_exc();
    input("Le programme a plante. Appuyez sur Entree pour quitter...")