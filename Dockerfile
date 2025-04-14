    # Utiliser une image Python officielle
    FROM python:3.11-slim

    # Définir le répertoire de travail
    WORKDIR /app

    # Installer curl (nécessaire pour télécharger lk) et nettoyer
    RUN apt-get update && apt-get install -y curl --no-install-recommends && \
        apt-get clean && rm -rf /var/lib/apt/lists/*

    # Télécharger, rendre exécutable et installer le CLI lk (adapter si architecture différente d'amd64)
    RUN curl -sfL https://github.com/livekit/livekit-cli/releases/latest/download/livekit-cli_linux_amd64.tar.gz | tar xz -C /usr/local/bin
    # Alternative si curl pose problème :
    # ADD https://github.com/livekit/livekit-cli/releases/latest/download/livekit-cli_linux_amd64.tar.gz /tmp/lk.tar.gz
    # RUN tar xzf /tmp/lk.tar.gz -C /usr/local/bin && rm /tmp/lk.tar.gz

    # Copier le fichier de dépendances de l'API
    COPY api/requirements.txt ./

    # Installer les dépendances Python
    RUN pip install --no-cache-dir -r api/requirements.txt

    # Copier le code de l'API
    COPY api/ ./api/

    # Exposer le port que Uvicorn utilisera (Railway le mappera)
    EXPOSE 8000

    # Commande pour lancer l'API (Railway utilisera $PORT, voir étape 3)
    # Utiliser le chemin relatif depuis WORKDIR
    CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
