"""Shared Nordic Learning Minimalism presentation helpers."""

from __future__ import annotations

from html import escape
from typing import Literal, Sequence

import streamlit as st


_GLOBAL_STYLES = """
<style>
    html,
    body {
        font-family: Inter, "Segoe UI", "Noto Sans", sans-serif;
    }

    [data-testid="stMainBlockContainer"] {
        max-width: 1120px;
        padding-top: 4.5rem;
        padding-bottom: 4rem;
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    [data-testid="stHeading"] h1 {
        letter-spacing: -0.035em;
        line-height: 1.08;
        font-weight: 750;
    }

    [data-testid="stHeading"] h2,
    [data-testid="stHeading"] h3 {
        letter-spacing: -0.02em;
        line-height: 1.2;
    }

    [data-testid="stMarkdownContainer"] p,
    [data-testid="stCaptionContainer"] p {
        line-height: 1.6;
    }

    [data-testid="stCaptionContainer"] {
        font-size: 0.9rem;
        opacity: 0.78;
    }

    [data-testid="stForm"] {
        max-width: 800px;
        border-radius: 1rem;
    }

    [data-testid="stAlert"] {
        border-radius: 0.875rem;
    }

    [data-testid="stMetricValue"] {
        font-size: clamp(1.6rem, 2.1vw, 2rem);
        line-height: 1.15;
    }

    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-tertiary"],
    [data-testid="stFormSubmitButton"] button {
        min-height: 44px;
        font-weight: 650;
    }

    button:focus-visible,
    input:focus-visible,
    textarea:focus-visible,
    [role="combobox"]:focus-visible,
    [data-testid="stRadioOption"]:has(input:focus-visible) {
        outline: 3px solid color-mix(in srgb, #087F74 55%, transparent);
        outline-offset: 2px;
    }

    [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"] {
        display: none;
    }

    [data-testid="stSidebarUserContent"] {
        padding-top: 1.5rem;
    }

    [data-testid="stSidebar"] [data-testid="stRadio"] > label {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

    [data-testid="stSidebar"] [data-testid="stRadioGroup"] {
        gap: 0.25rem;
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"] {
        min-height: 44px;
        width: 100%;
        padding: 0.625rem 0.75rem;
        border: 1px solid transparent;
        border-radius: 0.75rem;
        transition: background-color 120ms ease, border-color 120ms ease;
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {
        background: color-mix(in srgb, #087F74 9%, transparent);
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
        color: inherit;
        background: color-mix(in srgb, #087F74 14%, transparent);
        border-color: color-mix(in srgb, #087F74 28%, transparent);
        font-weight: 700;
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div > div:first-child {
        display: none;
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"] p {
        font-size: 0.96rem;
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"] p::before {
        display: inline-block;
        width: 1.75rem;
        color: inherit;
        font-weight: 750;
    }

    [data-testid="stSidebar"] [data-testid="stRadioOption"]:nth-child(1) p::before { content: "⌂"; }
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:nth-child(2) p::before { content: "✎"; }
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:nth-child(3) p::before { content: "A·a"; }
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:nth-child(4) p::before { content: "◫"; }
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:nth-child(5) p::before { content: "▶"; }
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:nth-child(6) p::before { content: "ⓘ"; }

    .fla-brand {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.25rem;
    }

    .fla-brand-mark {
        display: grid;
        place-items: center;
        width: 2.5rem;
        height: 2.5rem;
        border-radius: 0.75rem;
        color: #ffffff;
        background: #087F74;
        font-size: 1.15rem;
        font-weight: 800;
    }

    .fla-brand-name {
        font-size: 1rem;
        line-height: 1.25;
        font-weight: 750;
    }

    .fla-eyebrow {
        margin: 0 0 0.5rem;
        color: inherit;
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0.11em;
        opacity: 0.82;
        text-transform: uppercase;
    }

    .fla-empty {
        padding: 1.25rem;
        border: 1px dashed color-mix(in srgb, currentColor 24%, transparent);
        border-radius: 1rem;
        background: color-mix(in srgb, #087F74 5%, transparent);
    }

    .fla-empty-title {
        margin: 0 0 0.25rem;
        font-weight: 750;
    }

    .fla-empty-body {
        margin: 0;
        opacity: 0.78;
    }

    .fla-badge {
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 0.2rem 0.625rem;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 750;
    }

    .fla-badge--success {
        color: inherit;
        border: 1px solid color-mix(in srgb, #21805C 44%, transparent);
        background: color-mix(in srgb, #21805C 15%, transparent);
    }

    .fla-badge--warning {
        color: inherit;
        border: 1px solid color-mix(in srgb, #A76A21 44%, transparent);
        background: color-mix(in srgb, #A76A21 16%, transparent);
    }

    .fla-badge--error {
        color: inherit;
        border: 1px solid color-mix(in srgb, #B54743 44%, transparent);
        background: color-mix(in srgb, #B54743 15%, transparent);
    }

    .fla-badge--info {
        color: inherit;
        border: 1px solid color-mix(in srgb, #286F83 44%, transparent);
        background: color-mix(in srgb, #286F83 14%, transparent);
    }

    .fla-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin: 0.25rem 0 0.75rem;
    }

    .fla-chip {
        display: inline-flex;
        align-items: center;
        min-height: 32px;
        padding: 0.25rem 0.7rem;
        border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
        border-radius: 999px;
        background: color-mix(in srgb, #286F83 7%, transparent);
        font-size: 0.9rem;
    }

    @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] {
            padding: 4rem 1rem 3rem;
        }

        [data-testid="stHeading"] h1 {
            font-size: 2rem;
        }

        [data-testid="stForm"] {
            padding: 0.25rem;
        }

        [data-testid="stFormSubmitButton"] button {
            width: 100%;
        }
    }
</style>
"""


def apply_global_styles() -> None:
    """Apply the shared UI layer once per Streamlit rerun."""

    st.html(_GLOBAL_STYLES)


def render_eyebrow(text: str) -> None:
    """Render a compact, accessible page-category label."""

    st.html(f'<p class="fla-eyebrow">{escape(text)}</p>')


def render_empty_state(title: str, body: str) -> None:
    """Render a consistent learner-oriented empty state."""

    st.html(
        '<div class="fla-empty">'
        f'<p class="fla-empty-title">{escape(title)}</p>'
        f'<p class="fla-empty-body">{escape(body)}</p>'
        "</div>"
    )


def render_status_badge(
    label: str,
    *,
    tone: Literal["success", "warning", "error", "info"] = "info",
) -> None:
    """Render a compact status that communicates with text as well as color."""

    st.html(f'<span class="fla-badge fla-badge--{tone}">{escape(label)}</span>')


def render_chips(items: Sequence[str]) -> None:
    """Render short, non-interactive values as readable chips."""

    chips = "".join(f'<span class="fla-chip">{escape(item)}</span>' for item in items)
    st.html(f'<div class="fla-chips">{chips}</div>')
