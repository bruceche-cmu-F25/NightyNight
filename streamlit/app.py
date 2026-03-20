import json
import os

import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CountingStars",
    layout="centered",
)

st.title("CountingStars")
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
            ["fire", "rain", "ocean", "woods", "none"],
            index=0,
        )
    with col4:
        voice_choice = st.selectbox(
            "Voice",
            ["Aoede", "Sulafat", "Achernar", "Vindemiatrix", "Umbriel", "Kore", "Charon"],
            index=0,
            help="Aoede=Breezy · Sulafat=Warm · Achernar=Soft · Vindemiatrix=Gentle · Umbriel=Easy-going",
        )

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
                    progress_bar.progress(100)
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

    # ── Auto-generate audio immediately after story ───────────────────────────

    story_placeholder.markdown(final_story)

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
