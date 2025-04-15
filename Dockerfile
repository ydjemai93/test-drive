# Utiliser une image Python officielle
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Installer curl (nécessaire pour télécharger lk) et nettoyer
RUN apt-get update && apt-get install -y curl --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Télécharger, rendre exécutable et installer le CLI lk (adapter si architecture différente d'amd64)
RUN curl -sfL https://github.com/livekit/livekit-cli/releases/latest/download/livekit-cli_linux_amd64.tar.gz | tar xz -C /usr/local/bin

# Copier le fichier de dépendances de l'API (maintenant à la racine/api)
COPY api/requirements.txt ./

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'API (maintenant à la racine/api)
COPY api/ ./api/

# Exposer le port que Uvicorn utilisera (la plateforme le mappera)
EXPOSE 8000

# Commande pour lancer l'API
# Le chemin vers main:app est relatif au WORKDIR
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
