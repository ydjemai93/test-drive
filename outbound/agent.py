from __future__ import annotations

import asyncio
import logging
import json
import os
import sys
import locale
from typing import Any

# Setup logging first
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stderr)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
# Avoid adding multiple handlers if the module is reloaded
if not logger.hasHandlers():
    logger.addHandler(handler)

# Force UTF-8 encoding for Windows (optional, depending on environment)
if sys.platform == 'win32':
    try:
        locale.setlocale(locale.LC_ALL, 'fr_FR.UTF-8')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, 'French_France.1252')
        except locale.Error:
            logger.warning("Could not set French locale for Windows.")
            pass


# Import LiveKit modules after logger setup
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

# --- Agent Definition ---
class OutboundCaller(Agent):
    def __init__(
        self,
        *,
        name: str, # Keep name parameter even if not used in the new prompt
        dial_info: dict[str, Any],
    ):
        # System Prompt for "Pam" agent
        super().__init__(
            instructions=(
                "Vous êtes Pam, un agent d'assistance téléphonique IA développé par PAM AI, une solution SaaS permettant la création d'agent téléphonique IA. "
                "pour la création d'agents conversationnels intelligents. Lors de cette démonstration, présentez-vous de manière "
                "professionnelle et montrez vos capacités en tant qu'agent IA polyvalent.\\n\\n"
                "IMPORTANT : Évitez complètement d'utiliser des symboles de formatage comme les astérisques (**), "
                "le soulignement (_), le dièse (#), les puces ou tout autre formatage de type markdown. "
                "Formulez vos réponses uniquement en texte brut pour une lecture fluide par le système vocal. \\n\\n"
                "Vos capacités incluent la gestion de tâches administratives et de facturation pour un service client, "
                "l'optimisation des opérations dans un centre d'appels, et l'assistance aux équipes commerciales et de recouvrement. "
                "Vous pouvez traiter les demandes clients, répondre aux questions fréquentes, effectuer des actions administratives "
                "simples, et aider à la résolution de problèmes.\\n\\n"
                "Le nom de l'interlocuteur est {name}.\\n\\n"
                "Pendant la conversation, soyez concis et naturel dans vos réponses, évitez les phrases trop longues ou complexes. "
                "Adaptez votre ton pour être professionnel et sympathique. Pour présenter vos fonctionnalités, utilisez des phrases "
                "simples sans puces ni formatage spécial. Ne jamais utiliser de symboles tels que les astérisques, tirets, dièses.\\n\\n"
                "Si nécessaire, vous pouvez simuler la résolution de problèmes courants comme: vérification de factures, "
                "mise à jour de coordonnées, prise de rendez-vous, transfert vers un conseiller humain, ou suivi de commandes. "
                "Répondez toujours en français, avec un langage clair et accessible à tous."
            )
        )
        # Store participant reference for transfers etc.
        self.participant: rtc.RemoteParticipant | None = None
        self.dial_info = dial_info

        logger.info(f"OutboundCaller (Pam Demo Agent) initialized for {name}")
        logger.info(f"dial_info provided: {dial_info}")

    def set_participant(self, participant: rtc.RemoteParticipant):
        """Stores the remote participant once connected."""
        self.participant = participant
        logger.info(f"Participant {participant.identity} registered for the agent.")

    async def hangup(self):
        """Utility function to hang up by deleting the room."""
        logger.warning("Hangup requested (deleting room).")
        try:
            job_ctx = get_job_context()
            await job_ctx.api.room.delete_room(
                api.DeleteRoomRequest(room=job_ctx.room.name)
            )
            logger.info(f"Room {job_ctx.room.name} deleted.")
        except Exception as e:
            logger.error(f"Error deleting room: {e}")

    # --- Agent Function Tools ---
    @function_tool()
    async def transfer_call(self, ctx: RunContext):
        """Transfers the call to a human agent, called after user confirmation."""
        transfer_to = self.dial_info.get("transfer_to") # Use .get to avoid KeyError
        if not transfer_to:
            logger.warning("Transfer number not found in dial_info.")
            return "Je suis désolé, je ne peux pas transférer l'appel pour le moment."

        if not self.participant:
            logger.error("Attempting transfer without a registered participant.")
            return "Erreur technique lors de la tentative de transfert."

        logger.info(f"Attempting to transfer participant {self.participant.identity} to {transfer_to}")

        # Let the agent inform the user before transferring
        try:
            await ctx.session.generate_reply(
                instructions="Informez l'utilisateur que vous allez le transférer maintenant."
            )
        except Exception as e:
             logger.error(f"Error generating pre-transfer reply: {e}")
             # Continue with transfer if possible

        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=self.participant.identity,
                    transfer_to=f"tel:{transfer_to}", # Assume transfer_to is a valid number
                )
            )
            logger.info(f"Call successfully transferred to {transfer_to}. Agent should disconnect.")
        except Exception as e:
            logger.error(f"Error during SIP transfer: {e}")
            try:
                await ctx.session.generate_reply(
                    instructions="Informez l'utilisateur qu'une erreur est survenue lors du transfert."
                )
            except Exception as inner_e:
                logger.error(f"Error generating transfer error message: {inner_e}")
            await self.hangup() # Hang up on transfer failure

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call."""
        if not self.participant:
             logger.warning("end_call requested but no participant registered.")
        else:
             logger.info(f"End call requested for {self.participant.identity}")

        # Let the agent finish speaking before hanging up
        try:
            current_speech = ctx.session.current_speech
            if current_speech:
                logger.info("Waiting for agent speech to finish before hangup.")
                await current_speech.done()
        except Exception as e:
             logger.error(f"Error waiting for speech completion: {e}")

        await self.hangup()

    # Other function tools can be added here if Pam needs to perform actions
    # @function_tool()
    # async def lookup_invoice(self, ctx: RunContext, invoice_number: str): ...

# --- Agent Entrypoint ---
async def entrypoint(ctx: JobContext):
    logger.info(f"Entering entrypoint for job {ctx.job.id} in room {ctx.room.name}")

    # Connect to LiveKit room
    try:
        await ctx.connect()
        logger.info(f"Connection established to room {ctx.room.name}")
    except Exception as e:
        logger.critical(f"Critical error: Could not connect to room {ctx.room.name}: {e}")
        return # Stop if connection fails

    # --- Metadata Extraction ---
    logger.info(f"Raw job metadata: {ctx.job.metadata}")

    first_name = "Client estimé" # Default value
    last_name = ""
    phone_number = None
    dial_info = {} # Initialize dial_info

    try:
        # Use job metadata first, fallback to environment variable
        metadata_str = ctx.job.metadata or os.getenv("LK_JOB_METADATA", "{}")
        if metadata_str and metadata_str.strip() and metadata_str != "{}":
            dial_info = json.loads(metadata_str)
            logger.info(f"dial_info decoded from metadata: {dial_info}")
            first_name = dial_info.get("firstName", first_name)
            last_name = dial_info.get("lastName", last_name)
            phone_number = dial_info.get("phoneNumber")
            # Ensure 'transfer_to' is in dial_info if it exists
            if "transfer_to" in dial_info:
                 logger.info(f"Transfer number found in metadata: {dial_info['transfer_to']}")
        else:
             logger.warning("No metadata found in job or LK_JOB_METADATA env var.")
             dial_info = {} # Ensure dial_info is dict if no metadata

    except json.JSONDecodeError as e:
        logger.error(f"Error decoding metadata JSON: {e}")
        # Use temporary variable to avoid f-string syntax error
        raw_metadata_content = ctx.job.metadata or os.getenv("LK_JOB_METADATA", "{}")
        logger.error(f"Raw metadata content: {raw_metadata_content}")
        dial_info = {} # Ensure dial_info is dict on error

    # Determine final phone number (Metadata > PHONE_NUMBER env var)
    if not phone_number:
        phone_number_env = os.getenv("PHONE_NUMBER")
        if phone_number_env:
            logger.info(f"Phone number retrieved from PHONE_NUMBER env var: {phone_number_env}")
            phone_number = phone_number_env
        else:
            logger.critical("Phone number missing in metadata AND PHONE_NUMBER env var. Cannot dial.")
            ctx.shutdown() # Use shutdown to signal error to worker
            return # Stop execution

    # Update dial_info with final information (will be passed to agent)
    dial_info["phone_number"] = phone_number
    dial_info["firstName"] = first_name
    dial_info["lastName"] = last_name
    # dial_info might also contain 'transfer_to' if it was in metadata

    logger.info(f"Final call info: Name={first_name}, Tel={phone_number}, Other Info={dial_info}")

    # --- Agent and Session Setup ---
    agent = OutboundCaller(
        name=first_name,
        dial_info=dial_info,
    )

    logger.info("Configuring AgentSession with plugins...")
    try:
        # Initialize AgentSession only with plugins
        session = AgentSession(
            # agent=agent, # Removed from here
            # room=ctx.room, # Removed from here
            vad=silero.VAD.load(),
            stt=deepgram.STT(language="fr", model="nova-2"),
            tts=cartesia.TTS(
                model="sonic-2", # Use working Cartesia model
                voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9" # Cartesia voice ID
            ),
            llm=openai.LLM(model="gpt-4o-mini"),
        )
    except Exception as e:
        logger.critical(f"Critical error initializing plugins or AgentSession: {e}")
        ctx.shutdown()
        return

    # Start the agent session in the background to handle interaction
    logger.info("Starting agent session in background...")
    # Pass 'agent' and 'room' to session.start()
    session_task = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room
            # room_input_options=RoomInputOptions(), # Optional
        )
    )

    # --- Start Outbound SIP Call ---
    outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
    sip_from_number = os.getenv("SIP_FROM_NUMBER", "") # Presented number (optional, depends on trunk)

    logger.info(f"Attempting SIP call to {phone_number} via trunk {outbound_trunk_id}")

    if not outbound_trunk_id:
        logger.critical("Environment variable SIP_OUTBOUND_TRUNK_ID not set.")
        session_task.cancel() # Cancel session before exiting
        ctx.shutdown()
        return

    try:
        logger.info(f"Executing create_sip_participant for {phone_number}")
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity="phone_user", # Identity for the called participant
                wait_until_answered=True,
                # sip_from and caller_id parameters are not supported by all versions/configs
                # Ensure trunk is configured for correct outbound number
            )
        )
        logger.info(f"SIP call answered for {phone_number}. Waiting for participant 'phone_user' to connect.")

        # Wait for the participant to join the room (no explicit timeout if not supported)
        participant = await ctx.wait_for_participant(identity="phone_user")
        logger.info(f"Participant 'phone_user' ({participant.sid}) connected to room {ctx.room.name}.")
        agent.set_participant(participant) # Inform agent about the participant

    except api.TwirpError as e:
        logger.error(f"Twirp error during SIP call: {e.code} {e.message}, SIP Status: {e.metadata.get('sip_status_code')} {e.metadata.get('sip_status')}")
        session_task.cancel()
        ctx.shutdown()
    except asyncio.TimeoutError: # Can happen if wait_for_participant had a hidden timeout
         logger.error("Timeout waiting for participant 'phone_user'.")
         session_task.cancel()
         ctx.shutdown()
    except Exception as e:
        logger.error(f"Unexpected error during SIP call or participant wait: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        session_task.cancel()
        ctx.shutdown()
        return # Exit on critical error

    # --- Agent Handles the Call ---
    logger.info("SIP call connected and participant joined. Agent session is active.")

    # Entrypoint can end here. The session_task and LiveKit worker
    # will maintain the connection and handle call termination via the agent.
    # ctx.run() is not needed/standard here.

# --- Main Execution Block ---
if __name__ == "__main__":
    # Basic logging config for the worker process already done above
    # logging.basicConfig(level=logging.INFO)

    logger.info("Configuring and starting LiveKit Agent worker (outbound-caller)...")

    # Define worker options, pointing to the entrypoint function
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name="outbound-caller", # Name used for dispatching jobs
    )

    # Use the standard LiveKit agent runner
    try:
        cli.run_app(worker_options) # Handles connection to LiveKit and job loop
    except Exception as e:
        logger.critical(f"Critical failure running agent worker: {str(e)}")
        import traceback
        logger.critical(traceback.format_exc())
        sys.exit(1) # Exit with error code
