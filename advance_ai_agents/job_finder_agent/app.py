import streamlit as st
import asyncio
import threading
import logging
from dotenv import load_dotenv
from job_agents import run_analysis

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)



st.set_page_config(
    page_title="Job Searcher Agent",
    page_icon="🔍",
    layout="wide"
)

for key, default in [
    ("is_analyzing", False),
    ("analysis_result", ""),
    ("analysis_error", ""),
    ("shared", None),
    ("search_count", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def run_in_thread(user_profile: str, filters: dict, shared: dict):
    """Runs in background thread. Writes to shared dict (same object as in session_state)."""
    def log(msg: str):
        with shared["lock"]:
            shared["log_messages"].append(msg)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            run_analysis(user_profile, filters, log_callback=log)
        )
        with shared["lock"]:
            shared["result"] = result
    except Exception as e:
        logger.error(f"Error: {e}")
        with shared["lock"]:
            shared["error"] = str(e)
    finally:
        with shared["lock"]:
            shared["done"] = True
        loop.close()


def main():
    st.title("Job Searcher Agent")
    st.markdown("---")

    with st.sidebar:
        st.subheader("Your Profile")
        experience = st.text_area(
            "Experience & Resume",
            placeholder="Paste your resume or describe your work experience, skills, education...",
            height=180,
        )
        motivation = st.text_area(
            "Motivation (optional)",
            placeholder="What kind of role are you looking for? Goals, values, interests...",
            height=100,
        )

        st.subheader("Job Filters")

        sources = st.multiselect(
            "Sources",
            [
                "YC Startup Jobs", "Indeed", "Greenhouse", "Lever", "Ashby",
                "Remote Rocketship", "LinkedIn", "Welcome to the Jungle", "Pinpoint",
                "Jobs Subdomain", "Careers Pages", "People Subdomain", "Talent Subdomain",
                "Wellfound", "Workable", "BreezyHR", "Workday Jobs", "Recruitee",
                "Teamtailor", "SmartRecruiters", "JazzHR", "Jobvite", "iCIMS",
                "Dover", "Builtin", "Glassdoor", "Paylocity", "Keka", "Oracle Cloud",
                "Rippling", "CareerPuck", "TalentReef", "Homerun", "Trakstar",
                "ADP", "Factorial", "TriNet Hire",
                "HelloWork", "Eureka Education", "GGE Edu",
            ],
            default=["YC Startup Jobs", "Indeed"],
        )

        col1, col2 = st.columns(2)
        with col1:
            remote = st.checkbox("Remote only")
        with col2:
            num_results = st.number_input("# Results", min_value=1, max_value=20, value=5)

        location = st.text_input(
            "Preferred location",
            placeholder="e.g. New York, London, EU...",
        )

        experience_level = st.selectbox(
            "Experience level",
            ["Any", "Junior", "Mid", "Senior", "Lead / Staff"],
        )

        period = st.selectbox(
            "Posted within",
            ["Any", "Last 24h", "Last week", "Last month"],
        )

        salary_range = st.text_input(
            "Expected salary (optional)",
            placeholder="e.g. $80k–$120k, €60k+",
        )

        if st.session_state.is_analyzing:
            st.info("Search in progress...")

        clicked = st.button(
            "Find Jobs",
            type="primary",
            disabled=st.session_state.is_analyzing,
        )

        if clicked:
            if not experience:
                st.error("Please describe your experience")
                return
            if not sources:
                st.error("Please select at least one source")
                return

            user_profile = experience
            if motivation:
                user_profile += f"\n\nMotivation:\n{motivation}"

            filters = {
                "sources": sources,
                "remote": remote,
                "num_results": int(num_results),
                "location": location,
                "experience_level": experience_level,
                "period": period,
                "salary_range": salary_range,
            }

            # Reset all state for a fresh search
            st.session_state.analysis_result = ""
            st.session_state.analysis_error = ""
            st.session_state.shared = None
            st.session_state.search_count += 1

            # Create shared dict — stored in session_state so it survives reruns
            shared = {"log_messages": [], "result": "", "error": "", "done": False, "lock": threading.Lock()}
            st.session_state.shared = shared
            st.session_state.is_analyzing = True

            threading.Thread(
                target=run_in_thread,
                args=(user_profile, filters, shared),
                daemon=True,
            ).start()
            st.rerun()

    # Progress block — uses fragment so only this section reruns (no tab flicker)
    @st.fragment(run_every=0.5)
    def show_progress():
        if not st.session_state.is_analyzing or not st.session_state.shared:
            return
        shared = st.session_state.shared

        with shared["lock"]:
            messages = list(shared["log_messages"])
            done = shared["done"]
            result = shared["result"]
            error = shared["error"]

        with st.container(border=True):
            st.caption("Progress")
            for msg in messages:
                st.write(f"✓ {msg}")
            if not done:
                st.write("⏳ Working...")

        if done:
            st.session_state.is_analyzing = False
            st.session_state.analysis_result = result
            st.session_state.analysis_error = error
            st.rerun()

    show_progress()

    if st.session_state.analysis_error:
        st.error(st.session_state.analysis_error)

    if st.session_state.analysis_result:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.subheader("Results")
        with col2:
            st.download_button(
                label="Download MD",
                data=st.session_state.analysis_result,
                file_name="job_search_results.md",
                mime="text/markdown",
            )
        st.markdown(st.session_state.analysis_result)


if __name__ == "__main__":
    main()
