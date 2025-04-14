from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv
import json
import os
import sys
import locale
from typing import Any
import uuid
from dataclasses import dataclass
import random

# Forcer l'encodage UTF-8 pour Windows
if sys.platform == 'win32':
    # Tentative de définir le locale en français UTF-8
    try:
        locale.setlocale(locale.LC_ALL, 'fr_FR.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, 'French_France.1252')
        except locale.Error:
            pass

# Configuration du logger pour gérer les accents
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

# Créer un gestionnaire de flux qui gère l'encodage UTF-8 sans utiliser buffer
handler = logging.StreamHandler(sys.stderr)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Logs au démarrage du script pour débogage
logger.info(f"Agent script démarre, args: {sys.argv}")
logger.info(f"Python version: {sys.version}")
logger.info(f"Répertoire courant: {os.getcwd()}")
logger.info(f"Encodage par défaut: {sys.getdefaultencoding()}")
logger.info(f"Locale système: {locale.getlocale()}")

# Charger le fichier .env spécifié par la variable d'environnement ou .env.local par défaut
dotenv_file = os.getenv("DOTENV_FILE", ".env.local")
logger.info(f"Chargement du fichier .env: {dotenv_file}")
load_dotenv(dotenv_path=dotenv_file, encoding='utf-8')

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
patient_name = os.getenv("PATIENT_NAME", "Jayden")
appointment_time = os.getenv("APPOINTMENT_TIME", "next Tuesday at 3pm")
room_name = os.getenv("LK_ROOM_NAME", "")
job_metadata = os.getenv("LK_JOB_METADATA", "{}")

# Ajout de logs pour débugger
logger.info(f"SIP_OUTBOUND_TRUNK_ID: {outbound_trunk_id}")
logger.info(f"PATIENT_NAME: {patient_name}")
logger.info(f"APPOINTMENT_TIME: {appointment_time}")
logger.info(f"LK_ROOM_NAME: {room_name}")
logger.info(f"LK_JOB_METADATA: {job_metadata}")
logger.info(f"LIVEKIT_URL: {os.getenv('LIVEKIT_URL', 'non défini')}")
logger.info(f"LIVEKIT_API_KEY présent: {'Oui' if os.getenv('LIVEKIT_API_KEY') else 'Non'}")

# Importer les modules après la configuration du logger
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

class OutboundCaller(Agent):
    def __init__(
        self,
        *,
        name: str, # Keep name parameter even if not used in the new prompt, in case entrypoint/metadata still provides it
        # appointment_time: str, # No longer needed for the demo prompt
        dial_info: dict[str, Any],
    ):
        # Replaced system prompt with the one from inbound/agent.py
        super().__init__(
            instructions=(
                "Vous êtes Pam, un agent d'assistance téléphonique IA développé par PAM AI, une solution SaaS permettant la création d'agent téléphonique IA. "
                "Lors de cette démonstration, présentez-vous de manière "
                "professionnelle et montrez vos capacités en tant qu'agent IA polyvalent.\n\n"
                "IMPORTANT : Évitez complètement d'utiliser des symboles de formatage comme les astérisques (**), "
                "le soulignement (_), le dièse (#), les puces ou tout autre formatage de type markdown. "
                "Formulez vos réponses uniquement en texte brut pour une lecture fluide par le système vocal. \n\n"
                "Vos capacités incluent la gestion de tâches administratives et de facturation pour un service client, "
                "l'optimisation des opérations dans un centre d'appels, et l'assistance aux équipes commerciales et de recouvrement. "
                "Vous pouvez traiter les demandes clients, répondre aux questions fréquentes, effectuer des actions administratives "
                "simples, et aider à la résolution de problèmes.\n\n"
                "Pendant la conversation, soyez concis et naturel dans vos réponses, évitez les phrases trop longues ou complexes. "
                "Adaptez votre ton pour être professionnel et sympathique. Pour présenter vos fonctionnalités, utilisez des phrases "
                "simples sans puces ni formatage spécial. Ne jamais utiliser de symboles tels que les astérisques, tirets, dièses.\n\n"
                "Si nécessaire, vous pouvez simuler la résolution de problèmes courants comme: vérification de factures, "
                "mise à jour de coordonnées, prise de rendez-vous, transfert vers un conseiller humain, ou suivi de commandes. "
                "Répondez toujours en français, avec un langage clair et accessible à tous."
            )
        )
        # keep reference to the participant for transfers
        self.participant: rtc.RemoteParticipant | None = None

        self.dial_info = dial_info
        
        # Updated log message to reflect Pam's role
        logger.info(f"OutboundCaller (Pam Demo Agent) initialisé pour {name}") 
        logger.info(f"dial_info: {dial_info}")

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant

    async def hangup(self):
        """Helper function to hang up the call by deleting the room"""

        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(
                room=job_ctx.room.name,
            )
        )

    @function_tool()
    async def transfer_call(self, ctx: RunContext):
        """Transfer the call to a human agent, called after confirming with the user"""

        transfer_to = self.dial_info["transfer_to"]
        if not transfer_to:
            return "cannot transfer call"

        logger.info(f"transferring call to {transfer_to}")

        # let the message play fully before transferring
        await ctx.session.generate_reply(
            instructions="let the user know you'll be transferring them"
        )

        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=self.participant.identity,
                    transfer_to=f"tel:{transfer_to}",
                )
            )

            logger.info(f"transferred call to {transfer_to}")
        except Exception as e:
            logger.error(f"error transferring call: {e}")
            await ctx.session.generate_reply(
                instructions="there was an error transferring the call."
            )
            await self.hangup()

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call"""
        logger.info(f"ending the call for {self.participant.identity}")

        # let the agent finish speaking
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.done()

        await self.hangup()

    @function_tool()
    async def look_up_availability(
        self,
        ctx: RunContext,
        date: str,
    ):
        """Called when the user asks about alternative appointment availability

        Args:
            date: The date of the appointment to check availability for
        """
        logger.info(
            f"looking up availability for {self.participant.identity} on {date}"
        )
        await asyncio.sleep(3)
        return {
            "available_times": ["1pm", "2pm", "3pm"],
        }

    @function_tool()
    async def confirm_appointment(
        self,
        ctx: RunContext,
        date: str,
        time: str,
    ):
        """Called when the user confirms their appointment on a specific date.
        Use this tool only when they are certain about the date and time.

        Args:
            date: The date of the appointment
            time: The time of the appointment
        """
        logger.info(
            f"confirming appointment for {self.participant.identity} on {date} at {time}"
        )
        return "reservation confirmed"

    @function_tool()
    async def detected_answering_machine(self, ctx: RunContext):
        """Called when the call reaches voicemail. Use this tool AFTER you hear the voicemail greeting"""
        logger.info(f"detected answering machine for {self.participant.identity}")
        await self.hangup()


async def entrypoint(ctx: JobContext):
    # Reference global variables if they are genuinely needed globally or managed outside
    # Prefer passing necessary configs explicitly if possible
    global outbound_trunk_id # appointment_time is no longer directly needed by the agent prompt

    logger.info(f"Entrée dans la fonction entrypoint pour le job {ctx.job.id}")
    
    # Connect to the room first
    try:
        await ctx.connect()
        logger.info(f"Connexion établie à la room {ctx.room.name}")
    except Exception as e:
        logger.error(f"Erreur de connexion à la room {ctx.room.name}: {e}")
        return # Cannot proceed without connection

    # -- Start Metadata Extraction --
    logger.info(f"Métadonnées du job: {ctx.job.metadata}")

    first_name = "Valued Customer" # Default value
    last_name = ""
    phone_number = None
    dial_info = {} # Initialize dial_info

    try:
        # Use job metadata first, fallback to env var LK_JOB_METADATA
        metadata_str = ctx.job.metadata or os.getenv("LK_JOB_METADATA", "{}")
        if metadata_str and metadata_str != "{}":
            dial_info = json.loads(metadata_str)
            logger.info(f"dial_info parsed from metadata: {dial_info}")
            first_name = dial_info.get("firstName", first_name)
            last_name = dial_info.get("lastName", last_name)
            phone_number = dial_info.get("phoneNumber")
            # Keep transfer_to if present, ensure it's in dial_info for the agent
            if "transfer_to" in dial_info:
                 logger.info(f"Transfer number found in metadata: {dial_info['transfer_to']}")
            else:
                 # If not in metadata, maybe check environment? Or leave it empty.
                 # dial_info["transfer_to"] = os.getenv("DEFAULT_TRANSFER_NUMBER") 
                 pass # Assuming transfer_to is optional unless specified
        else:
             logger.warning("No metadata found in job context or environment variable LK_JOB_METADATA.")

    except json.JSONDecodeError as e:
        logger.error(f"Erreur lors du décodage des métadonnées JSON: {e}")
        logger.error(f"Contenu brut des métadonnées: {ctx.job.metadata or os.getenv("LK_JOB_METADATA", "{}")}")
        # Keep dial_info as {}, defaults for names/phone will be used

    # Determine phone number: Parsed Metadata > PHONE_NUMBER env var
    if not phone_number:
        phone_number_env = os.getenv("PHONE_NUMBER")
        if phone_number_env:
            logger.info(f"Phone number taken from PHONE_NUMBER env var: {phone_number_env}")
            phone_number = phone_number_env
        else:
            logger.error("Phone number is missing in metadata and PHONE_NUMBER env var. Cannot dial.")
            await ctx.disconnect() # Disconnect before returning
            return # Stop processing if no number

    # Update dial_info with the final phone number and names for the agent
    dial_info["phone_number"] = phone_number
    dial_info["firstName"] = first_name
    dial_info["lastName"] = last_name
    # -- End Metadata Extraction --

    logger.info(f"Final dial info for agent: {dial_info}")
    logger.info(f"Agent will use name: {first_name}")
    logger.info(f"Dialing number: {phone_number}")

    # -- Agent and Session Setup --
    # Create the agent instance *inside* entrypoint using extracted data
    # appointment_time is removed from agent creation as it's not in the new prompt
    agent = OutboundCaller(
        name=first_name, 
        # appointment_time=os.getenv("APPOINTMENT_TIME", "next Tuesday at 3pm"), # Removed
        dial_info=dial_info, 
    )

    # Setup plugins and session (Restored Logic)
    logger.info(f"Création de l'AgentSession avec les plugins")
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(language="fr", model="nova-2"),
        # Ensure Cartesia model and voice ID are correct
        tts=cartesia.TTS(model="sonic-2", # Reverted to sonic-2 based on original script
             voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9"), 
        llm=openai.LLM(model="gpt-4o-mini"),
    )

    # Start the session task to handle interactions
    logger.info(f"Démarrage de la session agent en arrière-plan")
    session_task = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            # No specific participant needed here, agent will interact with joined participants
            # room_input_options=RoomInputOptions(), # Use default options
        )
    )
    # -- End Agent and Session Setup --

    # -- Start Outbound SIP Call --
    current_outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID") # Get current value
    logger.info(f"Attempting SIP dial: {phone_number} via trunk {current_outbound_trunk_id}")

    if not current_outbound_trunk_id:
        logger.error("SIP_OUTBOUND_TRUNK_ID n'est pas défini dans l'environnement.")
        await ctx.disconnect()
        session_task.cancel() 
        return

    try:
        logger.info(f"Executing create_sip_participant for {phone_number}")
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=current_outbound_trunk_id,
                sip_call_to=phone_number, 
                participant_identity="phone_user",
                wait_until_answered=True, 
                # caller_id=os.getenv("SIP_CALLER_ID", ""), # Removed unsupported parameter
            )
        )
        logger.info(f"SIP call answered for {phone_number}. Waiting for participant 'phone_user' to join.")

        # Wait for the participant corresponding to the SIP call to join the room
        participant = await ctx.wait_for_participant(identity="phone_user")
        logger.info(f"Participant 'phone_user' ({participant.sid}) connected to room {ctx.room.name}.")
        agent.set_participant(participant) # Link participant to agent for context (e.g., transfer)

    except api.TwirpError as e:
        logger.error(
            f"Erreur Twirp during SIP call: {e.code} {e.message}, "
            f"SIP Status: {e.metadata.get('sip_status_code')} {e.metadata.get('sip_status')}"
        )
        ctx.shutdown()
        session_task.cancel()
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for participant 'phone_user' to join after SIP call answered.")
        ctx.shutdown()
        session_task.cancel()
    except Exception as e:
        logger.error(f"Unexpected error during SIP call or participant wait: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        ctx.shutdown()
        session_task.cancel()
        return # Exit on critical error
    # -- End Outbound SIP Call --

    # If SIP call successful and participant joined, let the agent session run
    logger.info("SIP call connected, participant joined. Agent session is active.")
    
    # The entrypoint completes here, the background session_task handles the interaction.


if __name__ == "__main__":
    # Basic logging config for the worker process
    logging.basicConfig(level=logging.INFO)
    
    logger.info("Configuring and starting LiveKit Agent worker (outbound-caller)")

    # Define the worker options, primarily setting the entrypoint function
    # The agent name allows LiveKit Server to dispatch jobs to this worker type
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name="outbound-caller",
        # Optional: Define resource limits, health checks, etc.
    )

    # Use the standard LiveKit agent CLI runner
    # run_app handles worker registration with LiveKit Server and job processing loop
    try:
        cli.run_app(worker_options)
    except Exception as e:
        logger.critical(f"Failed to run the agent worker: {str(e)}")
        import traceback
        logger.critical(traceback.format_exc())
        sys.exit(1) # Exit with error code if runner fails critically

