import os
import sys
import time
import subprocess
import requests
import zipfile
import shutil
import traceback

# --- CONFIGURATION ---
SERVER_EXECUTABLE_NAME = "serveur.exe"
# URL pour vérifier la dernière version (contient l'URL du pack complet)
UPDATE_URL = "https://raw.githubusercontent.com/lancienanubis/vms/main/version.json" 
# --------------------

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def log_to_console(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

def perform_download_and_extract(url, base_path):
    """Télécharge un ZIP depuis une URL et l'extrait."""
    update_dir = os.path.join(base_path, "download_temp")
    if not os.path.exists(update_dir): os.makedirs(update_dir)
    zip_path = os.path.join(update_dir, "package.zip")
    
    log_to_console("Téléchargement du package...")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    log_to_console("Téléchargement terminé.")

    extract_path = os.path.join(update_dir, "extracted")
    log_to_console("Extraction de l'archive...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_path)
    log_to_console("Extraction terminée.")
    
    log_to_console("Remplacement des anciens fichiers...")
    protected_items = [os.path.basename(sys.executable), "lanceur.py", "lanceur.log"]
    
    for item in os.listdir(extract_path):
        if item in protected_items:
            continue
        
        source_item = os.path.join(extract_path, item)
        dest_item = os.path.join(base_path, item)
        
        if os.path.isdir(dest_item):
            shutil.rmtree(dest_item)
        elif os.path.exists(dest_item):
            os.remove(dest_item)
        shutil.move(source_item, dest_item)
    
    log_to_console("Mise à jour des fichiers terminée.")
    shutil.rmtree(update_dir)

def main():
    base_path = get_base_path()
    server_path = os.path.join(base_path, SERVER_EXECUTABLE_NAME)

    # --- ÉTAPE D'AUTO-INSTALLATION AU PREMIER LANCEMENT ---
    if not os.path.exists(server_path):
        log_to_console("Première installation, veuillez patienter...")
        try:
            response = requests.get(UPDATE_URL, timeout=15)
            response.raise_for_status()
            package_url = response.json().get("download_url")
            if not package_url:
                raise ValueError("URL du package non trouvée dans le fichier de version.")
            
            perform_download_and_extract(package_url, base_path)
            log_to_console("Installation terminée avec succès !")
            time.sleep(2)
        except Exception as e:
            log_to_console(f"--- ERREUR CRITIQUE PENDANT L'INSTALLATION ---")
            log_to_console(str(e))
            input("\nL'installation a échoué. Appuyez sur Entrée pour quitter.")
            return

    # --- BOUCLE DE LANCEMENT NORMALE ---
    command_to_run = [server_path]
    
    while True:
        log_to_console(f"Lancement de {SERVER_EXECUTABLE_NAME}...")
        process = subprocess.Popen(command_to_run)
        process.wait() 
        log_to_console(f"Le serveur s'est arrêté (code: {process.returncode}).")

        update_signal_file = os.path.join(base_path, "update_signal.txt")
        if os.path.exists(update_signal_file):
            log_to_console("Signal de mise à jour détecté...")
            try:
                with open(update_signal_file, 'r') as f:
                    download_url = f.read().strip()
                
                perform_download_and_extract(download_url, base_path)
                
            except Exception as e:
                log_to_console(f"--- ERREUR PENDANT LA MISE A JOUR ---")
                log_to_console(traceback.format_exc())
            finally:
                if os.path.exists(update_signal_file):
                    os.remove(update_signal_file)
        else:
            log_to_console("Redémarrage simple dans 5 secondes (suite à un arrêt normal ou un crash)...")
            time.sleep(5)

if __name__ == "__main__":
    main()