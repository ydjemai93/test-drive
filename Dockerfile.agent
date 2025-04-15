    # Utiliser une image Python officielle
    FROM python:3.11-slim

    # Définir le répertoire de travail DANS le dossier de l'agent pour simplifier les chemins
    WORKDIR /app/Cartesia/Demo/outbound

    # Copier le fichier de dépendances de l'agent
    # Le chemin source est relatif à la racine du dépôt, la destination est relative à WORKDIR
    COPY Cartesia/Demo/outbound/requirements.txt ./

    # Installer les dépendances Python
    RUN pip install --no-cache-dir -r requirements.txt

    # Copier le code de l'agent
    # Le chemin source est relatif à la racine du dépôt, la destination est relative à WORKDIR
    COPY Cartesia/Demo/outbound/ ./

    # Commande pour lancer l'agent
    CMD ["python", "agent.py"]
