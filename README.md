# VMS - Système de Vidéosurveillance en Python/Flask

Ce projet est un système de gestion de vidéosurveillance (VMS) complet et autonome, doté d'une interface web riche construite avec Python et le micro-framework Flask. Il permet de gérer plusieurs caméras IP, de détecter les mouvements, d'enregistrer des vidéos automatiquement et de les revoir via une interface de relecture avancée.

---

## 🚀 Fonctionnalités Principales

*   **📺 Streaming en Direct Robuste :** Visualisez les flux de vos caméras en direct. Le système assure une reconnexion automatique en cas de perte de flux et offre une visualisation fluide des flux SD.
*   **🧠 Détection de Mouvement Intelligente :** Utilise l'algorithme `BackgroundSubtractorMOG2` d'OpenCV pour une détection de mouvement fiable, avec un délai de stabilisation pour éviter les fausses alertes.
*   **💾 Enregistrement Automatique :** Enregistre automatiquement des clips vidéo au format MP4 (H.264) sur détection de mouvement, avec création de miniatures pour un aperçu rapide.
*   **⚙️ Gestion Dynamique des Caméras :** Le système intègre la fonction `sync_camera_threads` qui permet d'ajouter, modifier, activer/désactiver ou supprimer une caméra **sans interrompre les flux des autres caméras**. Cela assure une continuité de service et une meilleure stabilité.
*   **👁️ Statuts en Temps Réel (Page d'Accueil) :** La page d'accueil affiche désormais l'état de chaque caméra en direct (connectée, en enregistrement, flux perdu, etc.) via des badges colorés et des indicateurs visuels (bordure de l'image).
*   **🎛️ Interface de Configuration Améliorée :**
    *   La page de configuration (`/config`) est simplifiée, affichant une liste claire des caméras avec leur statut d'activité, d'enregistrement et de détection visuelle. Les URLs ne sont plus affichées dans le tableau pour plus de clarté.
    *   Un bouton dédié mène vers une **nouvelle page de formulaire (`/add_camera_form`)** pour ajouter facilement de nouvelles caméras.
    *   La page de modification (`/edit_camera/<id>`) a été mise à jour pour avoir la même présentation cohérente que la page d'ajout.
    *   Les boutons de navigation redondants ont été retirés des pages de configuration et d'ajout/modification pour une interface plus épurée.
*   **🎞️ Interface de Relecture Avancée :**
    *   Une page de relecture par caméra, avec une timeline visuelle des événements de la journée. Les liens de navigation redondants ont été retirés de cette page.
    *   Une galerie de miniatures regroupées par heure pour une navigation rapide.
*   **🗂️ Organisation Structurée des Fichiers :** Les enregistrements et les miniatures sont automatiquement organisés dans une arborescence de dossiers claire : `recordings/Nom_Camera/Date/Heure.mp4`.

---

## 🛠️ Technologies Utilisées

*   **Backend :** [Python 3](https://www.python.org/)
*   **Framework Web :** [Flask](https://flask.palletsprojects.com/)
*   **Traitement Vidéo :** [OpenCV](https://opencv.org/)
*   **Manipulation de Données :** [NumPy](https://numpy.org/)
*   **Gestion de caractères :** [Unidecode](https://pypi.org/project/Unidecode/)
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
2.  Au premier lancement ou si le fichier n'existe pas, vous pouvez le créer manuellement via l'interface web en cliquant sur "Ajouter une Caméra" dans la section "Configuration".
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


VMS_Python/
├── app.py              # <-- Cœur de l'application (serveur, routes, logique des caméras)
├── cameras.json        # <-- Fichier de configuration où sont stockées vos caméras
├── recordings/         # <-- Dossier où les vidéos sont enregistrées (créé automatiquement)
│   └── NOM_DE_LA_CAMERA/
│       └── AAAA-MM-JJ/
│           └── HH-MM-SS.mp4
├── templates/          # <-- Dossier contenant les fichiers HTML de l'interface web
│   ├── add_camera.html # <-- Page dédiée pour ajouter une caméra
│   ├── config.html     # <-- Page de configuration (liste des caméras)
│   ├── edit_camera.html# <-- Page de modification d'une caméra
│   ├── fullscreen.html # <-- Page d'affichage plein écran d'un flux
│   ├── index.html      # <-- Page d'accueil (vue en direct des caméras + statuts)
│   ├── playback.html   # <-- Page de relecture (timeline des événements)
│   └── recordings.html # <-- Page de grille des enregistrements
└── thumbnails/         # <-- Dossier où les miniatures sont stockées (créé automatiquement)
    └── NOM_DE_LA_CAMERA/
        └── AAAA-MM-JJ/
            └── HH-MM-SS.jpg
