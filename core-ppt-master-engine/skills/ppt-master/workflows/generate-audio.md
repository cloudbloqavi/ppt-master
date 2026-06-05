description: Generate per-slide narration audio with AI-recommended voice selection, then optionally re-export PPTX with embedded audio

# Generate Audio Workflow

> Standalone post-export step. Run when the user asks for "Generate Audio" / "Record Narration" / "narrated PPT" / "video export with voice", or proactively offer it after a deck is exported. Produces one audio file per slide via `edge-tts` by default, or a cloud TTS provider (`elevenlabs` / `minimax` / `qwen` / `cosyvoice`) when the user chooses high-quality narration or a cloned voice, then optionally re-exports a video-ready PPTX with audio embedded and per-slide auto-advance timings.

This workflow is **independent**: it reads `notes/*.md` and queries the selected TTS voice catalog — no upstream conversation context required. Safe to invoke in a fresh session.

## When to Run

- `notes/total.md` exists and has been split into per-page files at `notes/*.md` (post-processing Step 7.1 done).
- Default mode: `edge-tts` is installed (`python3 -m pip install edge-tts`).
- The workflow is page-level only: one notes file becomes one audio file. Do not use a single long audio track or attempt automatic long-audio splitting.
- PPT narration assets must be PowerPoint-reliable audio: `m4a` (AAC), `mp3`, or `wav`. The built-in TTS path defaults to `mp3`; provider formats such as `pcm`, `opus`, or `flac` must be transcoded before embedding.
- PowerPoint recorded narration export requires `ffprobe` so slide timings can be written from actual audio duration.
- High-quality cloud mode: provider API key is set before use:
  - ElevenLabs: `ELEVENLABS_API_KEY`
  - MiniMax: `MINIMAX_API_KEY`
  - Qwen: `QWEN_API_KEY` or `DASHSCOPE_API_KEY`
  - CosyVoice: `COSYVOICE_API_KEY` or `DASHSCOPE_API_KEY`
  - Keys may live in the current process environment or the first `.env` found in this order: current working directory, skill directory (e.g. `~/.agents/skills/ppt-master/.env`), clone repo root, `~/.ppt-master/.env`
- The deck is in a single dominant language (mixed-language decks: pick the dominant one — the AI uses judgment, not a heuristic).

If `notes/*.md` are missing, run `total_md_split.py <project_path>` first.

---

## Step 1: Determine the deck's language

The AI already knows the deck's language from writing the notes. No detection script needed.

- Identify the primary language from the notes content: `zh` / `en` / `ja` / `ko` / etc.
- For mixed-language decks (e.g. Chinese with English technical terms), pick the language the audience will hear most of.
- For Chinese specifically: pick the locale based on context — `zh-CN` (mainland mandarin, default), `zh-TW` (Taiwanese mandarin), or `zh-HK` (Cantonese). Ask the user only if the project context doesn't make it clear.

---

## Step 2: Choose audio backend and pull the voice catalog

Default to **edge** unless the user explicitly asks for a cloud provider / higher-quality cloud narration / a cloned voice.

**edge backend**:

```bash
python3 skills/ppt-master/scripts/notes_to_audio.py --list-voices --locale <locale>
```

**ElevenLabs backend**:

```bash
python3 skills/ppt-master/scripts/notes_to_audio.py --provider elevenlabs --list-voices
```

**Cloud providers using explicit voice IDs/names**:

```bash
python3 skills/ppt-master/scripts/notes_to_audio.py --provider minimax --list-voices
python3 skills/ppt-master/scripts/notes_to_audio.py --provider qwen --list-voices
python3 skills/ppt-master/scripts/notes_to_audio.py --provider cosyvoice --list-voices
```

The output is a flat list of all available voices for the selected provider. From this list, the AI picks **3–6 candidates** to recommend, applying these rules:

- **Cover both genders** when both exist for the locale.
- **For edge**: prefer `COMMON_VOICES`-listed voices (curated set inside `notes_to_audio.py`) when the locale has them — they are battle-tested.
- **For ElevenLabs**: prefer voices already present in the user's account; if the user provides a specific `voice_id`, do not override it.
- **For MiniMax / Qwen / CosyVoice**: if the user provides a cloned `voice_id`, use it directly. Do not attempt voice cloning inside the narration workflow.
- **Match the deck's tone** — pick the strongest recommendation based on style:
  - Consultant / data-driven / financial report → steady male voice (e.g. `zh-CN-YunjianNeural`) or clear female voice (e.g. `zh-CN-XiaoxiaoNeural`)
  - General / teaching / product introduction → bright female voice / young male voice (e.g. `zh-CN-XiaoyiNeural` / `zh-CN-YunxiNeural`)
  - Press conference / broadcast → broadcast-style male voice (e.g. `zh-CN-YunyangNeural`)
  - English consultant deck → `en-US-GuyNeural` (steady) or `en-US-JennyNeural` (clear)
  - Japanese / Korean → pick from `ja-JP-*` / `ko-KR-*` neural voices, mark gender + tone

For each candidate, write a **one-line description** covering: Gender · Tone · Applicable Scenario. For cloud providers, include the voice name/ID exactly as it must be passed to `--voice-id`.

---

## Step 3: One-shot user interaction (mandatory)

Send a single message to the user that asks all three questions at once and provides a recommended value for each. Do NOT split into multiple rounds.

**Cloned-voice fast path**: if the user mentioned a cloned voice / cloned voice / replicated voice / "my own voice" along with a `voice_id`, skip the voice-recommendation list — set the provider to whichever the user named (`elevenlabs` / `minimax` / `qwen` / `cosyvoice`), pin the `voice_id` they gave you, and only confirm rate + embed-or-not.

**Message template** (translate to user's chat language if different):

> The primary language of the notes is detected as **<Language>** (locale: `<locale>`). Based on the deck's tone (<Style>), I recommend the following configuration:
>
> **Generation Mode**: ⭐ Recommended `<edge|elevenlabs|minimax|qwen|cosyvoice>` (Reason: <One sentence, such as "no configuration needed, stable generation" or "user requested high-quality cloud voice">).
>
> **Voice**:
> - **[1] <ShortName>** — <Gender · Tone · Applicable Scenario> ⭐ **Recommended**
> - [2] <ShortName> — <Gender · Tone · Applicable Scenario>
> - [3] <ShortName> — <Gender · Tone · Applicable Scenario>
> - [4] <ShortName> — <Gender · Tone · Applicable Scenario>
> - [5] <ShortName> — <Gender · Tone · Applicable Scenario>
> - You can also directly enter other ShortNames from the list.
>
> **Speech Rate/Style Parameters**: ⭐ Recommended `<rate or provider defaults>` (Reason: <One sentence, such as "2–3 sentences per page, normal speech rate sounds most stable" or "ElevenLabs default voice settings best preserve the original voice performance">).
>
> **Re-export PPTX with embedded audio after generation**: ⭐ Recommended **Yes** (one-shot, automatically sets page duration based on audio length).
>
> Reply "OK" to use all recommended values, or tell me what you want to change (e.g., "Voice 2, rate -5%" or "use MiniMax's voice_id xxx").

**Recommended-value rules**:
- Generation Mode: `edge` by default; when the user explicitly seeks high-quality cloud voice or provides a cloud voice ID, select `elevenlabs` / `minimax` / `qwen` / `cosyvoice` as specified by the user.
- Voice: Pick the one from Step 2 candidates that best matches the deck's tone.
- Speech Rate: edge defaults to `+0%`; if notes are dense (average >4 long sentences per page), `-5%` is suggested; if notes are brief and concise, `+5%` is suggested; reasons must be given if outside this range. Cloud providers default to provider defaults, unless the user explicitly requests to adjust speed or style.
- Embedding: "Yes" is recommended by default; unless the user has a customized PPTX they do not wish to overwrite.

---

## Step 4: Execute (no further interaction)

Run sequentially — do NOT bundle:

```bash
# 1A. Generate audio with edge (default)
python3 skills/ppt-master/scripts/notes_to_audio.py <project_path> \
  --voice <chosen-ShortName> --rate <chosen-rate>

# 1B. Or generate audio with ElevenLabs
python3 skills/ppt-master/scripts/notes_to_audio.py <project_path> \
  --provider elevenlabs --voice-id <chosen-voice-id> \
  --elevenlabs-model eleven_multilingual_v2

# 1C. Or generate audio with MiniMax
# Defaults to the China endpoint; set MINIMAX_TTS_BASE_URL=https://api.minimax.io/v1/t2a_v2 for overseas access.
python3 skills/ppt-master/scripts/notes_to_audio.py <project_path> \
  --provider minimax --voice-id <chosen-voice-id> \
  --minimax-model speech-2.8-hd

# 1D. Or generate audio with Qwen TTS
python3 skills/ppt-master/scripts/notes_to_audio.py <project_path> \
  --provider qwen --voice-id <chosen-voice> \
  --qwen-model qwen3-tts-flash --qwen-language-type Chinese

# 1E. Or generate audio with CosyVoice
python3 skills/ppt-master/scripts/notes_to_audio.py <project_path> \
  --provider cosyvoice --voice-id <chosen-voice> \
  --cosyvoice-model cosyvoice-v3-flash

# 2. (If user kept embedding) Re-export PPTX with audio embedded
python3 skills/ppt-master/scripts/svg_to_pptx.py <project_path> \
  --recorded-narration audio
```

If `notes_to_audio.py` errors with a missing dependency or missing provider API key, fix the prerequisite and re-run — do NOT swallow the error.

`--recorded-narration audio` prepares PowerPoint's recorded timings and narrations: every slide must have a matching supported audio file, every duration must be readable by `ffprobe`, and object animations must not use `--animation-trigger on-click`. Use `after-previous` or `with-previous` for narrated/video export.

---

## Step 5: Completion report

Output one summary block listing:

- Number of audio files generated and their location (`<project_path>/audio/*`).
- The provider, voice, and rate/settings actually used.
- (If embedded) the new narrated PPTX path under `<project_path>/exports/`.
- (If skipped embedding) one-line hint on how to embed later: `python3 skills/ppt-master/scripts/svg_to_pptx.py <project_path> --recorded-narration audio`.