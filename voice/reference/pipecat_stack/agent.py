"""
agent.py — Pure-Python Jio outbound voice agent. Zero per-minute platform fees.

Replaces the VAPI runtime with local components while reusing every asset the
VAPI deploy already uses (single source of truth, nothing forks):
  - system prompt + offer block : rendered via assistant/deploy_assistant.render()
  - tool schemas                : assistant/functions.json (+ a local end_call)
  - intent scoring              : campaign/intent_scoring.evaluate()

Stack (all free at demo time):
  LLM  Groq llama-3.3-70b (key via Doppler)        ~ $0.001/min
  TTS  edge-tts en-IN-NeerjaNeural (same voice VAPI used via Azure)   free
  STT  faster-whisper, local CPU                                       free
  I/O  sounddevice mic + winsound playback (Windows)                   free

Modes:
  --text       type to the agent in the console (no audio path)
  --voice      full mic + speakers voice loop
  --selftest   headless verification: TTS a user line -> STT it back ->
               one LLM turn -> TTS the reply. Proves the whole audio stack
               with no microphone. Run this first.

Usage:
  doppler run --project client-acquisition-pipeline --config dev -- \
      python agent.py --selftest
  doppler run --project client-acquisition-pipeline --config dev -- \
      python agent.py --voice --lead-name Rohan --plan "Rs 299" --expiry "12 June"

Telephony phase 2 (real +91 calls) is documented in
Projects/jio-outbound/pure-python-plan.md — this same loop drops into pipecat
with a Twilio/Exotel transport; only carrier termination is ever paid.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "assistant"))
sys.path.insert(0, str(ROOT / "campaign"))

from deploy_assistant import render  # noqa: E402  (reuses the VAPI render pipeline)
from intent_scoring import evaluate  # noqa: E402  (deterministic scorer)

DEFAULT_CAMPAIGN = ROOT / "assistant" / "campaigns" / "recharge_upsell.json"
FUNCTIONS_PATH = ROOT / "assistant" / "functions.json"
DND_FILE = ROOT / "campaign" / "dnd_list.txt"
CALL_LOG = HERE / "call_log.jsonl"

TTS_VOICE = "en-IN-NeerjaNeural"   # same neural voice the VAPI config used via Azure
TTS_RATE = "+5%"                   # matches voice.speed 1.05
STT_MODEL = os.getenv("WHISPER_MODEL", "base")
SAMPLE_RATE = 16000

# Each model has its OWN per-org daily token pool on Groq: this chain alone
# ~triples headroom on one key. GROQ_API_KEYS (comma-separated, one per Groq
# ACCOUNT — same-account keys share quota) multiplies it further.
MODEL_CHAIN_EXTRA = ["qwen/qwen3.8-27b", "qwen/qwen3.6-27b"]


def _groq_keys() -> list[str]:
    multi = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",")]
    keys = [k for k in multi if k] or [os.environ.get("GROQ_API_KEY", "").strip()]
    return [k for k in keys if k]


def chat_with_rotation(preferred_model: str, **kwargs):
    """(model x key) failover, model-major. Returns (model, response)."""
    import groq
    from groq import Groq

    chain = [preferred_model] + [m for m in MODEL_CHAIN_EXTRA if m != preferred_model]
    last = None
    for model in chain:
        for key in _groq_keys():
            try:
                return model, Groq(api_key=key).chat.completions.create(model=model, **kwargs)
            except (groq.RateLimitError, groq.AuthenticationError) as e:
                last = e
                continue
    raise last or RuntimeError("no usable GROQ key/model combination")


END_CALL_TOOL = {
    "type": "function",
    "function": {
        "name": "end_call",
        "description": "Hang up the call. Use after your warm closing line, or on voicemail.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "one short phrase, e.g. 'whatsapp sent', 'not interested'"}
        }},
    },
}


# ── prompt rendering ─────────────────────────────────────────────────────────

def _sanitize_value(v: str) -> str:
    """Lead values are DATA, never template or instructions. Strip anything that
    could smuggle template syntax or prompt structure in, and cap length.
    (VAPI gets this for free because variableValues never touch the template
    parser; here we string-substitute, so we enforce it ourselves.)"""
    v = str(v)
    v = re.sub(r"[{}%#\[\]<>`]", "", v)          # template/markdown structure chars
    v = re.sub(r"\s+", " ", v).strip()
    return v[:80]                                 # a name/plan/date never needs more


def resolve_liquid(text: str, variables: dict) -> str:
    """Apply the Liquid conditionals + {{var}} fills VAPI would do at call start.
    Only the narrow pattern our prompt uses: {% if X and X != "" %}...{% endif %}."""
    clean = {k: _sanitize_value(v) for k, v in variables.items()}

    def repl(m: re.Match) -> str:
        return m.group(2) if clean.get(m.group(1)) else ""
    text = re.sub(
        r'\{%\s*if\s+(\w+)\s+and\s+\1\s*!=\s*""\s*%\}(.*?)\{%\s*endif\s*%\}',
        repl, text, flags=re.S,
    )
    for k, v in clean.items():
        text = text.replace("{{" + k + "}}", v)
    return re.sub(r"\{\{[^}]+\}\}", "", text)  # anything unknown -> blank, like VAPI


def build_call_config(campaign_path: Path, lead: dict) -> dict:
    if not campaign_path.is_file():
        raise SystemExit(f"Campaign JSON not found: {campaign_path}")
    try:
        payload = render(str(campaign_path))
    except (OSError, json.JSONDecodeError, RuntimeError) as e:
        raise SystemExit(f"render() failed for {campaign_path}: {e}")
    try:
        model = payload["model"]
        prompt = model["messages"][0]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise SystemExit(f"Rendered payload missing model.messages[0].content: {e}")
    return {
        "system_prompt": resolve_liquid(prompt, lead),
        "model": model.get("model", "qwen/qwen3.8-27b"),
        "temperature": model.get("temperature", 0.4),
        "max_tokens": model.get("maxTokens", 200),
        "first_message": payload.get("firstMessage", "Namaste!"),
    }


def load_tools() -> list[dict]:
    data = json.loads(FUNCTIONS_PATH.read_text(encoding="utf-8"))
    tools = [
        {"type": "function", "function": {
            "name": f["name"], "description": f["description"], "parameters": f["parameters"]}}
        for f in data["functions"]
    ]
    tools.append(END_CALL_TOOL)  # VAPI's built-in endCall, provided locally
    return tools


def load_tool_speech() -> dict[str, str]:
    """name -> request-start spoken line from functions.json. Mirrors VAPI's
    tool-level messages: if a turn is tool-calls-only (no text), we speak this
    fixed line so the listener never gets silence (the turn-2 silence bug)."""
    data = json.loads(FUNCTIONS_PATH.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for f in data["functions"]:
        for m in f.get("messages", []):
            if m.get("type") == "request-start" and m.get("content"):
                out[f["name"]] = m["content"]
    return out


# ── audio: TTS (paralang: Aura Andromeda, Neerja/Swara fallback) and STT (faster-whisper) ──

def tts_to_wav(text: str, wav_path: Path) -> None:
    """Deepgram Aura-2 Andromeda by default via paralang.say, which speaks any
    Devanagari sentence with edge Swara and any sentence Aura fails on with edge
    Neerja. Plain edge-tts Neerja when paralang is missing or PARALANG_ENGINE=edge;
    PARALANG_ENGINE=orpheus uses Groq Orpheus instead."""
    engine = (os.environ.get("PARALANG_ENGINE") or "aura").lower()
    if engine != "edge":
        try:
            from paralang.say import say_wav
            voice = os.environ.get("PARALANG_AGENT_VOICE") or None   # engine default: andromeda
            say_wav(f"[warm] {text}", wav_path, voice=voice, engine=engine)
            return
        except ImportError:
            print("  [warn] paralang not installed; speaking with edge-tts", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - never go silent: edge-tts below
            print(f"  [warn] {engine} failed ({type(e).__name__}: {e}); speaking with edge-tts",
                  file=sys.stderr)
    import edge_tts

    mp3_path = wav_path.with_suffix(".mp3")
    # Neerja (en-IN) returns no audio for Devanagari: Hindi script needs Swara
    voice = "hi-IN-SwaraNeural" if re.search(r"[ऀ-ॿ]", text) else TTS_VOICE
    asyncio.run(edge_tts.Communicate(text, voice, rate=TTS_RATE).save(str(mp3_path)))
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path),
             "-ar", "24000", "-ac", "1", str(wav_path)],
            check=True, timeout=60,
        )
    finally:
        mp3_path.unlink(missing_ok=True)


def play_wav(path: Path) -> None:
    import winsound
    winsound.PlaySound(str(path), winsound.SND_FILENAME)


_stt_model = None


def stt(wav_path: Path) -> str:
    global _stt_model
    if _stt_model is None:
        from faster_whisper import WhisperModel
        print(f"  [stt] loading faster-whisper '{STT_MODEL}' (first run downloads the model)...")
        _stt_model = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
    segments, _info = _stt_model.transcribe(str(wav_path), vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def record_utterance(max_seconds: int = 15, silence_after: float = 1.2) -> Path | None:
    """Energy-VAD mic capture: wait for speech, stop after trailing silence."""
    import numpy as np
    import sounddevice as sd

    block = int(SAMPLE_RATE * 0.1)  # 100 ms chunks
    threshold = 350                  # int16 RMS; raise if a noisy room self-triggers
    frames: list[bytes] = []
    started = False
    silent_blocks = 0
    need_silent = int(silence_after / 0.1)

    print("  [mic] listening... (speak, pause to finish)")
    with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=block) as stream:
        for _ in range(int(max_seconds / 0.1)):
            data, _overflow = stream.read(block)
            buf = bytes(data)
            rms = float(np.sqrt(np.mean(np.frombuffer(buf, dtype=np.int16).astype(np.float64) ** 2)))
            if rms > threshold:
                started = True
                silent_blocks = 0
            elif started:
                silent_blocks += 1
            if started:
                frames.append(buf)
                if silent_blocks >= need_silent:
                    break
    if not started:
        return None
    path = Path(tempfile.gettempdir()) / "jio_local_utterance.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(frames))
    return path


# ── the call loop ────────────────────────────────────────────────────────────

class Call:
    """One conversation. Mirrors VAPI semantics: async-style tools that return
    {'status':'queued'} instantly, then a follow-up generation for the speech."""

    def __init__(self, cfg: dict, lead: dict):
        from groq import Groq
        keys = _groq_keys()
        if not keys:
            raise SystemExit("No Groq key found: set GROQ_API_KEY or GROQ_API_KEYS (run via doppler).")
        self.client = Groq(api_key=keys[0])  # used by the out-of-band extractor
        self.cfg = cfg
        self.lead = lead
        self.tools = load_tools()
        self.tool_speech = load_tool_speech()
        self.history: list[dict] = [{"role": "assistant", "content": cfg["first_message"]}]
        self.captures: list[dict] = []
        self.events: list[dict] = []
        self.ended = False
        self.end_reason = ""
        self.para = None              # paralang.Analyzer when the realtime agent runs one
        self.para_turns: list[dict] = []

    # tool handlers — this is where VAPI's webhook becomes plain Python
    def _handle_tool(self, name: str, args: dict) -> dict:
        self.events.append({"tool": name, "args": args, "t": time.time()})
        if name == "capture_intent":
            self.captures.append(args)
        elif name == "mark_dnd":
            number = args.get("number") or self.lead.get("customer_number", "")
            if number:
                with open(DND_FILE, "a", encoding="utf-8") as f:
                    f.write(number + "\n")
        elif name == "end_call":
            self.ended = True
            self.end_reason = args.get("reason", "")
        # schedule_callback / send_whatsapp / transfer_call: logged only (demo),
        # same as VAPI's fire-and-forget async tools with no webhook wired.
        return {"status": "queued"}

    def _generate(self) -> "tuple[str, list]":
        _model, resp = chat_with_rotation(
            self.cfg["model"],
            temperature=self.cfg["temperature"],
            max_tokens=self.cfg["max_tokens"],
            tools=self.tools,
            messages=[{"role": "system", "content": self.cfg["system_prompt"]}] + self.history,
        )
        if not resp.choices:
            return "", []
        m = resp.choices[0].message
        return (m.content or "").strip(), list(m.tool_calls or [])

    def turn(self, user_text: str) -> str:
        """One user turn -> agent speech (running the tool loop like VAPI does)."""
        self.history.append({"role": "user", "content": user_text})
        speech_parts: list[str] = []
        fired_tools: list[str] = []
        for _hop in range(3):  # text -> tools -> follow-up speech; hard cap
            text, tool_calls = self._generate()
            if text:
                speech_parts.append(text)
            if not tool_calls:
                self.history.append({"role": "assistant", "content": text})
                break
            self.history.append({
                "role": "assistant", "content": text,
                "tool_calls": [{"id": t.id, "type": "function", "function": {
                    "name": t.function.name, "arguments": t.function.arguments}} for t in tool_calls],
            })
            for t in tool_calls:
                try:
                    args = json.loads(t.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._handle_tool(t.function.name, args)
                fired_tools.append(t.function.name)
                self.history.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(result)})
            if self.ended:
                break
        speech = " ".join(p for p in speech_parts if p).strip()
        if not speech and fired_tools:
            # Tool-calls-only turn: speak the tools' fixed request-start lines,
            # exactly like VAPI's tool messages. The listener never gets silence.
            speech = " ".join(self.tool_speech[n] for n in fired_tools if n in self.tool_speech).strip()
            if speech:
                self.history.append({"role": "assistant", "content": speech})
        return speech

    def _extract_intent(self) -> list[dict]:
        """Out-of-band intent extraction (dograh pattern): the talking model never
        emits structured data (that caused speech-less turns); a separate cheap
        model reads the finished transcript instead. Mirrors VAPI analysisPlan.
        Uses qwen/qwen3.6-27b: extraction is easy, and it has its own Groq
        daily-token pool, so it works even when the 70b budget is exhausted."""
        convo = "\n".join(
            f"{'AGENT' if m['role'] == 'assistant' else 'USER'}: {m['content']}"
            for m in self.history if m["role"] in ("user", "assistant") and m.get("content")
        )
        if not convo:
            return []
        try:
            resp = self.client.chat.completions.create(
                model="qwen/qwen3.6-27b",
                temperature=0,
                max_tokens=200,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content":
                        "Extract the listener's buying intent from this outbound telecom sales call. "
                        "Return ONLY a JSON object with keys: interest_level (one of hot, warm, cold, not_interested), "
                        "signals (array of short phrases actually heard), product_interest "
                        "(one of recharge, upgrade, jiofiber, addon, not_sure, none), objection (string, may be empty)."},
                    {"role": "user", "content": convo},
                ],
            )
            data = json.loads(resp.choices[0].message.content or "{}")
        except Exception as e:
            print(f"  [warn] intent extraction failed ({type(e).__name__}); scoring with no signals.", file=sys.stderr)
            return []
        if data.get("interest_level") not in ("hot", "warm", "cold", "not_interested"):
            return []
        return [data]

    def finish(self) -> dict:
        if not self.captures:
            self.captures = self._extract_intent()
        if self.para is not None and self.captures:
            # Voice cues are measured, not guessed: merge them as signals so the
            # deterministic scorer weighs them ("tone: hesitant" matches "hesitant").
            sig = self.captures[-1].setdefault("signals", [])
            sig.extend(s for s in self.para.call_signals() if s not in sig)
        result = evaluate(self.captures, dnd=any(e["tool"] == "mark_dnd" for e in self.events))
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lead": self.lead,
            "end_reason": self.end_reason,
            "captures": self.captures,
            "events": [{k: v for k, v in e.items() if k != "t"} for e in self.events],
            "result": asdict(result),
            "transcript": [m for m in self.history if m["role"] in ("user", "assistant") and m.get("content")],
        }
        if getattr(self, "selfcheck", None):
            record["selfcheck"] = self.selfcheck       # paralang on the agent's own voice
        if getattr(self, "para_coached", None):
            record["coached"] = self.para_coached     # paralang playbook notes used
        if getattr(self, "para_timing", None):
            record["turn_timing"] = self.para_timing   # paralang end-of-turn telemetry
        if self.para is not None:
            # export() waits for the background voice-quality pass (jitter/shimmer/HNR)
            record["paralang"] = self.para.export()
            self.para.close()
        elif self.para_turns:
            record["paralang"] = self.para_turns
        try:
            with open(CALL_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"  [warn] could not write call log: {e}", file=sys.stderr)
        return record


# ── modes ────────────────────────────────────────────────────────────────────

def run_text(call: Call) -> None:
    print(f"\nAGENT: {call.cfg['first_message']}")
    print("(type your replies; /quit to end)\n")
    while not call.ended:
        try:
            user = input("YOU:   ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user == "/quit":
            break
        reply = call.turn(user)
        print(f"AGENT: {reply or '(tool action only)'}")
    summary = call.finish()
    r = summary["result"]
    print(f"\n-- call scored: {r['score']}/100 tier={r['tier']} action={r['action']} "
          f"(log: {CALL_LOG.name})")


def run_voice(call: Call) -> None:
    tmp = Path(tempfile.gettempdir())
    # Warm the STT model BEFORE the call starts, or the first turn stalls ~15s.
    # Pure optimization: if it fails, the lazy load in stt() still covers us.
    silence = tmp / "jio_warmup.wav"
    try:
        with wave.open(str(silence), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(b"\x00\x00" * SAMPLE_RATE)  # 1s of silence
        stt(silence)
    except Exception as e:
        print(f"  [warn] STT warmup skipped ({e}); first turn may be slow.", file=sys.stderr)
    finally:
        silence.unlink(missing_ok=True)
    first = tmp / "jio_agent_say.wav"
    tts_to_wav(call.cfg["first_message"], first)
    print(f"AGENT: {call.cfg['first_message']}")
    play_wav(first)
    while not call.ended:
        utt = record_utterance()
        if utt is None:
            print("  [mic] no speech detected; ending call.")
            break
        heard = stt(utt)
        if not heard:
            continue
        print(f"YOU:   {heard}")
        reply = call.turn(heard)
        if reply:
            print(f"AGENT: {reply}")
            out = tmp / "jio_agent_say.wav"
            tts_to_wav(reply, out)
            play_wav(out)
    summary = call.finish()
    r = summary["result"]
    print(f"\n-- call scored: {r['score']}/100 tier={r['tier']} action={r['action']}")


def run_selftest(call: Call) -> None:
    """Headless end-to-end: proves TTS, STT, LLM+tools, scoring with no mic."""
    tmp = Path(tempfile.gettempdir())
    user_line = "Haan bolo, kitne ka hai recharge plan?"
    print(f"[1/4] TTS user line via edge-tts ({TTS_VOICE})...")
    t0 = time.time()
    wav = tmp / "jio_selftest_user.wav"
    tts_to_wav(user_line, wav)
    print(f"      ok ({time.time()-t0:.1f}s, {wav.stat().st_size} bytes) — $0.00")

    print(f"[2/4] STT it back via faster-whisper '{STT_MODEL}'...")
    t0 = time.time()
    heard = stt(wav)
    if not heard:
        raise SystemExit("SELFTEST FAIL: STT returned empty text")
    print(f"      heard: {heard!r} ({time.time()-t0:.1f}s) — $0.00")

    print("[3/4] LLM turn via Groq (tools live)...")
    t0 = time.time()
    reply = call.turn(heard)
    if not (reply or call.events):
        raise SystemExit("SELFTEST FAIL: LLM produced neither speech nor tool calls")
    print(f"      agent: {reply!r}")
    print(f"      tools fired: {[e['tool'] for e in call.events]} ({time.time()-t0:.1f}s)")

    print("[4/4] TTS the reply...")
    out = tmp / "jio_selftest_agent.wav"
    tts_to_wav(reply or "Theek hai, dhanyavaad.", out)
    print(f"      ok ({out})")

    summary = call.finish()
    r = summary["result"]
    print(f"\nSELFTEST PASS — full voice loop verified at $0.00/min. "
          f"score={r['score']} tier={r['tier']} action={r['action']}")


def main():
    ap = argparse.ArgumentParser(description="Pure-Python Jio outbound voice agent (no VAPI).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--text", action="store_true")
    mode.add_argument("--voice", action="store_true")
    mode.add_argument("--selftest", action="store_true")
    ap.add_argument("--campaign", default=str(DEFAULT_CAMPAIGN))
    ap.add_argument("--lead-name", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("--expiry", default="")
    ap.add_argument("--circle", default="")
    ap.add_argument("--number", default="+910000000000")
    args = ap.parse_args()

    if not _groq_keys():
        raise SystemExit("No Groq key found (GROQ_API_KEY or GROQ_API_KEYS) — run via: doppler run "
                         "--project client-acquisition-pipeline --config dev -- python agent.py ...")

    lead = {
        "lead_name": args.lead_name, "current_plan": args.plan,
        "plan_expiry": args.expiry, "circle": args.circle,
        "customer.number": args.number, "customer_number": args.number,
    }
    cfg = build_call_config(Path(args.campaign), lead)
    call = Call(cfg, lead)

    if args.selftest:
        run_selftest(call)
    elif args.voice:
        run_voice(call)
    else:
        run_text(call)


if __name__ == "__main__":
    main()
