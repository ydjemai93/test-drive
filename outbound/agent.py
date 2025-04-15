from __future__ import annotations

import asyncio
import logging
import json
import os
import sys
import locale
from typing import Any

# Forcer l'encodage UTF-8 pour Windows (si nécessaire, mais peut être omis sur les systèmes Linux/macOS)
if sys.platform == 'win32':
    try:
        locale.setlocale(locale.LC_ALL, 'fr_FR.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, 'French_France.1252')
        except locale.Error:
            logger.warning("Could not set French locale for Windows.") # Utiliser logger si défini
            pass

# Configuration du logger (à faire avant les imports qui pourraient logger)
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stderr)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
# Éviter d'ajouter plusieurs fois le handler si le module est rechargé
if not logger.hasHandlers():
    logger.addHandler(handler)

# Importer les modules LiveKit après la configuration du logger
from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    get_job_context,
    cli,
    RoomInputOptions,
    WorkerOptions,
)
from livekit.plugins import (
    deepgram,
    openai,
    cartesia,
    silero,
)

# --- Définition de l'Agent ---
class OutboundCaller(Agent):
    def __init__(
        self,
        *,
        name: str, # Keep name parameter even if not used in the new prompt, in case entrypoint/metadata still provides it
        dial_info: dict[str, Any],
    ):
        # Prompt Système pour l'agent "Pam"
        super().__init__(
            instructions=(
                "Vous êtes Pam, un agent d\'assistance téléphonique IA développé par PAM AI, une solution SaaS permettant la création d\'agent téléphonique IA. "
                "pour la création d\'agents conversationnels intelligents. Lors de cette démonstration, présentez-vous de manière "
                "professionnelle et montrez vos capacités en tant qu\'agent IA polyvalent.\\n\\n"
                "IMPORTANT : Évitez complètement d\'utiliser des symboles de formatage comme les astérisques (**), "
                "le soulignement (_), le dièse (#), les puces ou tout autre formatage de type markdown. "
                "Formulez vos réponses uniquement en texte brut pour une lecture fluide par le système vocal. \\n\\n"
                "Vos capacités incluent la gestion de tâches administratives et de facturation pour un service client, "
                "l\'optimisation des opérations dans un centre d\'appels, et l\'assistance aux équipes commerciales et de recouvrement. "
                "Vous pouvez traiter les demandes clients, répondre aux questions fréquentes, effectuer des actions administratives "
                "simples, et aider à la résolution de problèmes.\\n\\n"
                "Pendant la conversation, soyez concis et naturel dans vos réponses, évitez les phrases trop longues ou complexes. "
                "Adaptez votre ton pour être professionnel et sympathique. Pour présenter vos fonctionnalités, utilisez des phrases "
                "simples sans puces ni formatage spécial. Ne jamais utiliser de symboles tels que les astérisques, tirets, dièses.\\n\\n"
                "Si nécessaire, vous pouvez simuler la résolution de problèmes courants comme: vérification de factures, "
                "mise à jour de coordonnées, prise de rendez-vous, transfert vers un conseiller humain, ou suivi de commandes. "
                "Répondez toujours en français, avec un langage clair et accessible à tous."
            )
        )
        # Garder la référence au participant pour les transferts etc.
        self.participant: rtc.RemoteParticipant | None = None
        self.dial_info = dial_info

        logger.info(f"OutboundCaller (Pam Demo Agent) initialisé pour {name}")
        logger.info(f"dial_info fourni: {dial_info}")

    def set_participant(self, participant: rtc.RemoteParticipant):
        """Enregistre le participant distant une fois connecté."""
        self.participant = participant
        logger.info(f"Participant {participant.identity} enregistré pour l'agent.")

    async def hangup(self):
        """Fonction utilitaire pour raccrocher en supprimant la room."""
        logger.warning("Raccrochage demandé (suppression de la room).")
        try:
            job_ctx = get_job_context()
            await job_ctx.api.room.delete_room(
                api.DeleteRoomRequest(room=job_ctx.room.name)
            )
            logger.info(f"Room {job_ctx.room.name} supprimée.")
        except Exception as e:
            logger.error(f"Erreur lors de la suppression de la room: {e}")

    # --- Outils Fonctionnels pour l'Agent ---
    @function_tool()
    async def transfer_call(self, ctx: RunContext):
        """Transfère l'appel à un agent humain, appelé après confirmation de l'utilisateur."""
        transfer_to = self.dial_info.get("transfer_to") # Utiliser .get pour éviter KeyError
        if not transfer_to:
            logger.warning("Numéro de transfert non trouvé dans dial_info.")
            return "Je suis désolé, je ne peux pas transférer l'appel pour le moment."

        if not self.participant:
            logger.error("Tentative de transfert sans participant enregistré.")
            return "Erreur technique lors de la tentative de transfert."

        logger.info(f"Tentative de transfert de l'appel du participant {self.participant.identity} vers {transfer_to}")

        # Laisser l'agent informer l'utilisateur avant le transfert
        try:
            await ctx.session.generate_reply(
                instructions="Informez l'utilisateur que vous allez le transférer maintenant."
            )
        except Exception as e:
             logger.error(f"Erreur lors de la génération de la réponse avant transfert: {e}")
             # Continuer quand même avec le transfert si possible

        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=self.participant.identity,
                    transfer_to=f"tel:{transfer_to}", # Assumer que transfer_to est un numéro valide
                )
            )
            logger.info(f"Appel transféré avec succès vers {transfer_to}. L'agent devrait se déconnecter.")
            # Normalement, après un transfert réussi, l'agent n'a plus de rôle.
            # On pourrait vouloir arrêter la session agent ici, mais la suppression de room gère ça.
            # await self.hangup() # Attention, peut couper le transfert si appelé trop tôt.
        except Exception as e:
            logger.error(f"Erreur lors du transfert de l'appel SIP: {e}")
            try:
                await ctx.session.generate_reply(
                    instructions="Informez l'utilisateur qu'une erreur est survenue lors du transfert."
                )
            except Exception as inner_e:
                logger.error(f"Erreur lors de la génération du message d'erreur de transfert: {inner_e}")
            await self.hangup() # Raccrocher en cas d'échec du transfert

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Appelé lorsque l'utilisateur souhaite mettre fin à l'appel."""
        if not self.participant:
             logger.warning("end_call demandé mais pas de participant enregistré.")
        else:
             logger.info(f"Fin d'appel demandée pour {self.participant.identity}")

        # Laisser l'agent finir de parler avant de raccrocher
        try:
            current_speech = ctx.session.current_speech
            if current_speech:
                logger.info("Attente de la fin de la parole de l'agent avant de raccrocher.")
                await current_speech.done()
        except Exception as e:
             logger.error(f"Erreur lors de l'attente de la fin de la parole: {e}")

        await self.hangup()

    # D'autres outils fonctionnels pourraient être ajoutés ici si Pam doit effectuer des actions
    # @function_tool()
    # async def lookup_invoice(self, ctx: RunContext, invoice_number: str): ...

# --- Point d'Entrée de l'Agent ---
async def entrypoint(ctx: JobContext):
    logger.info(f"Entrée dans entrypoint pour le job {ctx.job.id} dans la room {ctx.room.name}")

    # Connexion à la room LiveKit
    try:
        await ctx.connect()
        logger.info(f"Connexion établie à la room {ctx.room.name}")
    except Exception as e:
        logger.critical(f"Erreur critique : Impossible de se connecter à la room {ctx.room.name}: {e}")
        return # Arrêter si la connexion échoue

    # --- Extraction des Métadonnées ---
    logger.info(f"Métadonnées brutes du job: {ctx.job.metadata}")

    first_name = "Client estimé" # Valeur par défaut
    last_name = ""
    phone_number = None
    dial_info = {} # Initialiser dial_info

    try:
        # Utiliser les métadonnées du job en priorité, sinon fallback sur la variable d'environnement
        metadata_str = ctx.job.metadata or os.getenv("LK_JOB_METADATA", "{}")
        if metadata_str and metadata_str.strip() and metadata_str != "{}":
            dial_info = json.loads(metadata_str)
            logger.info(f"dial_info décodé des métadonnées: {dial_info}")
            first_name = dial_info.get("firstName", first_name)
            last_name = dial_info.get("lastName", last_name)
            phone_number = dial_info.get("phoneNumber")
            # S'assurer que 'transfer_to' est bien dans dial_info s'il existe
            if "transfer_to" in dial_info:
                 logger.info(f"Numéro de transfert trouvé dans les métadonnées: {dial_info['transfer_to']}")
        else:
             logger.warning("Aucune métadonnée trouvée dans le job ou LK_JOB_METADATA.")

    except json.JSONDecodeError as e:
        logger.error(f"Erreur lors du décodage des métadonnées JSON: {e}")
        # Utiliser une variable temporaire pour éviter l'erreur de syntaxe f-string
        raw_metadata_content = ctx.job.metadata or os.getenv("LK_JOB_METADATA", "{}")
        logger.error(f"Contenu brut des métadonnées: {raw_metadata_content}")
        dial_info = {} # Assurer que dial_info est un dict vide en cas d'erreur

    # Déterminer le numéro de téléphone final (Métadonnées > Variable d'env PHONE_NUMBER)
    if not phone_number:
        phone_number_env = os.getenv("PHONE_NUMBER")
        if phone_number_env:
            logger.info(f"Numéro de téléphone récupéré depuis la variable d'env PHONE_NUMBER: {phone_number_env}")
            phone_number = phone_number_env
        else:
            logger.critical("Numéro de téléphone manquant dans les métadonnées ET dans la variable d'env PHONE_NUMBER. Impossible d'appeler.")
            ctx.shutdown() # Utiliser shutdown pour signaler l'erreur au worker
            return # Arrêter l'exécution

    # Mettre à jour dial_info avec les informations finales (sera passé à l'agent)
    dial_info["phone_number"] = phone_number
    dial_info["firstName"] = first_name
    dial_info["lastName"] = last_name
    # dial_info peut aussi contenir 'transfer_to' s'il était dans les métadonnées

    logger.info(f"Infos finales pour l'appel : Nom={first_name}, Tel={phone_number}, Autres Infos={dial_info}")

    # --- Configuration de l'Agent et de la Session ---
    agent = OutboundCaller(
        name=first_name,
        dial_info=dial_info,
    )

    logger.info("Configuration de la session AgentSession avec les plugins...")
    try:
        session = AgentSession(
            agent=agent, # Passer l'instance de l'agent
            room=ctx.room, # Passer la room connectée
            vad=silero.VAD.load(),
            stt=deepgram.STT(language="fr", model="nova-2"),
            tts=cartesia.TTS(
                model="sonic-2", # Utiliser le modèle Cartesia qui fonctionne
                voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9" # ID de voix Cartesia
            ),
            llm=openai.LLM(model="gpt-4o-mini"),
        )
    except Exception as e:
        logger.critical(f"Erreur critique lors de l'initialisation des plugins ou AgentSession: {e}")
        ctx.shutdown()
        return

    # Démarrer la session agent en arrière-plan pour gérer l'interaction
    logger.info("Démarrage de la session agent en arrière-plan...")
    session_task = asyncio.create_task(session.start()) # start() gère maintenant l'agent et la room

    # --- Démarrage de l'Appel Sortant SIP ---
    outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
    sip_from_number = os.getenv("SIP_FROM_NUMBER", "") # Numéro présenté (optionnel, dépend du trunk)

    logger.info(f"Tentative d'appel SIP vers {phone_number} via trunk {outbound_trunk_id}")

    if not outbound_trunk_id:
        logger.critical("Variable d'environnement SIP_OUTBOUND_TRUNK_ID non définie.")
        session_task.cancel() # Annuler la session avant de quitter
        ctx.shutdown()
        return

    try:
        logger.info(f"Exécution de create_sip_participant pour {phone_number}")
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity="phone_user", # Identité pour le participant appelé
                wait_until_answered=True,
                # Les paramètres sip_from et caller_id ne sont pas supportés par toutes les versions/configs
                # S'assurer que le trunk est configuré pour utiliser le bon numéro sortant
            )
        )
        logger.info(f"Appel SIP répondu pour {phone_number}. Attente de la connexion du participant 'phone_user'.")

        # Attendre que le participant rejoigne la room (sans timeout explicite si non supporté)
        participant = await ctx.wait_for_participant(identity="phone_user")
        logger.info(f"Participant 'phone_user' ({participant.sid}) connecté à la room {ctx.room.name}.")
        agent.set_participant(participant) # Informer l'agent du participant

    except api.TwirpError as e:
        logger.error(f"Erreur Twirp lors de l'appel SIP: {e.code} {e.message}, SIP Status: {e.metadata.get('sip_status_code')} {e.metadata.get('sip_status')}")
        session_task.cancel()
        ctx.shutdown()
    except asyncio.TimeoutError: # Peut arriver si wait_for_participant avait un timeout caché
         logger.error("Timeout lors de l'attente du participant 'phone_user'.")
         session_task.cancel()
         ctx.shutdown()
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'appel SIP ou attente participant: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        session_task.cancel()
        ctx.shutdown()
        return # Sortir en cas d'erreur critique

    # --- L'Agent Gère l'Appel ---
    logger.info("Appel SIP connecté et participant joint. La session agent est active.")

    # Le point d'entrée peut se terminer ici. La session_task et le worker LiveKit
    # maintiendront la connexion et géreront la fin de l'appel via l'agent.
    # L'appel à ctx.run() n'est pas nécessaire/standard ici.

# --- Bloc Principal d'Exécution ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO) # Config logging de base pour le worker

    logger.info("Configuration et démarrage du worker LiveKit Agent (outbound-caller)...")

    # Définir les options du worker, en pointant vers la fonction entrypoint
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name="outbound-caller", # Nom utilisé pour dispatcher les jobs
    )

    # Utiliser le lanceur standard de LiveKit pour les agents
    try:
        cli.run_app(worker_options) # Gère la connexion à LiveKit et la boucle de jobs
    except Exception as e:
        logger.critical(f"Échec critique lors du lancement du worker agent: {str(e)}")
        import traceback
        logger.critical(traceback.format_exc())
        sys.exit(1) # Sortir avec un code d'erreur 
