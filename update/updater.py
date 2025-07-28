import os
import sys
import time
import zipfile
import shutil
import subprocess
import traceback

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # En dev, l'updater est dans /update, donc on remonte d'un niveau
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def log(message):
    try:
        log_file = os.path.join(get_base_path(), "updater.log")
        with open(log_file, "a", encoding='utf-8') as f:
            log_line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
            f.write(log_line)
            print(log_line, flush=True)
    except Exception:
        pass # Ne pas planter si on ne peut pas logger

# Effacer l'ancien log au démarrage
log_file_path = os.path.join(get_base_path(), "updater.log")
if os.path.exists(log_file_path):
    os.remove(log_file_path)

log("--- LANCEUR DE MISE A JOUR DÉMARRÉ ---")

try:
    log(f"Arguments reçus: {sys.argv}")
    time.sleep(3)
    log("Attente de 3 secondes terminée.")

    executable_to_restart = sys.argv[1] if len(sys.argv) > 1 else "app.py"
    application_path = get_base_path()
    
    log(f"Chemin de l'application: {application_path}")
    update_zip_path = os.path.join(application_path, "update", "update.zip")
    
    if os.path.exists(update_zip_path):
        log("Fichier ZIP trouvé. Décompression...")
        temp_extract_path = os.path.join(application_path, "update", "extracted")
        if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
        os.makedirs(temp_extract_path)
        
        with zipfile.ZipFile(update_zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_path)
        log("Décompression terminée.")

        log("Début du remplacement des fichiers...")
        for item in os.listdir(temp_extract_path):
            source_path = os.path.join(temp_extract_path, item)
            dest_path = os.path.join(application_path, item)
            log(f"  -> Remplacement de '{item}'")
            if os.path.isdir(source_path):
                if os.path.exists(dest_path): shutil.rmtree(dest_path)
                shutil.move(source_path, dest_path)
            else:
                if os.path.exists(dest_path): os.remove(dest_path)
                shutil.move(source_path, dest_path)
        log("Remplacement terminé.")
    else:
        log(f"ERREUR: Fichier {update_zip_path} non trouvé.")

except Exception as e:
    log("!!! ERREUR PENDANT LA MISE A JOUR !!!")
    log(traceback.format_exc())

finally:
    update_dir = os.path.join(application_path, "update")
    if os.path.isdir(update_dir):
        log("Nettoyage des fichiers temporaires...")
        # ... (logique de nettoyage si nécessaire) ...
    
    log(f"Redémarrage de '{executable_to_restart}'...")
    path_to_restart = os.path.join(application_path, executable_to_restart)
    
    if executable_to_restart.endswith('.py'):
        subprocess.Popen([sys.executable, path_to_restart])
    else:
        subprocess.Popen([path_to_restart])
    
    log("--- PROCESSUS DE MISE A JOUR TERMINE ---")