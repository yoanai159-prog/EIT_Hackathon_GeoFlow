"""Stand-alone demo of the problem scenario: streamlit run demo_scenario.py"""
from pathlib import Path

import streamlit as st

import page_story
import ui
from core.logic import Settings

ui.setup()
page_story.render(Path(__file__).parent / "data", Settings(critical_fill_pct=20.0, window_weeks=4))
