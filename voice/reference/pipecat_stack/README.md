# Reference: Shaurya's $0/min Pipecat voice stack (copied from jio-outbound, 2026-11-05)

Read-only reference. Do not run as-is: it is the Jio sales agent. Port the PATTERN into `voice/`.

- `rt_agent.py`: Pipecat 1.12 real-time agent. Groq Whisper STT + Groq LLM + edge-tts `hi-IN`/`en-IN` Neerja voice, Silero VAD, barge-in, paralang delivery (tone/silence/Hindi routing).
- `agent.py`: the non-real-time call logic it reuses (tools, call state). Jio-specific; only the structure matters.
- `requirements-rt.txt`: deps. `paralang` is Shaurya's public MIT repo: `pip install git+https://github.com/shauryalowkeygotaura/paralang`.

Cost: $0.00/min AI (Groq free pool + edge-tts). Telephony later via Exotel SIP (~$0.007/min, needs KYC). Browser WebRTC transport is free.
