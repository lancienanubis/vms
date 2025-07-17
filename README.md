# VMS - Système de Vidéosurveillance en Python/Flask

Ce projet est un système de gestion de vidéosurveillance (VMS) complet et autonome, doté d'une interface web riche construite avec Python et le micro-framework Flask. Il permet de gérer plusieurs caméras IP, de détecter les mouvements, d'enregistrer des vidéos automatiquement et de les revoir via une interface de relecture avancée.

---

## 🚀 Fonctionnalités Principales

*   **📺 Streaming en Direct Multi-Qualité :** Visualisez les flux de vos caméras en direct, avec une gestion séparée des flux SD (basse définition, pour l'analyse) et HD (haute définition, pour la visualisation).
*   **🧠 Détection de Mouvement Intelligente :** Utilise l'algorithme `BackgroundSubtractorMOG2` d'OpenCV pour une détection de mouvement fiable, avec un délai de stabilisation pour éviter les fausses alertes.
*   **💾 Enregistrement Automatique :** Enregistre automatiquement des clips vidéo au format MP4 (H.264) sur détection de mouvement, avec création de miniatures pour un aperçu rapide.
*   **⚙️ Gestion Dynamique des Caméras :** Le système a été amélioré avec une synchronisation intelligente (`sync_camera_threads`) qui permet d'ajouter, modifier, activer/désactiver ou supprimer une caméra sans jamais interrompre le flux des autres caméras.
*   **🎛️ Interface de Configuration Complète :** Une interface web permet de gérer l'ensemble des caméras et de leurs paramètres (nom, URLs, sensibilité de détection, activation de l'enregistrement, etc.).
*   **🎞️ Interface de Relecture Avancée :**
    *   Une page de relecture par caméra.
    *   Une timeline visuelle des événements de la journée.
    *   Une galerie de miniatures regroupées par heure pour une navigation rapide.
*   **🗂️ Organisation Structurée des Fichiers :** Les enregistrements et les miniatures sont automatiquement organisés dans une arborescence de dossiers claire : `recordings/Nom_Camera/Date/Heure.mp4`.

---

## 🛠️ Technologies Utilisées

*   **Backend :** [Python 3](https://www.python.org/)
*   **Framework Web :** [Flask](https://flask.palletsprojects.com/)
*   **Traitement Vidéo :** [OpenCV](https://opencv.org/)
*   **Manipulation de Données :** [NumPy](https://numpy.org/)
*   **Interface :** HTML / CSS (Bootstrap via CDN) / JavaScript

---

## 📦 Installation et Lancement

Suivez ces étapes pour mettre en place et lancer le projet.

### 1. Prérequis

*   [Python 3.8+](https://www.python.org/downloads/) installé.
*   `pip` (le gestionnaire de paquets Python) à jour.

### 2. Installation

1.  Clonez ce dépôt ou téléchargez les fichiers dans un dossier de votre choix.
    ```bash
    git clone https://github.com/lancienanubis/vms.git
    cd vms
    ```
2.  Installez manuellement les dépendances Python nécessaires. Ouvrez un terminal et exécutez les commandes suivantes :
    ```bash
    pip install flask
    pip install opencv-python
    pip install numpy
    pip install unidecode
    ```

### 3. Configuration

1.  Le système utilise un fichier `cameras.json` pour la configuration des caméras.
2.  Au premier lancement ou si le fichier n'existe pas, vous pouvez le créer manuellement ou utiliser l'interface web pour ajouter votre première caméra.
3.  Voici un exemple de structure pour le fichier `cameras.json` :
    ```json
    {
        "d8f4c5a2-c1b3-4f5a-9a8b-7e6d5c4b3a21": {
            "name": "Caméra du Salon",
            "url_sd": "rtsp://user:password@192.168.1.50/stream2",
            "url_hd": "rtsp://user:password@192.168.1.50/stream1",
            "sensitivity": 1200,
            "is_active": true,
            "is_recording_enabled": true,
            "show_detection": true
        }
    }
    ```

### 4. Lancement

Une fois les dépendances installées et la configuration prête, lancez le serveur depuis la racine du projet :
```bash
python app.py
```
Le serveur démarrera et sera accessible à l'adresse **http://localhost:5000** ou **http://[VOTRE_IP_LOCALE]:5000**.

---

## ⚙️ Fonctionnement Détaillé

L'application est entièrement contenue dans `app.py` et fonctionne sur les principes suivants :

1.  **Démarrage :** Au lancement, le script initialise Flask et appelle la fonction `sync_camera_threads()`.
2.  **`sync_camera_threads()` :** C'est le cœur de la gestion dynamique. Cette fonction lit le fichier `cameras.json`, compare la liste des caméras configurées avec les threads actuellement en cours d'exécution, et effectue les actions suivantes :
    *   **Arrête** les threads des caméras qui ont été supprimées ou désactivées.
    *   **Démarre** un nouveau thread pour chaque nouvelle caméra active.
    *   **Redémarre** uniquement les threads dont la configuration a été modifiée.
3.  **Classe `CameraThread` :** Chaque caméra active est gérée par son propre thread (une instance de la classe `CameraThread`). Ce thread est responsable de :
    *   Se connecter au flux vidéo SD.
    *   Analyser en continu les images pour la détection de mouvement.
    *   Lancer et arrêter l'enregistrement des clips vidéo et la création des miniatures.
    *   Stocker la dernière image du flux pour le streaming en direct.
4.  **Interface Flask :** Le serveur Flask expose plusieurs routes :
    *   Des routes HTML qui affichent les différentes pages de l'interface (`/`, `/config`, `/playback/<cam_id>`, etc.).
    *   Des routes de streaming (`/video_feed/...`) qui renvoient un flux MJPEG pour la vidéo en direct.
    *   Des routes API (`/api/...`) que le JavaScript du frontend utilise pour obtenir des informations (liste des enregistrements, etc.) de manière asynchrone.




---

## 🌳 Arborescence du Projet

```
VMS_Python/
│
├── app.py              # <-- Cœur de l'application (serveur, routes, logique des caméras)
│
├── cameras.json        # <-- Fichier de configuration où sont stockées vos caméras
│
├── recordings/         # <-- Dossier où les vidéos sont enregistrées (créé automatiquement)
│   └── NOM_DE_LA_CAMERA/
│       └── AAAA-MM-JJ/
│           └── HH-MM-SS.mp4
│
├── templates/          # <-- Dossier contenant les fichiers HTML de l'interface web
│   ├── config.html
│   ├── edit_camera.html
│   ├── fullscreen.html
│   ├── index.html
│   ├── playback.html
│   └── recordings.html
│
└── thumbnails/         # <-- Dossier où les miniatures sont stockées (créé automatiquement)
    └── NOM_DE_LA_CAMERA/
        └── AAAA-MM-JJ/
            └── HH-MM-SS.jpg
```
