import os
import sys
import time
import subprocess
import requests
import zipfile
import shutil
import traceback
import threading
import webbrowser
import logging
from logging.handlers import RotatingFileHandler
import re
from PIL import Image
from pystray import MenuItem as item, Icon as icon, Menu
import locale

# --- CONFIGURATION ---
SERVER_EXECUTABLE_NAME = "serveur.exe"
UPDATE_URL = "https://raw.githubusercontent.com/lancienanubis/vms/main/version.json" 
ICON_FILE = "icon.png"
LAUNCHER_LOG_FILE = "lanceur.log"
SERVER_LOG_FILE = "serveur.log"
LOG_MAX_SIZE_MB = 5
LOG_BACKUP_COUNT = 5
PORT_DETECTION_TIMEOUT = 15 

# --- VARIABLES GLOBALES ---
server_process = None
stop_event = threading.Event() 
status = "Initialisation..."
# Le chemin de base est défini une seule fois et utilisé partout pour une robustesse maximale
base_path = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

# Les chemins des logs sont construits à partir du chemin de base
LOG_DIRECTORY_PATH = os.path.join(base_path, "log")
LAUNCHER_LOG_PATH = os.path.join(LOG_DIRECTORY_PATH, LAUNCHER_LOG_FILE)
SERVER_LOG_PATH = os.path.join(LOG_DIRECTORY_PATH, SERVER_LOG_FILE)

discovered_port = None
local_ip = "127.0.0.1"
tray_icon = None

def setup_logging():
    max_bytes = LOG_MAX_SIZE_MB * 1024 * 1024
    rotating_handler = RotatingFileHandler(LAUNCHER_LOG_PATH, maxBytes=max_bytes, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S", handlers=[rotating_handler, logging.StreamHandler(sys.stdout)])

def rotate_server_log():
    if not os.path.exists(SERVER_LOG_PATH): return
    try:
        if os.path.getsize(SERVER_LOG_PATH) < (LOG_MAX_SIZE_MB * 1024 * 1024): return
        logging.info(f"Rotation de {SERVER_LOG_FILE}...");
        for i in range(LOG_BACKUP_COUNT - 1, 0, -1):
            source, dest = f"{SERVER_LOG_PATH}.{i}", f"{SERVER_LOG_PATH}.{i+1}"
            if os.path.exists(source):
                if os.path.exists(dest): os.remove(dest)
                os.rename(source, dest)
        if os.path.exists(SERVER_LOG_PATH): os.rename(SERVER_LOG_PATH, f"{SERVER_LOG_PATH}.1")
    except Exception as e:
        logging.error(f"Erreur lors de la rotation des logs du serveur: {e}")

def perform_download_and_extract(url, target_path):
    global status
    update_dir = os.path.join(target_path, "download_temp")
    if os.path.exists(update_dir): shutil.rmtree(update_dir)
    os.makedirs(update_dir)
    zip_path = os.path.join(update_dir, "package.zip")
    try:
        logging.info(f"Téléchargement depuis {url}..."); status = "Téléchargement..."
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logging.info("Téléchargement terminé."); status = "Extraction..."
        with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(os.path.join(update_dir, "extracted"))
        logging.info("Extraction terminée."); status = "Finalisation..."
        protected_items = [os.path.basename(sys.executable), "lanceur.py", "log"]
        for item_name in os.listdir(os.path.join(update_dir, "extracted")):
            if item_name in protected_items:
                logging.info(f"Élément protégé ignoré: {item_name}"); continue
            source_item, dest_item = os.path.join(update_dir, "extracted", item_name), os.path.join(target_path, item_name)
            if os.path.isdir(dest_item): shutil.rmtree(dest_item)
            elif os.path.exists(dest_item): os.remove(dest_item)
            shutil.move(source_item, dest_item)
        logging.info("Mise à jour/installation terminée."); return True
    except Exception:
        logging.exception("Erreur durant la mise à jour/installation.")
        status = "Erreur Opération"; return False
    finally:
        if os.path.exists(update_dir): shutil.rmtree(update_dir)

def get_status_text(icon): return f"Statut: {status}"
def open_url(url): logging.info(f"Ouverture de: {url}"); webbrowser.open(url)
def default_click_action(icon, item):
    if discovered_port: open_url(f"http://{local_ip}:{discovered_port}")
    else: logging.warning("Action par défaut: port non découvert.")
def open_log_file(log_path):
    try: os.startfile(log_path)
    except Exception as e: logging.error(f"Erreur ouverture log '{log_path}': {e}")

def kill_server_process():
    if server_process and server_process.poll() is None:
        logging.info(f"Arrêt forcé du processus serveur (PID: {server_process.pid})...")
        try:
            if sys.platform == "win32":
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(server_process.pid)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                server_process.kill()
            logging.info("Signal d'arrêt forcé envoyé au processus serveur.")
        except Exception as e:
            logging.error(f"Erreur lors de l'arrêt forcé du serveur: {e}")

def restart_server(icon, item):
    logging.info("Redémarrage manuel demandé.")
    kill_server_process()

def quit_application(icon, item):
    logging.info("Demande d'arrêt de l'application...")
    stop_event.set()
    kill_server_process()
    icon.stop()

def watch_server_log_for_port(stop_check_event):
    global discovered_port, local_ip, status, tray_icon
    pattern = re.compile(r"Running on http://(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(?P<port>\d+)")
    time.sleep(1)
    
    found_local_ip, found_port = None, None
    try:
        with open(SERVER_LOG_PATH, 'r', encoding=locale.getpreferredencoding(), errors='ignore') as f:
            start_time = time.time()
            while time.time() - start_time < PORT_DETECTION_TIMEOUT and not stop_check_event.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.2); continue

                match = pattern.search(line)
                if match:
                    captured_ip, captured_port = match.group('ip'), int(match.group('port'))
                    logging.info(f"Adresse détectée dans les logs: http://{captured_ip}:{captured_port}")
                    if captured_ip != "127.0.0.1":
                        discovered_port, local_ip = captured_port, captured_ip
                        logging.info(f"Adresse réseau prioritaire trouvée: {local_ip}:{discovered_port}")
                        status = "En cours"
                        if tray_icon: tray_icon.update_menu()
                        return
                    elif found_local_ip is None:
                        found_local_ip, found_port = captured_ip, captured_port
    except FileNotFoundError:
        logging.warning(f"Le fichier log du serveur n'existe pas encore: {SERVER_LOG_PATH}")
    except Exception as e:
        logging.error(f"Erreur lecture du port depuis le log: {e}")

    if found_local_ip and not discovered_port:
        discovered_port, local_ip = found_port, found_local_ip
        logging.info(f"Utilisation de l'adresse locale par défaut: {local_ip}:{discovered_port}")
        status = "En cours"
        if tray_icon: tray_icon.update_menu()
    elif not discovered_port:
        logging.warning("Port du serveur non découvert dans le temps imparti.")
        status = "En cours (port inconnu)"
        if tray_icon: tray_icon.update_menu()

def server_manager_thread():
    global server_process, status, discovered_port, local_ip
    server_path = os.path.join(base_path, SERVER_EXECUTABLE_NAME)
    if not os.path.exists(server_path):
        status = "Installation..."; logging.warning(f"'{SERVER_EXECUTABLE_NAME}' non trouvé. Installation...")
        try:
            response = requests.get(UPDATE_URL, timeout=15); response.raise_for_status()
            package_url = response.json().get("download_url")
            if not package_url: raise ValueError("URL du package non trouvée.")
            if not perform_download_and_extract(package_url, base_path):
                status = "Erreur Installation"; logging.error("Installation initiale échouée."); return
            status = "Installation finie"; logging.info("Installation terminée.")
        except Exception: status = "Erreur Installation"; logging.exception("Erreur critique durant l'installation."); return
    
    while not stop_event.is_set():
        discovered_port, local_ip, status = None, "127.0.0.1", "Démarrage..."
        if tray_icon: tray_icon.update_menu()
        
        rotate_server_log()
        with open(SERVER_LOG_PATH, 'a', encoding=locale.getpreferredencoding(), errors='ignore') as server_log_file:
            server_log_file.write(f"\n{'='*20} NOUVELLE SESSION SERVEUR : {time.strftime('%Y-%m-%d %H:%M:%S')} {'='*20}\n"); server_log_file.flush()
            logging.info(f"Lancement de {SERVER_EXECUTABLE_NAME}...")
            stop_log_watch = threading.Event()
            log_watcher = threading.Thread(target=watch_server_log_for_port, args=(stop_log_watch,))
            try:
                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                server_process = subprocess.Popen([server_path], stdout=server_log_file, stderr=subprocess.STDOUT, creationflags=creation_flags)
                log_watcher.start()
                server_process.wait()
            finally:
                stop_log_watch.set()
                log_watcher.join(timeout=1)
            
            if stop_event.is_set(): break

            status = f"Arrêté (code: {server_process.returncode})"; logging.warning(f"Serveur arrêté.")
            if tray_icon: tray_icon.update_menu()
            
            update_signal_file, restart_signal_file = os.path.join(base_path, "update_signal.txt"), os.path.join(base_path, "restart_signal.txt")
            if os.path.exists(restart_signal_file):
                logging.info("Signal de redémarrage détecté."); os.remove(restart_signal_file); continue
            elif os.path.exists(update_signal_file):
                logging.info("Signal de mise à jour détecté.")
                try:
                    with open(update_signal_file, 'r') as f: download_url = f.read().strip()
                    if download_url: perform_download_and_extract(download_url, base_path)
                    else: logging.error("Signal de MàJ vide.")
                finally: os.remove(update_signal_file)
                continue
            else:
                status = "Crash/Arrêt..."; logging.warning("Redémarrage dans 5s...")
                if stop_event.wait(timeout=5): break
    
    status = "Stoppé"; logging.info("Gestionnaire serveur arrêté.")
    if tray_icon: tray_icon.update_menu()

def create_main_menu():
    yield item(get_status_text, None, enabled=False)
    yield Menu.SEPARATOR
    if discovered_port:
        localhost_url = f"http://127.0.0.1:{discovered_port}"
        yield item(f"Ouvrir (Local): {localhost_url}", lambda: open_url(localhost_url))
        if local_ip != "127.0.0.1":
            network_url = f"http://{local_ip}:{discovered_port}"
            yield item(f"Ouvrir (Réseau): {network_url}", lambda: open_url(network_url))
    else:
        yield item("Détection port...", None, enabled=False)
    yield Menu.SEPARATOR
    log_menu = Menu(item('Log Lanceur', lambda: open_log_file(LAUNCHER_LOG_PATH)), item('Log Serveur', lambda: open_log_file(SERVER_LOG_PATH)))
    yield item('Logs', log_menu)
    yield item('Redémarrer', restart_server)
    yield Menu.SEPARATOR
    yield item('Quitter', quit_application)

def main():
    global tray_icon

    # ==============================================================================
    # <<< CORRECTION : LA MODIFICATION UNIQUE ET NÉCESSAIRE EST ICI >>>
    # On force le répertoire de travail à être celui où se trouve l'exécutable.
    # Cela garantit que toutes les opérations (y compris celles des bibliothèques
    # tierces) qui pourraient utiliser des chemins relatifs le font depuis la base
    # de l'application. C'est une "ceinture de sécurité" pour une robustesse maximale.
    os.chdir(base_path)
    # ==============================================================================
    
    os.makedirs(LOG_DIRECTORY_PATH, exist_ok=True)
    if os.path.exists(LAUNCHER_LOG_PATH):
        try:
            os.remove(LAUNCHER_LOG_PATH)
        except OSError as e:
            print(f"AVERTISSEMENT: Impossible de supprimer l'ancien fichier de log: {e}")
    
    setup_logging()
    
    logging.info("="*30); logging.info("DÉMARRAGE LANCEUR"); logging.info("="*30)
    logging.info(f"Les logs du lanceur sont enregistrés dans : {LAUNCHER_LOG_PATH}")
    logging.info(f"Les logs du serveur seront lus depuis : {SERVER_LOG_PATH}")
    
    # On peut maintenant utiliser un chemin relatif pour l'icône, car os.chdir a fait son travail
    icon_path = ICON_FILE
    try: image = Image.open(icon_path)
    except FileNotFoundError:
        logging.error(f"'{ICON_FILE}' non trouvé ! Création d'une icône par défaut."); image = Image.new('RGB', (64, 64), color='blue')
    
    tray_icon = icon("VMS_Launcher", image, "Mon VMS Launcher", menu=Menu(create_main_menu))
    tray_icon.DEFAULT_ACTION = default_click_action
    
    manager_thread = threading.Thread(target=server_manager_thread, daemon=True)
    manager_thread.start()
    
    logging.info("Lanceur démarré en mode icône.")
    tray_icon.run()
    
    logging.info("Le lanceur se ferme, attente de l'arrêt complet du serveur...")
    manager_thread.join(timeout=5)
    
    logging.info("="*30); logging.info("ARRÊT LANCEUR"); logging.info("="*30)

if __name__ == "__main__":
    main()