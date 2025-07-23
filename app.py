# app.py (Version corrigée pour l'archivage des miniatures)

try:
    from flask import Flask, render_template, Response, request, redirect, url_for, send_from_directory, jsonify
    import cv2, json, os, uuid, numpy as np, traceback, threading, time, sys, math, requests
    from datetime import datetime
    from unidecode import unidecode
    import shutil

    # --- CONSTANTES ---
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))

    APP_VERSION = "1.1.1.0"
    UPDATE_URL = "https://raw.githubusercontent.com/lancienanubis/vms/main/version.json"
    
    RECORDINGS_DIR = os.path.join(application_path, "recordings")
    CONFIG_FILE = os.path.join(application_path, "cameras.json")
    THUMBNAILS_DIR = os.path.join(application_path, "thumbnails")
    ARCHIVES_DIR = os.path.join(application_path, "archives")
    
    COOLDOWN_SECONDS, VIDEO_FPS, STABILIZATION_DELAY = 10, 15.0, 5

    app = Flask(__name__)
    camera_threads, thread_lock = {}, threading.Lock()
    if not os.path.exists(RECORDINGS_DIR): os.makedirs(RECORDINGS_DIR)
    if not os.path.exists(THUMBNAILS_DIR): os.makedirs(THUMBNAILS_DIR)
    if not os.path.exists(ARCHIVES_DIR): os.makedirs(ARCHIVES_DIR)

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
            self.status = "Initializing"
            self.motion_detected_in_frame = False
            self.min_recording_time = int(self.config.get('min_recording_time', 15))
            self.recording_start_time = 0

        def run(self):
            url, sensitivity = self.config['url_sd'], int(self.config.get('sensitivity', 1000))
            source = int(url) if url.isdigit() else url
            while self.is_running:
                self.status = "Connecting"
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    self.status = "Connection Failed"
                    print(f"[{self.config['name']}] Echec connexion. Nouvelle tentative dans {COOLDOWN_SECONDS}s.")
                    time.sleep(COOLDOWN_SECONDS)
                    continue
                self.status = "Connected"
                print(f"[{self.config['name']}] Connexion reussie.")
                bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=128, detectShadows=False)
                start_time = time.time()
                while self.is_running and cap.isOpened():
                    success, frame = cap.read()
                    if not success: self.status = "Stream Lost"; print(f"[{self.config['name']}] Flux perdu. Reconnexion..."); break
                    self.motion_detected_in_frame = False
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
                    
                    if self.is_recording and (time.time() - self.last_motion_time > COOLDOWN_SECONDS):
                        if (time.time() - self.recording_start_time >= self.min_recording_time):
                            self.stop_recording()

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
            self.recording_start_time = time.time()
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

    def load_cameras_config():
        if not os.path.exists(CONFIG_FILE): return {}
        try:
            with open(CONFIG_FILE,'r',encoding='utf-8') as f: return json.load(f)
        except json.JSONDecodeError as e: print(f"!!! ERREUR SYNTAXE {CONFIG_FILE}: {e} !!!"); return {}
        except Exception as e: print(f"!!! ERREUR LECTURE {CONFIG_FILE}: {e} !!!"); return {}
    def save_cameras_config(cameras):
        with open(CONFIG_FILE,'w',encoding='utf-8') as f: json.dump(cameras,f,indent=4)

    def get_directory_size(path):
        total_size = 0
        if not os.path.isdir(path):
            return 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        total_size += os.path.getsize(fp)
        except OSError:
            return 0
        return total_size

    def format_size(size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "Ko", "Mo", "Go", "To")
        i = int(math.floor(math.log(size_bytes, 1024))) if size_bytes > 0 else 0
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

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
                ret, buffer = cv2.imencode('.jpg', frame)
                if not ret: continue
                yield (b'--frame\r\n'b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'); time.sleep(1/VIDEO_FPS)
        elif quality == 'hd':
            cam_config = load_cameras_config().get(cam_id)
            if not cam_config or not cam_config.get('url_hd'): return
            url = cam_config['url_hd']; source = int(url) if url.isdigit() else url; cap = cv2.VideoCapture(source)
            if not cap.isOpened(): return
            while True:
                success, frame = cap.read()
                if not success: break
                ret, buffer = cv2.imencode('.jpg', frame);
                if ret: yield (b'--frame\r\n'b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            cap.release()

    # --- ROUTES ---
    @app.route('/')
    def index():
        return render_template('index.html', cameras={k: v for k, v in load_cameras_config().items() if v.get('is_active', False)})

    @app.route('/add_camera_form')
    def add_camera_form():
        return render_template('add_camera.html')

    @app.route('/add_camera', methods=['POST'])
    def add_camera():
        cameras = load_cameras_config()
        new_cam_id = str(uuid.uuid4())
        cameras[new_cam_id] = {
            'name': request.form['camera_name'], 'url_sd': request.form['camera_url_sd'], 'url_hd': request.form['camera_url_hd'],
            'sensitivity': int(request.form.get('sensitivity', 1000)), 'is_active': 'is_active' in request.form,
            'is_recording_enabled': 'is_recording_enabled' in request.form, 'show_detection': 'show_detection' in request.form,
            'min_recording_time': int(request.form.get('min_recording_time', 15))
        }
        save_cameras_config(cameras)
        sync_camera_threads()
        return redirect(url_for('config'))

    @app.route('/update/<cam_id>', methods=['POST'])
    def update_camera(cam_id):
        cameras = load_cameras_config()
        if cam_id in cameras:
            old_name = cameras[cam_id].get('name')
            new_name = request.form['camera_name']
            if old_name != new_name:
                with thread_lock:
                    if cam_id in camera_threads:
                        print(f"[MIGRATION] Arrêt temporaire de '{old_name}' pour renommage.")
                        camera_threads[cam_id].stop()
                        camera_threads[cam_id].join(timeout=2.0)
                        camera_threads.pop(cam_id, None)
                print(f"[MIGRATION] Le nom de la caméra '{old_name}' a changé en '{new_name}'.")
                old_safe_name = sanitize_filename(old_name)
                new_safe_name = sanitize_filename(new_name)
                for base_dir in [RECORDINGS_DIR, THUMBNAILS_DIR, ARCHIVES_DIR]:
                    old_path = os.path.join(base_dir, old_safe_name)
                    new_path = os.path.join(base_dir, new_safe_name)
                    if os.path.isdir(old_path):
                        if not os.path.isdir(new_path):
                            try:
                                shutil.move(old_path, new_path)
                                print(f"[MIGRATION] Succès : '{old_path}' -> '{new_path}'")
                            except Exception as e:
                                print(f"[MIGRATION][ERREUR] Impossible de déplacer '{old_path}': {e}")
                        else:
                            print(f"[MIGRATION][AVERTISSEMENT] Le dossier '{new_path}' existe déjà.")
            cameras[cam_id]['name'] = new_name
            cameras[cam_id]['url_sd'] = request.form['camera_url_sd']
            cameras[cam_id]['url_hd'] = request.form['camera_url_hd']
            cameras[cam_id]['sensitivity'] = int(request.form.get('sensitivity', 1000))
            cameras[cam_id]['is_active'] = 'is_active' in request.form
            cameras[cam_id]['is_recording_enabled'] = 'is_recording_enabled' in request.form
            cameras[cam_id]['show_detection'] = 'show_detection' in request.form
            cameras[cam_id]['min_recording_time'] = int(request.form.get('min_recording_time', 15))
        save_cameras_config(cameras)
        sync_camera_threads()
        return redirect(url_for('config'))
    
    @app.route('/config')
    def config():
        cameras = load_cameras_config()
        for cam_id, camera_config in cameras.items():
            safe_camera_name = sanitize_filename(camera_config.get('name', ''))
            recordings_path = os.path.join(RECORDINGS_DIR, safe_camera_name)
            archives_path = os.path.join(ARCHIVES_DIR, safe_camera_name)
            recordings_size = get_directory_size(recordings_path)
            archives_size = get_directory_size(archives_path)
            camera_config['recordings_usage'] = format_size(recordings_size)
            camera_config['archives_usage'] = format_size(archives_size)
        return render_template('config.html', cameras=cameras)
    
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
            shutil.rmtree(os.path.join(ARCHIVES_DIR, cam_name_safe), ignore_errors=True)
            del cameras[cam_id]; 
            save_cameras_config(cameras); 
            sync_camera_threads()
        return redirect(url_for('config'))
    
    @app.route('/archives/<cam_id>')
    def archives_page(cam_id):
        all_cameras = load_cameras_config()
        camera_info = all_cameras.get(cam_id)
        if not camera_info:
            return "Caméra non trouvée", 404
        safe_cam_name = sanitize_filename(camera_info['name'])
        cam_path = os.path.join(ARCHIVES_DIR, safe_cam_name)
        dates_structure = []
        if os.path.isdir(cam_path):
            for date_folder in sorted(os.listdir(cam_path), reverse=True):
                date_path = os.path.join(cam_path, date_folder)
                if os.path.isdir(date_path):
                    date_data = {'date': date_folder, 'files': []}
                    for filename in sorted(os.listdir(date_path)):
                        if filename.endswith('.mp4'):
                            comment = ""
                            meta_path = os.path.join(date_path, filename.replace('.mp4', '.meta.json'))
                            if os.path.exists(meta_path):
                                try:
                                    with open(meta_path, 'r', encoding='utf-8') as f:
                                        meta_data = json.load(f)
                                        comment = meta_data.get('comment', '')
                                except (IOError, json.JSONDecodeError):
                                    comment = "Erreur lecture commentaire"
                            date_data['files'].append({
                                'filename': filename,
                                'thumb_filename': filename.replace('.mp4', '.jpg'),
                                'time': filename.replace('.mp4', '').replace('-', ':'),
                                'comment': comment
                            })
                    if date_data['files']:
                        dates_structure.append(date_data)
        return render_template('archives.html', 
                               camera_info=camera_info, 
                               safe_cam_name=safe_cam_name,
                               dates=dates_structure)

    @app.route('/api/status')
    def api_status():
        statuses = {};
        with thread_lock:
            for cam_id, thread in camera_threads.items():
                statuses[cam_id] = {"id": cam_id, "name": thread.config.get('name', 'N/A'), "status": thread.status, "is_recording": thread.is_recording, "motion_detected": thread.motion_detected_in_frame}
        return jsonify(statuses)
    
    @app.route('/api/check_update')
    def check_update():
        try:
            response = requests.get(UPDATE_URL, timeout=5)
            response.raise_for_status()
            latest_version_info = response.json()
            latest_version = latest_version_info.get("version")
            download_url = latest_version_info.get("download_url")
            if latest_version and latest_version > APP_VERSION:
                return jsonify({ "update_available": True, "latest_version": latest_version, "download_url": download_url })
            else:
                return jsonify({"update_available": False})
        except requests.exceptions.RequestException as e:
            print(f"[UPDATE CHECK] Erreur réseau: {e}")
            return jsonify({"update_available": False, "error": "network_error"})
        except Exception as e:
            print(f"[UPDATE CHECK] Erreur inattendue: {e}")
            return jsonify({"update_available": False, "error": "server_error"})

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

    @app.route('/api/available_dates/<cam_id>')
    def api_available_dates(cam_id):
        cameras = load_cameras_config()
        if cam_id not in cameras:
            return jsonify([]), 404
        safe_camera_name = sanitize_filename(cameras[cam_id]['name'])
        recordings_cam_dir = os.path.join(RECORDINGS_DIR, safe_camera_name)
        available_dates = []
        if os.path.isdir(recordings_cam_dir):
            for date_folder in os.listdir(recordings_cam_dir):
                full_path = os.path.join(recordings_cam_dir, date_folder)
                if os.path.isdir(full_path) and len(os.listdir(full_path)) > 0:
                    available_dates.append(date_folder)
        return jsonify(available_dates)
    
    @app.route('/api/delete_hour', methods=['POST'])
    def api_delete_hour():
        data = request.json
        cam_id = data.get('cam_id')
        date = data.get('date')
        hour = data.get('hour')
        if not all([cam_id, date, hour]):
            return jsonify({'status': 'error', 'message': 'Données manquantes'}), 400
        cameras = load_cameras_config()
        if cam_id not in cameras:
            return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 404
        safe_camera_name = sanitize_filename(cameras[cam_id]['name'])
        recordings_dir = os.path.join(RECORDINGS_DIR, safe_camera_name, date)
        thumbnails_dir = os.path.join(THUMBNAILS_DIR, safe_camera_name, date)
        deleted_count = 0
        try:
            if os.path.isdir(recordings_dir):
                for filename in os.listdir(recordings_dir):
                    if filename.startswith(hour + '-') and filename.endswith('.mp4'):
                        os.remove(os.path.join(recordings_dir, filename))
                        deleted_count += 1
            if os.path.isdir(thumbnails_dir):
                for filename in os.listdir(thumbnails_dir):
                    if filename.startswith(hour + '-') and filename.endswith('.jpg'):
                        os.remove(os.path.join(thumbnails_dir, filename))
            return jsonify({'status': 'success', 'message': f'{deleted_count} fichiers supprimés.'})
        except Exception as e:
            print(f"[ERREUR] Suppression par heure impossible pour {date}/{hour}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    @app.route('/api/delete_recording', methods=['POST'])
    def api_delete_recording():
        data = request.json
        cam_id = data.get('cam_id')
        date = data.get('date')
        filename = data.get('filename')
        if not all([cam_id, date, filename]):
            return jsonify({'status': 'error', 'message': 'Données manquantes'}), 400
        cameras = load_cameras_config()
        if cam_id not in cameras:
            return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 404
        safe_camera_name = sanitize_filename(cameras[cam_id]['name'])
        video_path = os.path.abspath(os.path.join(RECORDINGS_DIR, safe_camera_name, date, filename))
        thumb_path = os.path.abspath(os.path.join(THUMBNAILS_DIR, safe_camera_name, date, filename.replace('.mp4', '.jpg')))
        if not video_path.startswith(os.path.abspath(RECORDINGS_DIR)):
            return jsonify({'status': 'error', 'message': 'Chemin invalide'}), 400
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                print(f"[ACTION] Fichier vidéo supprimé : {video_path}")
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
                print(f"[ACTION] Miniature supprimée : {thumb_path}")
            return jsonify({'status': 'success', 'message': 'Fichiers supprimés'})
        except Exception as e:
            print(f"[ERREUR] Suppression impossible pour {filename}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/archive_recording', methods=['POST'])
    def api_archive_recording():
        data = request.json
        cam_id = data.get('cam_id')
        date = data.get('date')
        filename = data.get('filename')
        if not all([cam_id, date, filename]):
            return jsonify({'status': 'error', 'message': 'Données manquantes'}), 400
        cameras = load_cameras_config()
        if cam_id not in cameras:
            return jsonify({'status': 'error', 'message': 'Caméra inconnue'}), 404
        safe_camera_name = sanitize_filename(cameras[cam_id]['name'])
        video_src_path = os.path.abspath(os.path.join(RECORDINGS_DIR, safe_camera_name, date, filename))
        thumb_src_path = os.path.abspath(os.path.join(THUMBNAILS_DIR, safe_camera_name, date, filename.replace('.mp4', '.jpg')))
        archive_dir = os.path.abspath(os.path.join(ARCHIVES_DIR, safe_camera_name, date))
        video_dest_path = os.path.join(archive_dir, filename)
        if not video_src_path.startswith(os.path.abspath(RECORDINGS_DIR)):
            return jsonify({'status': 'error', 'message': 'Chemin source invalide'}), 400
        if not archive_dir.startswith(os.path.abspath(ARCHIVES_DIR)):
            return jsonify({'status': 'error', 'message': 'Chemin destination invalide'}), 400
        try:
            os.makedirs(archive_dir, exist_ok=True)
            if os.path.exists(video_src_path):
                shutil.move(video_src_path, video_dest_path)
                print(f"[ACTION] Fichier vidéo archivé : {video_dest_path}")
            if os.path.exists(thumb_src_path):
                shutil.move(thumb_src_path, os.path.join(archive_dir, filename.replace('.mp4', '.jpg')))
                print(f"[ACTION] Miniature archivée pour : {filename}")
            return jsonify({'status': 'success', 'message': 'Fichiers archivés'})
        except Exception as e:
            print(f"[ERREUR] Archivage impossible pour {filename}: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/archives/save_comment', methods=['POST'])
    def save_archive_comment():
        data = request.json
        safe_cam_name = data.get('safe_cam_name')
        date = data.get('date')
        filename = data.get('filename')
        comment = data.get('comment', '')
        if not all([safe_cam_name, date, filename]):
            return jsonify({'status': 'error', 'message': 'Données manquantes'}), 400
        meta_path = os.path.abspath(os.path.join(ARCHIVES_DIR, safe_cam_name, date, filename.replace('.mp4', '.meta.json')))
        if not meta_path.startswith(os.path.abspath(ARCHIVES_DIR)):
            return jsonify({'status': 'error', 'message': 'Chemin invalide'}), 400
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump({'comment': comment}, f, indent=4)
            return jsonify({'status': 'success', 'new_comment': comment})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/archives/delete', methods=['POST'])
    def delete_archive():
        data = request.json
        safe_cam_name = data.get('safe_cam_name')
        date = data.get('date')
        filename = data.get('filename')
        if not all([safe_cam_name, date, filename]):
            return jsonify({'status': 'error', 'message': 'Données manquantes'}), 400
        base_path = os.path.abspath(os.path.join(ARCHIVES_DIR, safe_cam_name, date))
        if not base_path.startswith(os.path.abspath(ARCHIVES_DIR)):
            return jsonify({'status': 'error', 'message': 'Chemin invalide'}), 400
        video_path = os.path.join(base_path, filename)
        thumb_path = os.path.join(base_path, filename.replace('.mp4', '.jpg'))
        meta_path = os.path.join(base_path, filename.replace('.mp4', '.meta.json'))
        try:
            if os.path.exists(video_path): os.remove(video_path)
            if os.path.exists(thumb_path): os.remove(thumb_path)
            if os.path.exists(meta_path): os.remove(meta_path)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/thumbnail/<camera_name>/<date>/<thumb_filename>')
    def serve_thumbnail(camera_name, date, thumb_filename):
        thumb_path = os.path.join(THUMBNAILS_DIR, sanitize_filename(camera_name), date)
        return send_from_directory(thumb_path, thumb_filename) if os.path.exists(os.path.join(thumb_path, thumb_filename)) else ("", 404)
    
    @app.route('/archives/thumbnail/<camera_name>/<date>/<thumb_filename>')
    def serve_archive_thumbnail(camera_name, date, thumb_filename):
        path = os.path.join(ARCHIVES_DIR, sanitize_filename(camera_name), date)
        return send_from_directory(path, thumb_filename)

    @app.route('/archives/play/<camera_name>/<date>/<filename>')
    def play_archive_video(camera_name, date, filename):
        path = os.path.join(ARCHIVES_DIR, sanitize_filename(camera_name), date)
        
        if 'download' in request.args:
            comment = ""
            meta_path = os.path.join(path, filename.replace('.mp4', '.meta.json'))
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        comment = json.load(f).get('comment', '')
                except Exception: pass
            
            all_cameras = load_cameras_config()
            camera_display_name = "Camera"
            for cam in all_cameras.values():
                if sanitize_filename(cam['name']) == camera_name:
                    camera_display_name = cam['name']
                    break
            
            safe_cam_display_name = sanitize_filename(camera_display_name)
            time_part = filename.replace('.mp4', '').replace('-', '_')
            new_filename_parts = [safe_cam_display_name, date, time_part]

            if comment:
                safe_comment = "".join(c if c.isalnum() or c in ' _-' else '' for c in comment).strip().replace(' ', '_')
                if safe_comment:
                    new_filename_parts.append(safe_comment)
            
            new_filename = "_".join(new_filename_parts) + ".mp4"
            
            return send_from_directory(path, filename, as_attachment=True, download_name=new_filename)

        return send_from_directory(path, filename)

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
        print(f"\n--- Lancement du serveur VMS (Version {APP_VERSION}) ---")
        app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
except Exception as e:
    print(f"\n\n!!! ERREUR FATALE AU DEMARRAGE: {e} !!!\n\n"); traceback.print_exc();
    input("Le programme a plante. Appuyez sur Entree pour quitter...")