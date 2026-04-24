import json
import os

import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="NightyNight",
    layout="centered",
)

st.title("NightyNight🌙✨")
st.caption("A bedtime science story, made just for tonight.")

# ── Session state init ────────────────────────────────────────────────────────

if "final_story" not in st.session_state:
    st.session_state.final_story = None
if "forced_chapters" not in st.session_state:
    st.session_state.forced_chapters = []
if "topic" not in st.session_state:
    st.session_state.topic = ""
if "audio_url" not in st.session_state:
    st.session_state.audio_url = None
if "audio_info" not in st.session_state:
    st.session_state.audio_info = {}

# ── Ambient preview helpers ────────────────────────────────────────────────────

_AMBIENT_PREVIEW_PATHS: dict[str, str] = {
    "fire":   "sounds/fire/fire01.mp3",
    "rain":   "sounds/rain/Light rain recordings mixed settings-01.wav",
    "ocean":  "sounds/ocean/ocean01.mp3",
    "woods":  "sounds/woods/woods01.mp3",
    "cosmos": "sounds/cosmos/cosmos01.wav",
}

_COSMOS_WORDS  = {"universe", "cosmos", "space", "galaxy", "star", "big bang", "astronomy",
                   "cosmic", "planet", "black hole", "nebula", "supernova", "quasar", "dark matter"}
_LIFE_WORDS    = {"biology", "evolution", "life", "species", "animal", "plant", "tree",
                   "forest", "creature", "dna", "cell", "nature", "ecosystem", "dinosaur"}
_HISTORY_WORDS = {"history", "civilization", "ancient", "rome", "egypt", "dynasty", "war",
                   "culture", "empire", "greek", "human", "society", "archaeology", "medieval"}

def _infer_ambient(topic: str) -> str:
    t = topic.lower()
    if any(w in t for w in _COSMOS_WORDS):
        return "cosmos"
    if any(w in t for w in _HISTORY_WORDS):
        return "fire"
    if any(w in t for w in _LIFE_WORDS):
        return "woods"
    return "rain"

# ── Input form ────────────────────────────────────────────────────────────────

with st.form("generate_form"):
    topic = st.text_input(
        "Topic",
        placeholder="e.g. the birth of the universe, how trees communicate, ancient Rome...",
    )

    col1, col2 = st.columns(2)
    with col1:
        duration_min = st.select_slider(
            "Duration (minutes)",
            options=[8, 10, 15, 20, 25],
            value=15,
        )
    with col2:
        style = st.selectbox(
            "Narration style",
            ["calm documentary", "gentle bedtime", "soft storytelling"],
        )
        audience = st.selectbox(
            "Audience",
            ["curious adults", "science enthusiasts", "general public"],
        )

    col3, col4 = st.columns(2)
    with col3:
        ambient_choice = st.selectbox(
            "Ambient sound",
            ["auto", "fire", "rain", "ocean", "woods", "cosmos", "none"],
            index=0,
            help='"auto" picks by story domain',
        )
    with col4:
        _VOICE_OPTIONS = {
            # User's own voices
            "True Crime & Horror Narrator":          "tZssYepgGaQmegsMEXjK",
            "Kyle Manning":                          "q8hD3YAFEqLvfbspywun",
            "Archer (deep, steady, relaxing)":       "X0K9Z1Bor9SpbE1wSaoe",
            "Adam Stone (smooth, deep, relaxed)":    "NFG5qt843uXKj4pFvR7C",
            "Christopher (gentle, trustworthy)":     "G17SuINrv2H9FC6nvetn",
            "John Doe (deep)":                       "EiNlNiXeDU1pqqOPrYMO",
            "Autumn Veil (warm, reflective female)": "KoVIHoyLDrQyd4pGalbs",
        }
        voice_label = st.selectbox(
            "Voice",
            list(_VOICE_OPTIONS.keys()),
            index=4,  # Christopher — gentle, trustworthy, good default for bedtime
            help="Christopher or Archer work well for bedtime science; Autumn Veil for a warm female narrator",
        )
        voice_choice = _VOICE_OPTIONS[voice_label]

    submitted = st.form_submit_button("Generate story + audio", type="primary", use_container_width=True)

# ── Generation & streaming ────────────────────────────────────────────────────

if submitted:
    if not topic.strip():
        st.warning("Please enter a topic.")
        st.stop()

    # Clear previous results when a new story is requested
    st.session_state.final_story = None
    st.session_state.audio_url = None
    st.session_state.audio_info = {}
    st.session_state.topic = topic.strip()

    # Play ambient immediately while story generates.
    # Use the user's explicit choice so the preview matches the final mixed audio.
    # If "auto", infer from topic. If "none", skip preview entirely.
    if ambient_choice == "none":
        preview_ambient = None
    elif ambient_choice == "auto":
        preview_ambient = _infer_ambient(topic)
    else:
        preview_ambient = ambient_choice

    if preview_ambient and preview_ambient in _AMBIENT_PREVIEW_PATHS:
        preview_url = f"{API_BASE}/{_AMBIENT_PREVIEW_PATHS[preview_ambient]}"
        st.components.v1.html(
            f"""
            <audio id="cs-ambient-preview" autoplay loop style="display:none">
                <source src="{preview_url}">
            </audio>
            <script>
                document.getElementById('cs-ambient-preview').volume = 0.3;
            </script>
            """,
            height=0,
        )

    status_box    = st.empty()
    progress_bar  = st.progress(0)
    warning_box   = st.empty()
    story_placeholder = st.empty()

    _NODE_PROGRESS = {
        "plan_story":      10,
        "write_chapter":   30,
        "reflect_chapter": 50,
        "revise_chapter":  55,
        "iterate_chapter": 58,
        "advance_chapter": 70,
        "polish_story":    90,
    }

    payload = {
        "topic": topic.strip(),
        "duration_min": duration_min,
        "style": style,
        "audience": audience,
        "domain": "general science",
        "voice": voice_choice,
        "ambient": ambient_choice,
    }

    final_story = None
    forced_chapters = []
    current_progress = 0

    try:
        with requests.post(
            f"{API_BASE}/generate",
            json=payload,
            stream=True,
            timeout=600,
        ) as resp:
            resp.raise_for_status()

            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data:"):
                    continue

                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                event = data.get("event")

                if event == "node_done":
                    msg  = data.get("message", "")
                    node = data.get("node", "")

                    new_pct = _NODE_PROGRESS.get(node, current_progress)
                    current_progress = max(current_progress, new_pct)
                    progress_bar.progress(current_progress)
                    status_box.info(msg if msg else f"Running {node}...")

                    fc = data.get("forced_chapters", [])
                    if fc:
                        forced_chapters = fc
                        warning_box.warning(
                            f"Chapter(s) {[c + 1 for c in fc]} were force-advanced "
                            "after reaching the revision limit."
                        )

                elif event == "done":
                    final_story     = data.get("final_story", "")
                    forced_chapters = data.get("forced_chapters", [])
                    server_audio_url = data.get("audio_url")  # pre-synthesized by server
                    progress_bar.progress(100)
                    if server_audio_url:
                        status_box.success("Story and audio ready!")
                    else:
                        status_box.success("Story ready — generating audio...")

                elif event == "error":
                    progress_bar.empty()
                    st.error(data.get("message", "Unknown error"))
                    st.stop()

    except requests.exceptions.ConnectionError:
        st.error(f"Cannot reach the API at {API_BASE}. Is the server running?")
        st.stop()
    except requests.exceptions.Timeout:
        st.error("The request timed out. Try a shorter duration.")
        st.stop()
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        st.stop()

    if not final_story:
        st.warning("Generation finished but no story was returned.")
        st.stop()

    # Save story to session state so it survives reruns
    st.session_state.final_story = final_story
    st.session_state.forced_chapters = forced_chapters

    # ── Audio: use server-pre-synthesized URL or fall back to explicit POST ──────

    story_placeholder.markdown(final_story)

    # Stop the ambient preview that was playing during generation
    st.components.v1.html(
        "<script>var a=document.getElementById('cs-ambient-preview');if(a){a.pause();a.currentTime=0;}</script>",
        height=0,
    )

    if server_audio_url:
        # Server already synthesized audio in parallel with the done SSE — no extra wait
        st.session_state.audio_url  = f"{API_BASE}{server_audio_url}"
        st.session_state.audio_info = {"audio_url": server_audio_url, "ambient_mixed": ambient_choice}
        status_box.success("Ready.")
    else:
        with st.spinner("Synthesizing narration..."):
            try:
                audio_resp = requests.post(
                    f"{API_BASE}/generate-audio",
                    json={
                        "story_text": final_story,
                        "ambient": ambient_choice,
                        "voice": voice_choice,
                    },
                    timeout=600,
                )
                audio_resp.raise_for_status()
                audio_data = audio_resp.json()
                st.session_state.audio_url  = f"{API_BASE}{audio_data['audio_url']}"
                st.session_state.audio_info = audio_data
                status_box.success("Ready.")
            except Exception as e:
                status_box.warning(f"Audio generation failed: {e}")

# ── Display persisted result ──────────────────────────────────────────────────

if st.session_state.final_story:
    final_story     = st.session_state.final_story
    forced_chapters = st.session_state.forced_chapters

    if forced_chapters:
        st.warning(
            f"Chapter(s) {[c + 1 for c in forced_chapters]} were accepted after "
            "reaching the maximum revision attempts. Quality may vary."
        )

    st.divider()
    st.subheader("Your story")
    st.markdown(final_story)

    st.download_button(
        label="Download as .txt",
        data=final_story,
        file_name=f"{st.session_state.topic[:40].replace(' ', '_')}.txt",
        mime="text/plain",
    )

    if st.session_state.audio_url:
        st.divider()
        st.subheader("Listen")
        st.audio(st.session_state.audio_url, format="audio/mp3")
        info = st.session_state.audio_info
        mins = info.get("duration_seconds", 0) // 60
        st.caption(
            f"Duration: ~{mins} min  |  Ambient: {info.get('ambient_mixed', 'none')}"
        )
