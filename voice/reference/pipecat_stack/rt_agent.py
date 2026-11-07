"""
rt_agent.py -- Phase 2: real-time duplex voice on Pipecat (the VAPI replacement).

agent.py (Phase 1) is turn-based: record until silence, then think, then speak,
and the caller cannot interrupt. This is the streaming version: audio flows
both ways continuously, Silero VAD decides when the caller has finished, and
the caller can talk over the agent (barge-in) the way they would on a real call.

Why Pipecat and not the alternatives (decided 2026-10-01):
  - LiveKit Agents needs a LiveKit media server; Pipecat runs in-process and
    already supports the Exotel/Twilio telephony transports Phase 2 targets.
  - Moonshine STT has no Hindi, and these callers speak Hinglish.
  - transcribe.cpp runs Whisper locally but is C++ with no Python binding;
    Groq Whisper is hosted, Hinglish-capable, and ~$0.04 per audio hour.

Nothing is forked from Phase 1: the prompt (deploy_assistant.render), tools
(functions.json), tool handlers, DND list and intent scoring all come from
agent.py's Call, so one edit still changes both agents.

Run (needs the .venv-rt venv; Pipecat is not in the Phase-1 requirements):
    doppler run --project client-acquisition-pipeline --config dev -- \
        .venv-rt/Scripts/python rt_agent.py --lead-name Rohan --plan "Rs 299" --expiry "12 June"
    ... rt_agent.py --selftest      # no mic: TTS -> STT round trip + tool wiring
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import threading
import uuid
import time
import sys
from pathlib import Path

import edge_tts
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (EndFrame, EndTaskFrame, ErrorFrame, TTSAudioRawFrame,
                                   TTSSpeakFrame, UserIdleTimeoutUpdateFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.tts_service import TTSService

from paralang import PROMPT_HINT, SPEAKING_HINT, Analyzer, DeliveryPlanner, aura, orpheus
from paralang.delivery import emotion_for
from paralang.lang import HINDI_VOICE, ReplyRouter
from paralang.silence import SilencePolicy
from paralang.live import LiveFeed, turn_event
from paralang.selfcheck import SelfCheck
from paralang.say import edge_voice_for
from paralang.adapters.pipecat import (AutoLanguageGroqSTT, BackchannelAwareStartStrategy,
                                       ParalangProcessor)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

sys.path.insert(0, str(Path(__file__).parent))
import agent as phase1  # noqa: E402  (prompt, tools, handlers, scoring)

# Longest silence a caller hears before a sentence switches to the fallback voice.
# Aura's first audio measured 1.4-2.5 s (once 4.3 s) from Delhi.
LIVE_FIRST_AUDIO_S = float(os.environ.get("PARALANG_LIVE_FIRST_AUDIO_S", "2.5"))
SAMPLE_RATE = 24000  # Orpheus and edge-tts Neerja both render 24 kHz; one rate end to end


class ParalangTTSService(TTSService):
    """The agent's voice: Deepgram Aura-2 Andromeda by default, edge-tts Neerja
    as the safety net, hi-IN Swara for Devanagari (Neerja is silent on it).

    aura (default, Shaurya 2026-10-15): paralang.aura streams raw 24 kHz PCM.
        Measured from Delhi: first audio 1.4-2.5 s, so live mode caps every read
        at 3 s and a slow sentence is spoken by Neerja instead of dead air.
        Aura cannot act emotion: delivery is the planner's breathing gaps.
    orpheus: Groq, first audio ~300-450 ms, ACTS "[<emotion>] text" chosen from
        the caller's last turn (paralang.delivery.emotion_for).
    edge: Neerja with the planner's rate/pitch/volume knobs.
    PARALANG_ENGINE=orpheus|edge picks another engine; PARALANG_AGENT_VOICE the voice.
    """

    def __init__(self, *, voice: str, rate: str = "+0%", planner: DeliveryPlanner | None = None,
                 cues_fn=None, emotion: str | None = "warm", engine: str | None = None,
                 orpheus_voice: str | None = None, caller_text_fn=None, **kwargs):
        super().__init__(sample_rate=SAMPLE_RATE, push_start_frame=True,
                         push_stop_frames=True, **kwargs)
        self._voice = voice                      # edge voice (fallback, or engine=edge)
        self._rate = rate
        self._engine = (engine or os.environ.get("PARALANG_ENGINE") or "aura").lower()
        default_voice = "aura-2-andromeda-en" if self._engine == "aura" else "hannah"
        self._engine_voice = orpheus_voice or os.environ.get("PARALANG_AGENT_VOICE", default_voice)
        # paralang delivery: breathing gaps + (edge) rate/pitch/volume, reacting
        # to the caller's latest cues (cues_fn). None = flat, as before.
        self._planner = planner
        self._cues_fn = cues_fn or (lambda: [])
        # on-the-fly EN<->HI: Andromeda garbles Hindi (paralang samples/hindi_ab), so a
        # Hindi sentence is spoken by Swara; caller_text_fn lets short openers mirror the caller
        self._router = ReplyRouter()
        self._caller_text_fn = caller_text_fn or (lambda: "")
        self.lang_counts = {"en": 0, "hi": 0}
        self._emotion = emotion  # base colour (paralang.EMOTIONS); caller cues steer it
        self.engine_counts = {"aura": 0, "orpheus": 0, "edge": 0}
        self.selfcheck = None          # paralang.selfcheck.SelfCheck, set by build_task
        self._gap_fn = lambda: None
        self._reply: dict | None = None
        if self._engine == "aura":
            # pay Deepgram's TCP + TLS handshake (1-9 s on a slow line) now, not on sentence 1
            threading.Thread(target=aura.prewarm, args=(2,), daemon=True, name="aura-prewarm").start()

    def can_generate_metrics(self) -> bool:
        return True

    async def _synth_pcm(self, text: str, prosody: dict | None = None,
                         voice: str | None = None) -> bytes:
        """edge-tts -> PCM (fallback path, and engine=edge)."""
        mp3 = bytearray()
        kw = prosody or {"rate": self._rate}
        async for chunk in edge_tts.Communicate(text, voice or edge_voice_for(text, self._voice),
                                                **kw).stream():
            if chunk.get("type") == "audio":
                mp3.extend(chunk["data"])
        if not mp3:
            raise RuntimeError("edge-tts returned no audio")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", "pipe:0",
            "-f", "s16le", "-ac", "1", "-ar", str(self.sample_rate), "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        pcm, err = await asyncio.wait_for(proc.communicate(bytes(mp3)), timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg decode failed: {err.decode(errors='replace')[:200]}")
        return pcm

    async def _engine_chunks(self, text: str):
        """Aura/Orpheus PCM chunks as they arrive (blocking HTTP runs in a thread)."""
        engine = aura if self._engine == "aura" else orpheus
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def work():
            try:
                for chunk in engine.stream(text, self._engine_voice, live=True):
                    loop.call_soon_threadsafe(q.put_nowait, chunk)
                loop.call_soon_threadsafe(q.put_nowait, None)
            except Exception as e:  # noqa: BLE001 - re-raised on the event loop
                loop.call_soon_threadsafe(q.put_nowait, e)

        threading.Thread(target=work, daemon=True, name="tts-stream").start()
        first = True
        while True:
            if first:
                # WALL-CLOCK cap on dead air: socket timeouts are per read, and
                # connect + TLS alone took 4.3 s to Deepgram once (2026-10-15)
                try:
                    item = await asyncio.wait_for(q.get(), LIVE_FIRST_AUDIO_S)
                except asyncio.TimeoutError:
                    raise aura.AuraError(f"no audio within {LIVE_FIRST_AUDIO_S:.1f}s") from None
                first = False
            else:
                item = await q.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def _frames(self, pcm: bytes, context_id: str):
        step = self.sample_rate * 2 // 10  # 100 ms of 16-bit mono per frame
        for i in range(0, len(pcm), step):
            yield TTSAudioRawFrame(pcm[i:i + step], self.sample_rate, 1, context_id=context_id)

    def _selfcheck_track(self, context_id: str, text: str) -> None:
        """v0.3 #13: start collecting a new reply; check the finished one off-loop."""
        if self.selfcheck is None:
            return
        if self._reply is not None and self._reply["id"] != context_id:
            self.flush_selfcheck(background=True)
        if self._reply is None:
            self._reply = {"id": context_id, "pcm": bytearray(), "text": [],
                           "gap": self._gap_fn()}
        self._reply["text"].append(text)

    def flush_selfcheck(self, background: bool = False) -> None:
        r, self._reply = self._reply, None
        if self.selfcheck is None or not r or len(r["pcm"]) < self.sample_rate:   # < 0.5 s: skip
            return
        args = (bytes(r["pcm"]), self.sample_rate, " ".join(r["text"]), r["gap"])
        if background:
            asyncio.get_running_loop().run_in_executor(None, self.selfcheck.observe_reply, *args)
        else:
            self.selfcheck.observe_reply(*args)

    def _keep(self, pcm: bytes) -> None:
        if self._reply is not None:
            self._reply["pcm"].extend(pcm)

    async def run_tts(self, text: str, context_id: str):
        try:
            await self.start_tts_usage_metrics(text)
            self._selfcheck_track(context_id, text)
            cues = self._cues_fn()
            lang = self._router.lang(text, context_id, self._caller_text_fn())
            self.lang_counts[lang] += 1
            p = (self._planner.plan(text, cues, context_id, emotion=self._emotion)
                 if self._planner else None)
            # a breath between thoughts; real silence, so barge-in still works
            gap = b"\x00\x00" * (self.sample_rate * p.pause_before_ms // 1000) if p and p.pause_before_ms else b""

            if lang == "en" and self._engine in ("aura", "orpheus") and orpheus.speakable(text):
                directed = text
                if self._engine == "orpheus":           # only Orpheus ACTS a direction
                    emo = emotion_for(cues, self._emotion or "warm")
                    directed = text if emo == "neutral" else f"[{emo}] {text}"
                started = False
                try:
                    async for chunk in self._engine_chunks(directed):
                        if not started:
                            await self.stop_ttfb_metrics()
                            started = True
                            for f in self._frames(gap, context_id):
                                yield f
                        self._keep(chunk)
                        for f in self._frames(chunk, context_id):
                            yield f
                    if started:
                        self.engine_counts[self._engine] += 1
                        return
                except (orpheus.OrpheusError, aura.AuraError) as e:
                    if started:          # audio already playing: do not restart the sentence
                        logger.warning(f"{self} {self._engine} stopped mid-sentence: {e}")
                        return
                    logger.warning(f"{self} {self._engine} unavailable ({e}); this sentence -> edge")

            pcm = await self._synth_pcm(text, p.edge() if p else None,
                                        voice=HINDI_VOICE if lang == "hi" else None)
            await self.stop_ttfb_metrics()
            self.engine_counts["edge"] += 1
            self._keep(pcm)
            for f in self._frames(gap + pcm, context_id):
                yield f
        except Exception as e:  # noqa: BLE001 - surfaced as a pipeline error frame
            logger.error(f"{self} TTS failed: {e}")
            yield ErrorFrame(error=f"TTS failed: {e}")


EdgeTTSService = ParalangTTSService  # old name, kept for anything importing it


_VOICEMAIL_LINE = re.compile(r'voicemail or answering machine: say exactly one line\W+"([^"]+)"')


PLAYBOOK = Path(__file__).resolve().parents[1] / "campaign" / "playbook.json"


def load_playbook():
    """campaign/playbook.json -> paralang Playbook; None (no coaching) if absent/bad."""
    from paralang.playbook import Playbook
    try:
        return Playbook.load(PLAYBOOK) if PLAYBOOK.exists() else None
    except ValueError as e:
        logger.warning(f"playbook disabled: {e}")
        return None


def voicemail_line(cfg: dict) -> str:
    """The prompt's own voicemail line (rendered, names filled in), so the
    wording lives in one place: assistant/system_prompt.md."""
    m = _VOICEMAIL_LINE.search(cfg.get("system_prompt", ""))
    return m.group(1) if m else "Namaste, aapke plan ke liye ek offer hai, hum WhatsApp pe bhej rahe hain. Dhanyavaad."


def tools_schema() -> ToolsSchema:
    """functions.json (+ the local end_call) in Pipecat's provider-neutral form."""
    fns = []
    for t in phase1.load_tools():
        f = t["function"]
        params = f.get("parameters") or {}
        fns.append(FunctionSchema(name=f["name"], description=f.get("description", ""),
                                  properties=params.get("properties", {}),
                                  required=params.get("required", [])))
    return ToolsSchema(standard_tools=fns)


def groq_key() -> str:
    keys = phase1._groq_keys()
    if not keys:
        raise SystemExit("No Groq key: run via doppler (client-acquisition-pipeline/dev).")
    return keys[0]


def build_task(call: "phase1.Call", transport) -> PipelineTask:
    key = groq_key()
    # auto-detect, then hint the caller's language (GroqSTTService was forced to "en",
    # so Hindi callers were transcribed as English until 2026-10-22)
    stt = AutoLanguageGroqSTT(api_key=key, settings=AutoLanguageGroqSTT.Settings(
        model="whisper-large-v3-turbo"))
    llm = GroqLLMService(api_key=key, model=call.cfg["model"])
    # Speak back in reaction to how the caller's LAST turn sounded (para is
    # defined below; the lambda only runs once audio is flowing).
    tts = ParalangTTSService(
        voice=phase1.TTS_VOICE, rate=phase1.TTS_RATE,
        planner=DeliveryPlanner(base_rate_pct=int(phase1.TTS_RATE.strip("%+") or 0)),
        cues_fn=lambda: para.analyzer.turns[-1].cues if para.analyzer.turns else [],
        caller_text_fn=lambda: para.analyzer.turns[-1].text if para.analyzer.turns else "")

    async def on_tool(params: FunctionCallParams):
        # The Phase-1 handler is the single source of truth for tool effects
        # (DND file, captures, end_call). It returns {"status": "queued"},
        # which is what VAPI's async tools returned too.
        result = call._handle_tool(params.function_name, dict(params.arguments or {}))
        await params.result_callback(result)
        if params.function_name == "end_call":
            # Let the goodbye finish speaking, then hang up.
            await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)

    for t in phase1.load_tools():
        llm.register_function(t["function"]["name"], on_tool)

    # paralang: hears pauses/pace/pitch, prefixes "[tone: ...]" to the caller's
    # transcript, and keeps per-turn JSON on the Call for the dump + scoring.
    holder: dict = {}          # task is created below; handlers reach it through here

    # v0.3 #12: live supervisor feed (127.0.0.1 only; Command Center LIVE CALLS reads it)
    feed = LiveFeed.start() if os.environ.get("PARALANG_LIVE", "1") != "0" else None
    call.live_id = getattr(call, "live_id", None) or uuid.uuid4().hex[:10]
    call.live_feed = feed

    async def on_turn(r):
        call.para_turns.append(r.to_dict())
        silence.caller_spoke()
        if feed is not None:
            coach = next((c["coach"] for c in para.coached if c["turn"] == r.turn), None)
            hint = para.language_hint.hint if para.language_hint else None
            feed.publish(call.live_id, turn_event(r, coach=coach, lang=hint),
                         meta={"lead": call.lead.get("lead_name", ""), "agent": "jio rt_agent"})
        # v0.3 #4: re-fit the 'are you there?' wait to this caller's own pace
        if "task" in holder:
            await holder["task"].queue_frames([UserIdleTimeoutUpdateFrame(timeout=silence.timeout_s())])

    def on_machine(verdict):
        # v0.3 #7: beep heard (VAD ignores it, paralang watches non-speech audio).
        # Leave the prompt's own one-line voicemail message, then hang up.
        call.events.append({"tool": "machine", "args": {"kind": verdict.kind,
                            **verdict.evidence}, "t": time.time()})
        call.ended, call.end_reason = True, verdict.kind

        async def leave_message():
            await asyncio.sleep(0.6)          # let the beep finish
            await holder["task"].queue_frames([TTSSpeakFrame(voicemail_line(call.cfg)), EndFrame()])
        asyncio.get_running_loop().create_task(leave_message())

    def last_agent_line() -> str:
        ctx = holder.get("context")
        msgs = (ctx.get_messages() if hasattr(ctx, "get_messages") else getattr(ctx, "messages", [])) if ctx else []
        for m in reversed(msgs or []):
            if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str):
                return m["content"]
        return ""

    para = ParalangProcessor(Analyzer(), on_turn=on_turn, on_language=stt.set_language_hint,
                             on_machine=on_machine, playbook=load_playbook(),
                             agent_text_fn=last_agent_line)
    call.para_coached = para.coached         # v0.3 #11 coaching notes, for the call dump
    # v0.3 #13: paralang on Riya's own voice (pace vs caller, monotone, dead air)
    tts.selfcheck = SelfCheck(para.analyzer)
    tts._gap_fn = lambda: para.turn_timing["reply_gaps"][-1] if para.turn_timing["reply_gaps"] else None
    call.selfcheck = tts.selfcheck.replies
    call.tts = tts
    silence = SilencePolicy(para.analyzer)
    call.para_timing = para.turn_timing     # reply gaps + cut-offs, for the call dump
    call.para = para.analyzer

    context = LLMContext(
        messages=[{"role": "system", "content": call.cfg["system_prompt"] + "\n\n" + PROMPT_HINT + "\n" + SPEAKING_HINT},
                  {"role": "assistant", "content": call.cfg["first_message"]}],
        tools=tools_schema(),
    )
    holder["context"] = context
    aggregators = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_idle_timeout=silence.timeout_s(),
            # v0.3 #1: "haan"/"hmm" while Riya talks is listening, not an interruption.
            # Stop strategy stays Pipecat's default (smart-turn v3).
            user_turn_strategies=UserTurnStrategies(start=[BackchannelAwareStartStrategy(
                on_backchannel=lambda t: call.events.append(
                    {"tool": "backchannel", "args": {"text": t}, "t": time.time()}))])))

    @aggregators.user().event_handler("on_user_turn_idle")
    async def on_idle(_aggregator):
        act = silence.on_idle()
        call.events.append({"tool": "silence", "args": {"strike": silence.strikes,
                                                       "end": act.end_call}, "t": time.time()})
        frames = [TTSSpeakFrame(act.say)]
        if act.end_call:
            call.ended, call.end_reason = True, "caller silent"
            frames.append(EndFrame())        # after the goodbye is spoken
        await holder["task"].queue_frames(frames)

    pipeline = Pipeline([
        transport.input(), stt, para, aggregators.user(), llm, tts,
        transport.output(), aggregators.assistant(),
    ])
    task = PipelineTask(pipeline, params=PipelineParams(
        allow_interruptions=True, enable_metrics=True))
    holder["task"] = task
    return task


async def greet(task: PipelineTask, call: "phase1.Call") -> None:
    """Speak the opener. Local audio has no 'client connected' event, so the
    caller of build_task decides when; a telephony transport would call this
    from its on_client_connected handler instead."""
    await task.queue_frames([TTSSpeakFrame(call.cfg["first_message"])])


async def run_live(call: "phase1.Call") -> None:
    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

    transport = LocalAudioTransport(LocalAudioTransportParams(
        audio_in_enabled=True, audio_out_enabled=True,
        audio_in_sample_rate=16000, audio_out_sample_rate=SAMPLE_RATE))
    task = build_task(call, transport)
    await greet(task, call)
    try:
        await PipelineRunner(handle_sigint=True).run(task)
    finally:
        if getattr(call, "tts", None) is not None:
            call.tts.flush_selfcheck()             # the last reply
        rec = call.finish()
        if getattr(call, "live_feed", None) is not None:
            call.live_feed.end(call.live_id, {k: rec["result"].get(k) for k in ("score", "tier", "action")})
        print(f"\nscore {rec['result'].get('score')} tier {rec['result'].get('tier')} "
              f"-> {rec['result'].get('action')}")


async def selftest(call: "phase1.Call") -> None:
    """No mic needed: proves TTS, STT and tool wiring against the real services."""
    from groq import AsyncGroq

    import time
    tts = ParalangTTSService(voice=phase1.TTS_VOICE, rate=phase1.TTS_RATE)
    line = "Hello, your plan expires tomorrow. Shall I send the details?"   # English: Andromeda's job
    t0, first, chunks, spoke = time.perf_counter(), None, [], tts._engine
    try:
        async for c in tts._engine_chunks(line):
            first = first or (time.perf_counter() - t0)
            chunks.append(c)
        pcm = b"".join(chunks)
    except (aura.AuraError, orpheus.OrpheusError) as e:
        # exactly what a live call does: the sentence goes to Neerja, no dead air
        print(f"[ok] {tts._engine} slow/unavailable ({e}); fallback engaged")
        pcm, spoke = await tts._synth_pcm(line), "edge Neerja"
        first = time.perf_counter() - t0
    secs = len(pcm) / (SAMPLE_RATE * 2)
    assert secs > 0.8, f"{spoke} too short: {secs:.2f}s"
    print(f"[ok] {spoke} spoke {secs:.1f}s of {SAMPLE_RATE} Hz PCM, first audio {first * 1000:.0f} ms "
          f"(dead-air cap {LIVE_FIRST_AUDIO_S:.1f}s)")

    r = ReplyRouter()
    assert r.lang("Aapka plan kal khatam ho raha hai.", "t") == "hi"
    assert r.lang("Your plan is ending tomorrow, shall I send details?", "u") == "en"
    roman = await tts._synth_pcm("Koi baat nahi ji, aap aaram se sochiye.", voice=HINDI_VOICE)
    assert len(roman) / (SAMPLE_RATE * 2) > 0.8, "romanized Hindi via Swara produced no speech"
    print(f"[ok] on-the-fly switch: romanized Hindi -> {HINDI_VOICE} "
          f"({len(roman) / (SAMPLE_RATE * 2):.1f}s), English -> {tts._engine_voice}")
    hindi = await tts._synth_pcm("आपका प्लान कल खत्म हो रहा है।")
    assert len(hindi) / (SAMPLE_RATE * 2) > 0.8, "Devanagari fallback produced no speech"
    print(f"[ok] Devanagari -> edge {edge_voice_for('आपका')} ({len(hindi) / (SAMPLE_RATE * 2):.1f}s)")

    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm)
    tr = await AsyncGroq(api_key=groq_key()).audio.transcriptions.create(
        file=("t.wav", buf.getvalue()), model="whisper-large-v3-turbo")
    assert tr.text.strip(), "Groq STT returned empty text"
    print(f"[ok] groq whisper heard: {tr.text.strip()!r}")

    schema = tools_schema()
    names = [f.name for f in schema.standard_tools]
    assert {"end_call", "mark_dnd"} <= set(names), names
    print(f"[ok] {len(names)} tools mapped: {', '.join(names)}")

    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
    transport = LocalAudioTransport(LocalAudioTransportParams(
        audio_in_enabled=False, audio_out_enabled=False))
    build_task(call, transport)
    print("[ok] pipeline builds (STT -> paralang -> VAD/aggregator -> Groq LLM + tools -> Andromeda/Neerja/Swara)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--campaign", default=str(phase1.DEFAULT_CAMPAIGN))
    ap.add_argument("--lead-name", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("--expiry", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    lead = {"lead_name": a.lead_name, "current_plan": a.plan, "plan_expiry": a.expiry}
    call = phase1.Call(phase1.build_call_config(Path(a.campaign), lead), lead)
    asyncio.run(selftest(call) if a.selftest else run_live(call))


if __name__ == "__main__":
    main()
