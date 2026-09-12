"""About page for the Finnish Learning Assistant demo."""

from __future__ import annotations

import streamlit as st


def render_about_page() -> None:
    """Render concise architecture, provenance, and limitation notes."""

    st.title("About")
    st.write(
        "Finnish Learning Assistant is an educational MVP for checking Finnish "
        "grammar, understanding recurring mistakes, looking up words, and practising "
        "targeted grammar topics."
    )
    st.subheader("How the learning loop works")
    st.markdown("**Write → Check → Understand → Remember → Analyze → Practice**")
    st.subheader("Architecture")
    st.write(
        "Streamlit provides the presentation layer. Grammar analysis and exercise "
        "generation use the provider-isolated LLM service; grammar history and "
        "weaknesses are stored locally in SQLite; vocabulary uses a documented "
        "FinnWordNet/UD-derived local index."
    )
    st.subheader("AI and data disclosure")
    st.write(
        "The Phase 5 Logistic Regression model is an experimental synthetic-data "
        "baseline and is not used to override the grammar service. Vocabulary facts "
        "are shown with their source information; generated content is not a dictionary "
        "authority."
    )
    st.subheader("Privacy and limitations")
    st.write(
        "The MVP uses the local demo learner ID `demo_user` and a local runtime database. "
        "It has no authentication and should not be treated as a complete Finnish grammar "
        "checker or dictionary. LLM-reported confidence is not calibrated probability."
    )
