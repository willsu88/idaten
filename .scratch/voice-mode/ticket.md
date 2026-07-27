# Ticket: voice mode - talk to the coach

Filed 2026-07-27 from a brainstorm. Status: idea, not scheduled.
Motivation is dual: a real use case (hands-free post-run debrief, morning check-in) and a learning vehicle for voice-agent architecture (endpointing, barge-in, turn-taking latency).

## Architecture decision (made up front)

**Cascaded pipeline (ASR -> existing text coach -> TTS), not native speech-to-speech.**

- The coach, tool loop, `LLMClient` seam, and plan-edit approval queue stay completely untouched; voice is an I/O adapter in front of the existing chat endpoint.
- LLM token cost is therefore unchanged. Voice adds only ASR/TTS cost: $0 with browser APIs, ~$0.02-0.04/min with Whisper + OpenAI TTS (a 5-min daily debrief is ~$3-6/month).
- Native speech-to-speech (OpenAI Realtime, Gemini Live) is ~10-20x text cost, bypasses the provider seam, and complicates tool use. Rejected.

## Phases

### v1 - push-to-talk (weekend-sized, $0)
- Mic button in the existing chat UI.
- Browser Web Speech API for ASR, `speechSynthesis` for TTS reading the streamed reply.
- No backend changes at all.

### v2 - real pipeline
- Server-side Whisper (API or whisper.cpp local) behind a small `/chat/audio` adapter.
- Better TTS, synthesized sentence-by-sentence from the existing stream so speech starts before the LLM finishes.
- VAD (silero) replaces push-to-talk.

### v3 - the interesting voice-agent problems
- **Semantic endpointing**: on each VAD pause, classify the partial transcript as `complete | incomplete` (Haiku or heuristic: trailing conjunction/filler words -> incomplete); short endpoint timeout when complete, long when incomplete.
- **Barge-in**: user speech cancels in-flight TTS (and ideally the LLM stream).
- **Tool-latency masking**: tool calls take 3-8s; emit an immediate acknowledgment utterance ("let me pull up your week") before the real answer.

## Design constraints

- Plan edits stay visual: voice speaks a summary of a proposed diff, but accept/dismiss remains an on-screen action. No voice confirmation for state-changing operations in v1-v3.
- Voice must degrade gracefully to the text chat; it is an enhancement layer, never a fork of the agent.

## Open questions

1. Is mobile Safari's Web Speech API good enough for v1, since the phone is the primary voice device?
2. Latency budget: what end-to-end (end of user speech -> first audio out) is acceptable? Sub-1s likely needs v2 streaming TTS at minimum.
3. Does semantic endpointing need a dedicated fast-model slot in `make_client()`, or a one-off client?
