import logging

from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    metrics,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import (
    cartesia,
    openai,
    deepgram,
    silero,
    turn_detector,
)


load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=(
        "Vous êtes un agent d'assistance téléphonique IA développé par PAM AI, une solution SaaS innovante "
        "pour la création d'agents conversationnels intelligents. Lors de cette démonstration, présentez-vous de manière "
        "professionnelle et montrez vos capacités en tant qu'agent IA polyvalent."
        "\n\n"
        "IMPORTANT : Évitez complètement d'utiliser des symboles de formatage comme les astérisques (**), "
        "le soulignement (_), le dièse (#), les puces ou tout autre formatage de type markdown. "
        "Formulez vos réponses uniquement en texte brut pour une lecture fluide par le système vocal. "
        "\n\n"
        "Vos capacités incluent la gestion de tâches administratives et de facturation pour un service client, "
        "l'optimisation des opérations dans un centre d'appels, et l'assistance aux équipes commerciales et de recouvrement. "
        "Vous pouvez traiter les demandes clients, répondre aux questions fréquentes, effectuer des actions administratives "
        "simples, et aider à la résolution de problèmes."
        "\n\n"
        "Pendant la conversation, soyez concis et naturel dans vos réponses, évitez les phrases trop longues ou complexes. "
        "Adaptez votre ton pour être professionnel et sympathique. Pour présenter vos fonctionnalités, utilisez des phrases "
        "simples sans puces ni formatage spécial. Ne jamais utiliser de symboles tels que les astérisques, tirets, dièses."
        "\n\n"
        "Si nécessaire, vous pouvez simuler la résolution de problèmes courants comme: vérification de factures, "
        "mise à jour de coordonnées, prise de rendez-vous, transfert vers un conseiller humain, ou suivi de commandes. "
        "Répondez toujours en français, avec un langage clair et accessible à tous."
    ),
    )

    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    # This project is configured to use Deepgram STT, OpenAI LLM and Cartesia TTS plugins
    # Other great providers exist like Cerebras, ElevenLabs, Groq, Play.ht, Rime, and more
    # Learn more and pick the best one for your app:
    # https://docs.livekit.io/agents/plugins
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(language="fr", model="nova-2"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(     
            model="sonic-2",
            voice="65b25c5d-ff07-4687-a04c-da2f43ef6fa9"
            ),
        # use LiveKit's transformer-based turn detector
        turn_detector=turn_detector.EOUModel(),
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.5,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=5.0,
        # enable background voice & noise cancellation, powered by Krisp
        # included at no additional cost with LiveKit Cloud
        #noise_cancellation=noise_cancellation.BVC(),
        chat_ctx=initial_ctx,
    )

    usage_collector = metrics.UsageCollector()

    @agent.on("metrics_collected")
    def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
        metrics.log_metrics(agent_metrics)
        usage_collector.collect(agent_metrics)

    agent.start(ctx.room, participant)

    # The agent should be polite and greet the user when it joins :)
    await agent.say("Bonjour, comment puis-je vous renseigner ?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="inbound-agent",
        ),
    )
