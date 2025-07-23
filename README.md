
# Mon VMS Web - Système de Vidéosurveillance Avancé

Ce projet est un système de gestion de vidéosurveillance (VMS) complet, autonome et hautement personnalisable, doté d'une interface web moderne construite avec Python et Flask. Il permet de gérer plusieurs caméras IP, de détecter les mouvements, d'enregistrer, d'archiver et de consulter les vidéos de manière intuitive.

---

## 🚀 Fonctionnalités Principales

*   **📺 Streaming en Direct Robuste :** Visualisez les flux de vos caméras en direct. Le système assure une reconnexion automatique en cas de perte de flux.
*   **🧠 Détection de Mouvement Intelligente :** Utilise l'algorithme `BackgroundSubtractorMOG2` d'OpenCV pour une détection fiable.
*   **💾 Enregistrement Automatisé & Contrôlé :**
    *   Enregistre automatiquement des clips vidéo au format MP4 (H.264) sur détection de mouvement.
    *   **Durée Minimale d'Enregistrement :** Paramétrez une durée minimale pour chaque clip afin d'éviter les micro-enregistrements.
*   **⚙️ Gestion Dynamique des Caméras :** Ajoutez, modifiez ou supprimez des caméras **sans jamais interrompre les flux existants**.
*   **👁️ Statuts en Temps Réel :** La page d'accueil affiche l'état de chaque caméra (Connecté, REC, Mouvement) via des badges et des bordures colorées, mis à jour en direct.
*   **🎛️ Interface de Configuration Complète :**
    *   Gérez toutes vos caméras depuis une liste claire.
    *   Visualisez l'**espace disque utilisé** par les enregistrements et les archives pour chaque caméra, de manière séparée.
    *   Accédez à l'historique complet (Timeline, Enregistrements, Archives) de **n'importe quelle caméra**, même si elle est inactive.
*   **🎞️ Interface de Relecture Avancée (Timeline) :**
    *   Visualisez les événements d'une journée sur une **timeline interactive**.
    *   Contrôlez la **vitesse de lecture** (1x, 2x, 4x, 8x, 16x).
    *   **Archivez ou supprimez** la vidéo en cours de lecture d'un simple clic sur les icônes dédiées.
    *   Naviguez entre les jours grâce à un **calendrier intelligent** qui indique les dates contenant des enregistrements.
*   **🗂️ Gestion Puissante des Enregistrements :**
    *   **Archivage :** Protégez les vidéos importantes en les déplaçant vers un dossier d'archives sécurisé.
    *   **Suppression en Masse :** Supprimez tous les enregistrements d'une heure entière en un seul clic.
    *   **Suppression & Archivage Individuels :** Gérez chaque clip un par un.
*   **📦 Consultation des Archives :** Une page dédiée par caméra permet de consulter vos vidéos archivées, d'y ajouter des **commentaires**, de les **télécharger** avec un nom de fichier informatif (`NomCamera_Date_Heure_Commentaire.mp4`) ou de les supprimer.
*   **⬆️ Notification de Mise à Jour :** L'application vérifie automatiquement si une nouvelle version est disponible sur GitHub et affiche une notification cliquable pour télécharger l'installateur.

---

## 🛠️ Technologies Utilisées

*   **Backend :** Python 3, Flask
*   **Traitement Vidéo :** OpenCV
*   **Dépendances Python :** NumPy, Unidecode, Requests
*   **Interface :** HTML, CSS, JavaScript, Bootstrap (CDN), Flatpickr (CDN), Font Awesome (CDN)

---

## 📦 Installation et Lancement

### 1. Prérequis

*   [Python 3.8+](https://www.python.org/downloads/) et `pip`.

### 2. Installation des Dépendances

Ouvrez un terminal et exécutez la commande suivante :
```bash
pip install flask opencv-python numpy unidecode requests
Use code with caution.
Markdown
3. Lancement
Lancez le serveur depuis la racine du projet :
Generated bash
python app.py
Use code with caution.
Bash
Le serveur sera accessible à l'adresse http://127.0.0.1:5000.
💻 Création d'un Exécutable (.exe) pour Windows
Pour distribuer l'application sans que l'utilisateur n'ait besoin d'installer Python.
1. Installation de PyInstaller
Generated bash
pip install pyinstaller
Use code with caution.
Bash
2. Compilation
Assurez-vous que le fichier openh264-1.8.0-win64.dll est présent à la racine de votre projet si vous rencontrez des problèmes de codec sur d'autres PC. Lancez ensuite la commande suivante depuis le terminal, à la racine de votre projet :
Generated bash
pyinstaller --name MonVMS --onefile --add-data "templates;templates" --add-binary "openh264-1.8.0-win64.dll;." app.py
Use code with caution.
Bash
L'exécutable MonVMS.exe sera créé dans le dossier dist/.
3. Création d'un Installateur (Recommandé)
Pour une installation facile (Suivant > Suivant > Terminer) et un démarrage automatique avec Windows, vous pouvez utiliser un outil comme Inno Setup.

🌳 Arborescence du Projet
Generated code
MonVMS/
├── app.py              # Cœur de l'application (serveur, routes, logique)
├── cameras.json        # Fichier de configuration des caméras
├── version.json        # Fichier de vérification des mises à jour (sur GitHub)
├── recordings/         # Dossier des enregistrements courants
├── thumbnails/         # Dossier des miniatures
├── archives/           # Dossier des vidéos archivées (protégées)
├── templates/          # <-- Dossier contenant les fichiers HTML de l'interface web
│   ├── add_camera.html # <-- Page dédiée pour ajouter une caméra
│   ├── config.html     # <-- Page de configuration (liste des caméras)
│   ├── edit_camera.html# <-- Page de modification d'une caméra
│   ├── fullscreen.html # <-- Page d'affichage plein écran d'un flux
│   ├── index.html      # <-- Page d'accueil (vue en direct des caméras + statuts)
│   ├── playback.html   # <-- Page de relecture (timeline des événements)
│   └── recordings.html # <-- Page de grille des enregistrements
└── thumbnails/         # <-- Dossier où les miniatures sont stockées (créé automatiquement)
