# helpers/profile_defs.py
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os, io, re, datetime as dt, base64, uuid, csv
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from logging import root
import glob
import urllib.parse
import math
import textwrap
import difflib
import csv, json
import altair as alt
import streamlit.components.v1 as components
import unicodedata
from pathlib import Path
import requests

try:
    import plotly.graph_objects as go
except Exception:
    go = None



####################################################################################
# POSITION ROLES DEFINITIONS AND METRICS
# (metric_col, threshold_percentile, higher_is_better, weight)
####################################################################################

POSITION_ROLES = {
        "CB": {
            "No nonsense CB": [
                ("Successful defensive actions per 90", 70, True, 1.0),
                ("Defensive duels won, %", 60, True, 1.0),
                ("Aerial duels won, %", 65, True, 1.0),
                ("Shots blocked per 90", 60, True, 0.9),
                ("Fouls per 90", 60, False, 0.7),
            ],
            "Aerial dominator": [
                ("Aerial duels per 90", 70, True, 1.0),
                ("Aerial duels won, %", 70, True, 1.0),
                ("Head goals per 90", 60, True, 0.8),
                ("Shots blocked per 90", 55, True, 0.7),
                ("Duels won, %", 55, True, 0.7),
            ],
            "Ball playing CB": [
                ("Passes per 90", 65, True, 1.0),
                ("Accurate passes, %", 60, True, 0.9),
                ("Progressive passes per 90", 65, True, 1.0),
                ("Accurate progressive passes, %", 60, True, 0.9),
                ("Passes to final third per 90", 60, True, 0.8),
                ("Accurate passes to final third, %", 55, True, 0.7),
            ],
            "Line breaker CB": [
                ("Passes to final third per 90", 70, True, 1.0),
                ("Progressive passes per 90", 70, True, 1.0),
                ("Through passes per 90", 55, True, 0.8),
                ("Accurate through passes, %", 55, True, 0.8),
                ("Accurate progressive passes, %", 55, True, 0.7),
            ],
            "Front footed stopper": [
                ("Defensive duels per 90", 70, True, 1.0),
                ("Sliding tackles per 90", 60, True, 0.9),
                ("PAdj Sliding tackles", 60, True, 0.9),
                ("Duels per 90", 65, True, 0.8),
                ("Successful defensive actions per 90", 60, True, 0.8),
            ],
            "Cover CB": [
                ("Interceptions per 90", 70, True, 1.0),
                ("PAdj Interceptions", 70, True, 1.0),
                ("Successful defensive actions per 90", 60, True, 0.8),
                ("Fouls per 90", 60, False, 0.7),
                ("Yellow cards per 90", 60, False, 0.6),
            ],
            "Progressive carrier CB": [
                ("Progressive runs per 90", 65, True, 1.0),
                ("Accelerations per 90", 60, True, 0.9),
                ("Duels won, %", 55, True, 0.7),
                ("Passes per 90", 55, True, 0.6),
                ("Accurate passes, %", 55, True, 0.6),
            ],
            "Clean defender": [
                ("Fouls per 90", 70, False, 1.0),
                ("Yellow cards per 90", 70, False, 0.9),
                ("Red cards per 90", 85, False, 0.7),
                ("Defensive duels won, %", 55, True, 0.6),
                ("Successful defensive actions per 90", 55, True, 0.6),
            ],
        },

        "FB": {
            "Flying fullback": [
                ("Progressive runs per 90", 70, True, 1.0),
                ("Accelerations per 90", 70, True, 1.0),
                ("Crosses per 90", 65, True, 0.9),
                ("Successful attacking actions per 90", 60, True, 0.9),
                ("xA per 90", 55, True, 0.7),
            ],
            "Crossing specialist": [
                ("Crosses per 90", 75, True, 1.0),
                ("Accurate crosses, %", 60, True, 0.9),
                ("Crosses to goalie box per 90", 65, True, 0.8),
                ("Deep completed crosses per 90", 65, True, 0.8),
                ("xA per 90", 55, True, 0.7),
            ],
            "Final third creator FB": [
                ("xA per 90", 65, True, 1.0),
                ("Key passes per 90", 60, True, 0.9),
                ("Passes to penalty area per 90", 60, True, 0.9),
                ("Accurate passes to penalty area, %", 55, True, 0.8),
                ("Deep completions per 90", 60, True, 0.8),
            ],
            "Inverted fullback": [
                ("Passes per 90", 65, True, 1.0),
                ("Forward passes per 90", 60, True, 0.9),
                ("Passes to final third per 90", 65, True, 1.0),
                ("Accurate passes, %", 60, True, 0.8),
                ("Progressive passes per 90", 60, True, 0.9),
                ("Accurate progressive passes, %", 55, True, 0.7),
            ],
            "Build up connector FB": [
                ("Short / medium passes per 90", 70, True, 1.0),
                ("Accurate short / medium passes, %", 65, True, 0.9),
                ("Lateral passes per 90", 65, True, 0.8),
                ("Accurate passes, %", 60, True, 0.8),
                ("Passes per 90", 60, True, 0.7),
            ],
            "Defensive specialist": [
                ("Successful defensive actions per 90", 70, True, 1.0),
                ("Defensive duels won, %", 60, True, 1.0),
                ("Defensive duels per 90", 60, True, 0.9),
                ("Interceptions per 90", 55, True, 0.8),
                ("Fouls per 90", 60, False, 0.8),
                ("Yellow cards per 90", 60, False, 0.7),
            ],
            "Underlapping fullback": [
                ("Passes to penalty area per 90", 60, True, 1.0),
                ("Deep completions per 90", 60, True, 0.9),
                ("Key passes per 90", 55, True, 0.8),
                ("Touches in box per 90", 55, True, 0.8),
                ("xA per 90", 50, True, 0.7),
            ],
            "Ball carrying fullback": [
                ("Progressive runs per 90", 65, True, 1.0),
                ("Dribbles per 90", 60, True, 0.9),
                ("Successful attacking actions per 90", 60, True, 0.8),
                ("Offensive duels per 90", 60, True, 0.8),
                ("Touches in box per 90", 55, True, 0.6),
            ],
        },

        "6": {
            "Ball winner 6": [
                ("Successful defensive actions per 90", 75, True, 1.0),
                ("Defensive duels per 90", 70, True, 1.0),
                ("Defensive duels won, %", 60, True, 0.9),
                ("Interceptions per 90", 65, True, 0.9),
                ("PAdj Interceptions", 65, True, 0.9),
                ("Fouls per 90", 60, False, 0.7),
            ],
            "Screener": [
                ("PAdj Interceptions", 70, True, 1.0),
                ("Successful defensive actions per 90", 65, True, 0.9),
                ("Shots blocked per 90", 60, True, 0.8),
                ("Aerial duels per 90", 55, True, 0.7),
                ("Aerial duels won, %", 55, True, 0.7),
            ],
            "Orchestrator/Controller": [
                ("Passes per 90", 70, True, 1.0),
                ("Accurate passes, %", 65, True, 0.9),
                ("Forward passes per 90", 60, True, 0.8),
                ("Accurate forward passes, %", 60, True, 0.8),
                ("Progressive passes per 90", 60, True, 0.9),
                ("Accurate progressive passes, %", 55, True, 0.7),
            ],
            "Distributor": [
                ("Long passes per 90", 70, True, 1.0),
                ("Accurate long passes, %", 60, True, 0.9),
                ("Average long pass length, m", 60, True, 0.7),
                ("Passes to final third per 90", 60, True, 0.8),
                ("Accurate passes to final third, %", 55, True, 0.7),
            ],
            "Recycler": [
                ("Short / medium passes per 90", 70, True, 1.0),
                ("Accurate short / medium passes, %", 65, True, 1.0),
                ("Back passes per 90", 60, True, 0.6),
                ("Accurate passes, %", 65, True, 0.9),
                ("Fouls per 90", 55, False, 0.6),
            ],
            "Progressive 6": [
                ("Progressive passes per 90", 70, True, 1.0),
                ("Passes to final third per 90", 70, True, 0.9),
                ("Passes to penalty area per 90", 60, True, 0.8),
                ("Smart passes per 90", 60, True, 0.8),
                ("Accurate smart passes, %", 55, True, 0.7),
            ],
        },

        "8": {
            "Box to box 8": [
                ("Successful attacking actions per 90", 60, True, 0.9),
                ("Successful defensive actions per 90", 60, True, 0.9),
                ("Progressive runs per 90", 60, True, 0.9),
                ("Duels per 90", 60, True, 0.8),
                ("Accelerations per 90", 60, True, 0.8),
            ],
            "Ball carrier 8": [
                ("Progressive runs per 90", 70, True, 1.0),
                ("Dribbles per 90", 65, True, 0.9),
                ("Successful dribbles, %", 55, True, 0.8),
                ("Accelerations per 90", 65, True, 0.8),
                ("Fouls suffered per 90", 60, True, 0.7),
            ],
            "Playmaking 8": [
                ("Key passes per 90", 65, True, 1.0),
                ("xA per 90", 60, True, 1.0),
                ("Successful defensive actions per 90", 60, True, 0.9),
                ("Passes to final third per 90", 65, True, 0.9),
                ("Progressive passes per 90", 60, True, 0.8),
            ],
            "Final third runner 8": [
                ("Touches in box per 90", 65, True, 1.0),
                ("Shots per 90", 60, True, 0.9),
                ("xG per 90", 55, True, 0.9),
                ("Progressive runs per 90", 60, True, 0.8),
                ("Accelerations per 90", 60, True, 0.8),
            ],
            "Duel dominant 8": [
                ("Duels per 90", 70, True, 1.0),
                ("Duels won, %", 60, True, 0.9),
                ("Offensive duels won, %", 55, True, 0.7),
                ("Successful defensive actions per 90", 55, True, 0.7),
                ("Fouls per 90", 55, False, 0.6),
            ],
            "Link and circulate 8": [
                ("Passes per 90", 65, True, 1.0),
                ("Accurate passes, %", 65, True, 0.9),
                ("Short / medium passes per 90", 65, True, 0.8),
                ("Accurate short / medium passes, %", 60, True, 0.8),
                ("Second assists per 90", 55, True, 0.6),
            ],
        },

        "10": {
            "Creative 10": [
                ("xA per 90", 70, True, 1.0),
                ("Key passes per 90", 70, True, 1.0),
                ("Shot assists per 90", 65, True, 0.9),
                ("Passes to penalty area per 90", 60, True, 0.8),
                ("Smart passes per 90", 60, True, 0.8),
            ],
            "Half space playmaker": [
                ("Through passes per 90", 65, True, 1.0),
                ("Accurate through passes, %", 55, True, 0.8),
                ("Passes to penalty area per 90", 65, True, 0.9),
                ("Accurate passes to penalty area, %", 55, True, 0.7),
                ("Third assists per 90", 55, True, 0.6),
            ],
            "Goal threat 10": [
                ("xG per 90", 60, True, 1.0),
                ("Shots per 90", 60, True, 0.9),
                ("Touches in box per 90", 55, True, 0.9),
                ("Non-penalty goals per 90", 55, True, 0.8),
                ("Goal conversion, %", 55, True, 0.7),
            ],
            "Box-Crashing 10": [
                ("Progressive runs per 90", 65, True, 1.0),
                ("Accelerations per 90", 65, True, 0.9),
                ("Touches in box per 90", 60, True, 0.8),
                ("Dribbles per 90", 55, True, 0.7),
                ("Fouls suffered per 90", 60, True, 0.7),
            ],
        },

        "WM": {
        "Touchline provider": [
            ("Crosses per 90", 75, True, 1.0),
            ("Accurate crosses, %", 60, True, 0.9),
            ("Crosses to goalie box per 90", 65, True, 0.8),
            ("Deep completed crosses per 90", 65, True, 0.8),
            ("xA per 90", 55, True, 0.7),
        ],
        "Creative wide midfielder": [
            ("Key passes per 90", 65, True, 1.0),
            ("xA per 90", 65, True, 1.0),
            ("Smart passes per 90", 60, True, 0.8),
            ("Passes to final third per 90", 60, True, 0.8),
            ("Shot assists per 90", 60, True, 0.8),
        ],
        "Link and circulate wide": [
            ("Passes per 90", 65, True, 0.9),
            ("Accurate passes, %", 65, True, 0.9),
            ("Short / medium passes per 90", 65, True, 0.9),
            ("Accurate short / medium passes, %", 65, True, 0.9),
            ("Forward passes per 90", 55, True, 0.7),
        ],
        "Progressive wide carrier": [
            ("Progressive runs per 90", 65, True, 1.0),
            ("Dribbles per 90", 60, True, 0.8),
            ("Successful dribbles, %", 55, True, 0.7),
            ("Successful attacking actions per 90", 60, True, 0.8),
            ("Fouls suffered per 90", 60, True, 0.7),
        ],
        "Pseudo Wingback": [
            ("Defensive duels per 90", 60, True, 0.8),
            ("Defensive duels won, %", 55, True, 0.7),
            ("Duels per 90", 60, True, 0.7),
            ("Duels won, %", 55, True, 0.7),
            ("Interceptions per 90", 55, True, 0.6),
        ],
    },

    "WF": {
        "Direct winger": [
            ("Dribbles per 90", 65, True, 0.9),
            ("Successful dribbles, %", 55, True, 0.8),
            ("Progressive runs per 90", 65, True, 0.9),
            ("Crosses per 90", 60, True, 0.8),
            ("Successful attacking actions per 90", 60, True, 0.8),
        ],
        "Inside forward": [
            ("Shots per 90", 65, True, 1.0),
            ("xG per 90", 60, True, 0.9),
            ("Touches in box per 90", 65, True, 1.0),
            ("Non-penalty goals per 90", 55, True, 0.8),
            ("Goal conversion, %", 55, True, 0.7),
        ],
        "Box-crashing carrier": [
            ("Progressive runs per 90", 70, True, 1.0),
            ("Accelerations per 90", 70, True, 0.9),
            ("Dribbles per 90", 60, True, 0.8),
            ("Fouls suffered per 90", 65, True, 0.8),
            ("Touches in box per 90", 55, True, 0.7),
        ],
        "Wide duel monster": [
            ("Offensive duels per 90", 70, True, 1.0),
            ("Offensive duels won, %", 60, True, 0.9),
            ("Duels per 90", 65, True, 0.8),
            ("Duels won, %", 55, True, 0.7),
            ("Successful attacking actions per 90", 55, True, 0.7),
        ],
        "Final third creator": [
            ("Key passes per 90", 60, True, 0.8),
            ("xA per 90", 60, True, 0.8),
            ("Shot assists per 90", 60, True, 0.8),
            ("Passes to penalty area per 90", 55, True, 0.7),
            ("Smart passes per 90", 55, True, 0.7),
        ],
        "Transition Runner": [
            ("Sprints per 90", 65, True, 0.8),
            ("Accelerations per 90", 70, True, 1.0),
            ("Progressive runs per 90", 65, True, 0.9),
            ("Dribbles per 90", 55, True, 0.7),
            ("Shots per 90", 55, True, 0.7),
        ],
    },

        "CF": {
            "Target man": [
                ("Aerial duels per 90", 70, True, 1.0),
                ("Aerial duels won, %", 65, True, 1.0),
                ("Received long passes per 90", 65, True, 0.9),
                ("Duels won, %", 55, True, 0.7),
                ("Touches in box per 90", 55, True, 0.7),
                ("Head goals per 90", 55, True, 0.7),
            ],
            "Box target finisher": [
                ("Touches in box per 90", 70, True, 1.0),
                ("Head goals per 90", 60, True, 0.9),
                ("Aerial duels won, %", 60, True, 0.8),
                ("Shots per 90", 60, True, 0.8),
                ("xG per 90", 60, True, 0.8),
            ],
            "Pressing forward": [
                ("Successful defensive actions per 90", 70, True, 1.0),
                ("Defensive duels per 90", 60, True, 0.9),
                ("Duels per 90", 60, True, 0.8),
                ("Interceptions per 90", 55, True, 0.7),
                ("Fouls per 90", 55, False, 0.6),
            ],
            "Poacher": [
                ("Non-penalty goals per 90", 65, True, 1.0),
                ("xG per 90", 70, True, 1.0),
                ("Touches in box per 90", 70, True, 1.0),
                ("Shots per 90", 65, True, 0.9),
                ("Goal conversion, %", 55, True, 0.7),
            ],
            "Dribbling striker": [
                ("Shots per 90", 75, True, 1.0),
                ("Shots on target, %", 55, True, 0.8),
                ("Successful attacking actions per 90", 60, True, 0.8),
                ("Touches in box per 90", 50, True, 0.7),
                ("Successful dribbles per 90", 55, True, 0.6),
                ("Successful dribbles, %", 55, True, 0.6),
                ("Fouls suffered per 90", 50, True, 0.7),
                ("Progressive runs per 90", 60, True, 0.7),
            ],
            "Link forward": [
                ("Received passes per 90", 65, True, 1.0),
                ("Passes per 90", 55, True, 0.7),
                ("Through passes per 90", 55, True, 0.9),
                ("Passes to final third per 90", 60, True, 0.9),
                ("Progressive passes per 90", 55, True, 0.7),
            ],
            "Creative Striker": [
                ("Assists per 90", 60, True, 0.9),
                ("Key passes per 90", 55, True, 0.8),
                ("xA per 90", 60, True, 0.9),
                ("Progressive passes per 90", 55, True, 0.7),
                ("Passes to penalty area per 90", 55, True, 0.7),
            ],
            "Channel runner": [
                ("Progressive runs per 90", 65, True, 1.0),
                ("Accelerations per 90", 70, True, 0.9),
                ("Fouls suffered per 90", 60, True, 0.7),
                ("Shots per 90", 55, True, 0.7),
                ("Touches in box per 90", 55, True, 0.7),
            ],
        },
    }

#-----------------------------------------------------------------------
# RESPONSIBILITY DEFINITIONS

RESPONSIBILITY_DEFINITIONS = {'1v1 defending': 'Winning contests. Ability to compete in 1v1s and aerials with timing, strength and technique.',
    '1v1 threat': 'Winning contests. Ability to compete in 1v1s and aerials with timing, strength and technique.',
    'Aerial dominance': 'Winning contests. Ability to compete in 1v1s and aerials with timing, strength and technique.',
    'Aggressor': 'Winning contests. Ability to compete in 1v1s and aerials with timing, strength and technique.',
    'Ball carrying': 'Advancing play with carries. Driving through pressure, breaking lines, entering final third.',
    'Ball circulation': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Box defending': 'Penalty area involvement, either attacking the box or defending it, including second ball actions.',
    'Box entries': 'Penalty area involvement, either attacking the box or defending it, including second ball actions.',
    'Box presence': 'Penalty area involvement, either attacking the box or defending it, including second ball actions.',
    'Box threat': 'Penalty area involvement, either attacking the box or defending it, including second ball actions.',
    'Box to box impact': 'Penalty area involvement, either attacking the box or defending it, including second ball actions.',
    'Build up Involvement': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Build up involvement': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Build up security': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Chance creation': 'Creating for others in the final third through passes, combinations and decision making.',
    'Creation': 'Creating for others in the final third through passes, combinations and decision making.',
    'Creativity': 'Creating for others in the final third through passes, combinations and decision making.',
    'Cross delivery': 'Profile defined by creating threat through crosses and deliveries from wide areas.',
    'Defensive duelling': 'Winning contests. Ability to compete in 1v1s and aerials with timing, strength and technique.',
    'Defensive screenning': 'Protecting space and stopping progression. Screening, intercepting, and duels to regain.',
    'Discipline and control': 'Control without needless fouls or cards. Decision making when stepping in and managing risk.',
    'Distribution range': 'Using passing range to progress. Long distribution, switches and forward passing under pressure.',
    'Duelling': 'Winning contests. Ability to compete in 1v1s and aerials with timing, strength and technique.',
    'Final third Impact': 'Creating for others in the final third through passes, combinations and decision making.',
    'Final third Passing': 'Creating for others in the final third through passes, combinations and decision making.',
    'Final third creation': 'Creating for others in the final third through passes, combinations and decision making.',
    'Finishing': 'Converting chances. Shot execution, composure, selection, and finishing variety.',
    'Goal threat': 'Penalty area involvement, either attacking the box or defending it, including second ball actions.',
    'Hold up and Link play': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Link play': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Out of possession work': 'Sustained intensity out of possession. Repeat pressing actions, recoveries and duels.',
    'Progression': 'Profile centred on advancing the team up the pitch through carries and or forward passing.',
    'Shot volume': 'Frequency of shooting actions and ability to generate attempts from open play.',
    'Work rate': 'Sustained intensity out of possession. Repeat pressing actions, recoveries and duels.',
    'Build up involvement ': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Build up Involvement ': 'Connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Defensive screening': 'Protecting space and stopping progression. Screening, intercepting, and duels to regain.',
    'Final third impact': 'Creating for others in the final third through passes, combinations and decision making.',
    'Final third passing': 'Creating for others in the final third through passes, combinations and decision making.',
    'Final third Impact ': 'Creating for others in the final third through passes, combinations and decision making.',
    'Final third Passing ': 'Creating for others in the final third through passes, combinations and decision making.'}

#-----------------------------------------------------------------------
# GLOBAL TRAITS AND RESPONSIBILITIES DEFINITIONS AND METRICS
#-----------------------------------------------------------------------

GLOBAL_TRAITS = {
    "Defensive workhorse": [
        ("Successful defensive actions per 90", 75, True, 1.0),
        ("Duels per 90", 65, True, 0.9),
        ("Defensive duels per 90", 65, True, 0.9),
        ("Interceptions per 90", 60, True, 0.8),
        ("PAdj Interceptions", 60, True, 0.8),
    ],
    "Ball progression threat": [
        ("Progressive passes per 90", 70, True, 1.0),
        ("Progressive runs per 90", 70, True, 1.0),
        ("Passes to final third per 90", 65, True, 0.9),
        ("Accurate progressive passes, %", 55, True, 0.7),
        ("Accelerations per 90", 60, True, 0.7),
    ],
    "Press resistance Dribbler": [
        ("Dribbles per 90", 65, True, 0.9),
        ("Successful dribbles, %", 60, True, 0.9),
        ("Fouls suffered per 90", 65, True, 0.8),
        ("Progressive runs per 90", 60, True, 0.8),
        ("Duels won, %", 55, True, 0.6),
    ],
    "Playmaking passer": [
        ("Key passes per 90", 70, True, 1.0),
        ("xA per 90", 70, True, 1.0),
        ("Smart passes per 90", 65, True, 0.9),
        ("Shot assists per 90", 65, True, 0.8),
        ("Accurate smart passes, %", 55, True, 0.7),
    ],
    "Final third connector": [
        ("Passes to penalty area per 90", 65, True, 1.0),
        ("Accurate passes to penalty area, %", 55, True, 0.8),
        ("Through passes per 90", 60, True, 0.8),
        ("Accurate through passes, %", 55, True, 0.7),
        ("Third assists per 90", 55, True, 0.6),
    ],
    "Box threat": [
        ("Touches in box per 90", 70, True, 1.0),
        ("Shots per 90", 65, True, 0.9),
        ("xG per 90", 65, True, 0.9),
        ("Non-penalty goals per 90", 55, True, 0.8),
        ("Aerial duels won, %", 60, True, 0.6),
    ],
    "Aerial presence": [
        ("Aerial duels per 90", 65, True, 1.0),
        ("Aerial duels won, %", 65, True, 1.0),
        ("Head goals per 90", 55, True, 0.7),
        ("Received long passes per 90", 60, True, 0.7),
        ("Duels won, %", 55, True, 0.6),
    ],
    "Crossing threat": [
        ("Crosses per 90", 75, True, 1.0),
        ("Accurate crosses, %", 60, True, 0.9),
        ("Deep completed crosses per 90", 65, True, 0.8),
        ("Crosses to goalie box per 90", 60, True, 0.7),
        ("xA per 90", 55, True, 0.7),
    ],
    "Transition Runner": [
        ("Accelerations per 90", 75, True, 1.0),
        ("Progressive runs per 90", 65, True, 0.9),
        ("Successful attacking actions per 90", 55, True, 0.7),
        ("Shots per 90", 55, True, 0.6),
        ("Fouls suffered per 90", 60, True, 0.6),
    ],
    "Clean defender": [
        ("Fouls per 90", 70, False, 1.0),
        ("Yellow cards per 90", 70, False, 0.9),
        ("Red cards per 90", 85, False, 0.7),
        ("Defensive duels won, %", 55, True, 0.6),
        ("Successful defensive actions per 90", 55, True, 0.6),
    ],
    "Set piece taker": [
        ("Free kicks per 90", 65, True, 1.0),
        ("Corners per 90", 65, True, 1.0),
        ("Direct free kicks per 90", 55, True, 0.7),
        ("Direct free kicks on target, %", 55, True, 0.7),
    ],
}


ROLE_DEFINITIONS = {
    '1v1 lock FB': 'Full back who shuts down wingers. Strong in isolation defending, body shape, duels and recovery.',
    'Aerial dominator': 'Dominant in the air at both ends. Attacks crosses, wins aerial duels, strong timing and power.',
    'Ball carrier 8': 'Central midfielder who advances play by driving with the ball through pressure and into space.',
    'Ball playing CB': 'Centre back who progresses play with passing and carries, comfortable breaking lines under pressure.',
    'Ball security 10': 'Attacking midfielder who keeps possession under pressure, links play, reduces turnovers.',
    'Ball winner 6': 'Defensive midfielder who breaks play up. High duel and interception volume, protects centre.',
    'Box target finisher': 'Striker who lives in the penalty area. Strong box presence, attacks crosses, high xG locations.',
    'Box to box 8': 'High running central midfielder impacting both boxes. Pressing, carrying and late arrivals.',
    'Build up connector FB': 'Full back who supports first and second phase. Offers angles, keeps circulation, plays inside when needed.',
    'Carry and crash': 'Ball carrying attacker who drives into contact and the box, commits defenders and forces chaos.',
    'Channel runner': 'Forward who threatens depth in channels. Repeated runs behind, stretches centre backs.',
    'Chance creating ten': 'Attacking midfielder who consistently creates shots for others from central pockets.',
    'Clean defender': 'Low risk defender. Stays on feet, times tackles, avoids fouls, wins duels through positioning.',
    'Cover CB': 'Centre back who defends space. Quick to drop, protects depth, sweeps behind a higher line.',
    'Creative Striker': 'Forward who drops to link and create. Combines, plays through balls, still arrives to finish.',
    'Creative wide': 'Wide player who creates more than finishes. Finds pockets, combines, slips passes and crosses.',
    'Creator 10': 'Attacking midfielder who creates chances with final passes, combinations and assists.',
    'Crossing specialist': 'Wide player who creates through delivery. Repeats quality crosses and cut backs from high zones.',
    'Deep distributor': 'Midfield controller who dictates from deeper areas with progressive passing and switches.',
    'Defensive specialist': 'Full back focused on stopping wide threat. Tackling, blocking crosses, managing 1v1s.',
    'Direct winger': 'Wide attacker who plays forward quickly. Attacks space, carries at speed, looks for end product.',
    'Inverted winger': 'Wide attacker who comes inside onto stronger foot to combine, shoot or thread passes.',
    'Link forward': 'Forward who connects midfield to attack. Secure lay offs, wall passes, brings wide players in.',
    'Link play forward': 'Forward who connects play and sets others up rather than only finishing.',
    'No nonsense CB': 'Defence first centre back. Clears danger, wins duels, protects box, keeps decisions simple.',
    'Overlap provider': 'Full back who overlaps regularly to create crossing angles and provide width high up.',
    'Penalty box nine': 'High volume finisher who lives in the box and generates strong expected goal output.',
    'Poacher': 'Box focused striker. Finds space on last line, attacks rebounds and finishes with few touches.',
    'Pressing forward': 'Leads the press from the front. Triggers pressure, forces long balls and creates turnovers.',
    'Progressive full back': 'Full back who progresses play with carries and forward passing, often stepping into midfield.',
    'Target forward': 'Reference style forward with regular aerial involvement and back to goal play.',
    'Target man': 'Reference striker for direct play. Holds up, wins aerials, sets runners and attacks the box.',
    'Touchline winger': 'Holds width to stretch the line. Delivers crosses, isolates full back, attacks outside.',
    'Trigger Happy striker': 'Shoots early and often. Looks for half chances, quick releases, high shot volume mindset.',
    'Underlap connector': 'Full back who underlaps into half spaces to combine and create central access.',
    '1v1 outlet winger': 'Profile centred on advancing the team up the pitch through carries and or forward passing.',
    'Aggressive ball winner': 'Profile defined by aggressive off ball work to win possession high and disrupt build up.',
    'Anchor 6': 'Positionally disciplined 6. Screens the back line, controls space, supports rest defence.',
    'Ball carrier FB': 'Profile centred on advancing the team up the pitch through carries and or forward passing.',
    'Box arriving 10': 'Attacking midfielder who arrives in the area to finish moves, strong timing into the box.',
    'Box threat winger': 'Profile defined by strong penalty area involvement, attacking key spaces and finishing actions.',
    'Counter threat winger': 'Profile centred on advancing the team up the pitch through carries and or forward passing.',
    'Direct runner': 'Profile centred on advancing the team up the pitch through carries and or forward passing.',
    'Deep runner': 'Profile centred on advancing the team up the pitch through carries and or forward passing.',
    'Final third creator': 'Profile defined by creating for others in the final third through passes, combinations and decision making.',
    'Hold up forward': 'Profile defined by connecting phases. Secure receiving, keeping the ball, and linking teammates in build up.',
    'Press trigger': 'Profile defined by aggressive off ball work to win possession high and disrupt build up.',
    'Wide creator': 'Profile defined by creating for others in the final third through passes, combinations and decision making.'
}

TRAIT_DEFINITIONS = {
    'Aerial presence': 'Ability to compete and win aerial duels, both defensively and in the box.',
    'Ball progression threat': 'Carries and passes that consistently move the team upfield and break lines.',
    'Box threat': 'Regular penalty area presence and actions that lead to shots, goals and second balls.',
    'Clean defender': 'Defends with timing and positioning, wins duels without giving away cheap fouls.',
    'Crossing threat': 'Consistent delivery quality and volume from wide areas, including cut backs.',
    'Defensive workhorse': 'High intensity out of possession contributor, covering ground and sustaining pressing work.',
    'Final third connector': 'Links wide and central attackers in the last third with secure combinations and lay offs.',
    'Playmaking passer': 'Creates advantage with through balls, switches and final passes rather than safe circulation.',
    'Press resistance carrier': 'Receives under pressure, protects the ball and escapes with carries or sharp combinations.',
    'Set piece taker': 'Direct involvement as a primary deliverer shooter on dead balls.',
    'Transition Runner': 'Attacks space at speed in transition, stretching the line and arriving early in the box.'
}


#-----------------------------------------------------------------------
# RESPONSIBILITIES DEFINITIONS WITH METRICS AND WEIGHTS FOR EACH POSITION
#-----------------------------------------------------------------------

RESPONSIBILITIES = {
    "CB": {
        "Box defending": [
            ("Aerial duels won, %", True, 0.30),
            ("Aerial duels per 90", True, 0.15),
            ("Shots blocked per 90", True, 0.20),
            ("Interceptions per 90", True, 0.20),
            ("Defensive duels won, %", True, 0.15),
        ],
        "Duelling": [
            ("Defensive duels per 90", True, 0.25),
            ("Defensive duels won, %", True, 0.30),
            ("Duels per 90", True, 0.20),
            ("Duels won, %", True, 0.25),
        ],
        "Sweeping": [
            ("PAdj Interceptions", True, 0.45),
            ("Interceptions per 90", True, 0.30),
            ("Successful defensive actions per 90", True, 0.25),
        ],
        "Aggressor": [
            ("PAdj Sliding tackles", True, 0.35),
            ("Sliding tackles per 90", True, 0.25),
            ("Defensive duels per 90", True, 0.20),
            ("Shots blocked per 90", True, 0.20),
        ],
        "Build up security": [
            ("Accurate passes, %", True, 0.35),
            ("Accurate short / medium passes, %", True, 0.35),
            ("Passes per 90", True, 0.15),
            ("Average pass length, m", True, 0.15),
        ],
        "Progressive distribution": [
            ("Progressive passes per 90", True, 0.35),
            ("Accurate progressive passes, %", True, 0.25),
            ("Passes to final third per 90", True, 0.25),
            ("Through passes per 90", True, 0.15),
        ],
        "Discipline and control": [
            ("Fouls per 90", False, 0.45),
            ("Yellow cards per 90", False, 0.35),
            ("Red cards per 90", False, 0.20),
        ],
    },

    "FB": {
        "Proactive defending": [
            ("Successful defensive actions per 90", True, 0.35),
            ("Defensive duels won, %", True, 0.30),
            ("Interceptions per 90", True, 0.20),
            ("Defensive duels per 90", True, 0.15),
        ],
        "1v1 defending": [
            ("Defensive duels per 90", True, 0.40),
            ("Defensive duels won, %", True, 0.40),
            ("Duels won, %", True, 0.20),
        ],
        "Progression": [
            ("Progressive runs per 90", True, 0.35),
            ("Progressive passes per 90", True, 0.35),
            ("Accurate progressive passes, %", True, 0.30),
        ],
        "Build up involvement": [
            ("Passes per 90", True, 0.30),
            ("Accurate passes, %", True, 0.30),
            ("Short / medium passes per 90", True, 0.20),
            ("Accurate short / medium passes, %", True, 0.20),
        ],
        "Final third creation": [
            ("xA per 90", True, 0.30),
            ("Key passes per 90", True, 0.25),
            ("Shot assists per 90", True, 0.20),
            ("Passes to penalty area per 90", True, 0.25),
        ],
        "Cross delivery": [
            ("Crosses per 90", True, 0.35),
            ("Accurate crosses, %", True, 0.25),
            ("Crosses to goalie box per 90", True, 0.20),
            ("Deep completed crosses per 90", True, 0.20),
        ],
        "Ball carrying": [
            ("Dribbles per 90", True, 0.35),
            ("Successful dribbles, %", True, 0.25),
            ("Accelerations per 90", True, 0.25),
            ("Fouls suffered per 90", True, 0.15),
        ],
        "Discipline and control": [
            ("Fouls per 90", False, 0.50),
            ("Yellow cards per 90", False, 0.35),
            ("Red cards per 90", False, 0.15),
        ],
        "Underlap support": [
        ("Passes to penalty area per 90", True, 1.0),
        ("Deep completions per 90", True, 0.9),
        ("xA per 90", True, 0.9),
        ("Accurate passes to penalty area, %", True, 0.6),
        ],
    },

    "WB": {
        "Wide threat": [
            ("Progressive runs per 90", True, 0.25),
            ("Touches in box per 90", True, 0.25),
            ("Dribbles per 90", True, 0.25),
            ("Shots per 90", True, 0.25),
        ],
        "Wide creation": [
            ("xA per 90", True, 0.25),
            ("Crosses per 90", True, 0.25),
            ("Accurate crosses, %", True, 0.15),
            ("Key passes per 90", True, 0.20),
            ("Passes to penalty area per 90", True, 0.15),
        ],
        "Cross delivery": [
            ("Crosses to goalie box per 90", True, 0.30),
            ("Deep completed crosses per 90", True, 0.25),
            ("Accurate crosses, %", True, 0.25),
            ("xA per 90", True, 0.20),
        ],
        "Transitions": [
            ("Accelerations per 90", True, 0.35),
            ("Progressive runs per 90", True, 0.35),
            ("Fouls suffered per 90", True, 0.30),
        ],
        "Proactive defending": [
            ("Successful defensive actions per 90", True, 0.30),
            ("Defensive duels per 90", True, 0.30),
            ("Defensive duels won, %", True, 0.40),
        ],
        "Build up Involvement": [
            ("Passes per 90", True, 0.30),
            ("Accurate passes, %", True, 0.30),
            ("Forward passes per 90", True, 0.20),
            ("Accurate forward passes, %", True, 0.20),
        ],
        "Discipline and control": [
            ("Fouls per 90", False, 0.50),
            ("Yellow cards per 90", False, 0.35),
            ("Red cards per 90", False, 0.15),
        ],
    },

    "6": {
        "Defensive screenning": [
            ("PAdj Interceptions", True, 0.40),
            ("Interceptions per 90", True, 0.20),
            ("Successful defensive actions per 90", True, 0.25),
            ("Shots blocked per 90", True, 0.15),
        ],
        "Defensive duelling": [
            ("Defensive duels per 90", True, 0.25),
            ("Defensive duels won, %", True, 0.35),
            ("Duels won, %", True, 0.25),
            ("Aerial duels won, %", True, 0.15),
        ],
        "Ball circulation": [
            ("Accurate passes, %", True, 0.35),
            ("Accurate short / medium passes, %", True, 0.35),
            ("Short / medium passes per 90", True, 0.15),
            ("Fouls per 90", False, 0.15),
        ],
        "Progression": [
            ("Progressive passes per 90", True, 0.35),
            ("Accurate progressive passes, %", True, 0.20),
            ("Passes to final third per 90", True, 0.25),
            ("Accurate passes to final third, %", True, 0.20),
        ],
        "Distribution range": [
            ("Passes per 90", True, 0.25),
            ("Long passes per 90", True, 0.25),
            ("Accurate long passes, %", True, 0.25),
            ("Average long pass length, m", True, 0.25),
        ],
        "Final third Impact": [
            ("Passes to penalty area per 90", True, 0.35),
            ("Accurate passes to penalty area, %", True, 0.25),
            ("Through passes per 90", True, 0.25),
            ("Accurate through passes, %", True, 0.15),
        ],
        "Discipline and control": [
            ("Fouls per 90", False, 0.55),
            ("Yellow cards per 90", False, 0.30),
            ("Red cards per 90", False, 0.15),
        ],
    },

    "8": {
        "Box to box impact": [
            ("Successful attacking actions per 90", True, 0.20),
            ("Successful defensive actions per 90", True, 0.20),
            ("Duels per 90", True, 0.20),
            ("Duels won, %", True, 0.20),
            ("Accelerations per 90", True, 0.20),
        ],
        "Progression": [
            ("Progressive runs per 90", True, 0.30),
            ("Progressive passes per 90", True, 0.30),
            ("Passes to final third per 90", True, 0.25),
            ("Accurate progressive passes, %", True, 0.15),
        ],
        "Creation": [
            ("xA per 90", True, 0.30),
            ("Shot assists per 90", True, 0.25),
            ("Key passes per 90", True, 0.25),
            ("Smart passes per 90", True, 0.20),
        ],
        "Final third contribution": [
        ("xA per 90", True, 0.9),
        ("Key passes per 90", True, 0.9),
        ("Passes to penalty area per 90", True, 0.8),
        ("Deep completions per 90", True, 0.7),
        ],
        "Goal threat support": [
            ("Shots per 90", True, 0.8),
            ("xG per 90", True, 0.9),
            ("Touches in box per 90", True, 0.7),
        ],
        "Final third Passing": [
            ("Passes to penalty area per 90", True, 0.35),
            ("Accurate passes to penalty area, %", True, 0.25),
            ("Through passes per 90", True, 0.20),
            ("Accurate through passes, %", True, 0.20),
        ],
        "Box threat": [
            ("Touches in box per 90", True, 0.35),
            ("Shots per 90", True, 0.25),
            ("xG per 90", True, 0.25),
            ("Non-penalty goals per 90", True, 0.15),
        ],
        "Ball carrying": [
            ("Dribbles per 90", True, 0.30),
            ("Successful dribbles, %", True, 0.25),
            ("Progressive runs per 90", True, 0.25),
            ("Fouls suffered per 90", True, 0.20),
        ],
        "Discipline and control": [
            ("Fouls per 90", False, 0.50),
            ("Yellow cards per 90", False, 0.35),
            ("Red cards per 90", False, 0.15),
        ],
    },

    "10": {
        "Creativity": [
            ("xA per 90", True, 0.30),
            ("Key passes per 90", True, 0.25),
            ("Shot assists per 90", True, 0.20),
            ("Smart passes per 90", True, 0.15),
            ("Accurate smart passes, %", True, 0.10),
        ],
        "Passing Threat": [
            ("Passes to final third per 90", True, 0.25),
            ("Passes to penalty area per 90", True, 0.25),
            ("Through passes per 90", True, 0.25),
            ("Accurate through passes, %", True, 0.15),
            ("Deep completions per 90", True, 0.10),
        ],
        "Ball carrying": [
            ("Dribbles per 90", True, 0.35),
            ("Successful dribbles, %", True, 0.25),
            ("Progressive runs per 90", True, 0.25),
            ("Accelerations per 90", True, 0.15),
        ],
        "Goal threat": [
            ("Shots per 90", True, 0.30),
            ("xG per 90", True, 0.35),
            ("Touches in box per 90", True, 0.20),
            ("Non-penalty goals per 90", True, 0.15),
        ],
        "Link play": [
            ("Passes per 90", True, 0.25),
            ("Accurate passes, %", True, 0.25),
            ("Shot assists per 90", True, 0.25),
            ("Second assists per 90", True, 0.15),
            ("Third assists per 90", True, 0.10),
        ],
        "Press Resistance": [
            ("Fouls suffered per 90", True, 0.40),
            ("Successful dribbles, %", True, 0.40),
            ("Accurate progressive passes, %", True, 0.15),
            ("Defensive duels won, %", False, 0.05),
        ],
    },

    "WM": {
        "1v1 threat": [
            ("Dribbles per 90", True, 0.35),
            ("Successful dribbles, %", True, 0.30),
            ("Offensive duels per 90", True, 0.20),
            ("Offensive duels won, %", True, 0.15),
        ],
        "Chance creation": [
            ("xA per 90", True, 0.30),
            ("Key passes per 90", True, 0.25),
            ("Shot assists per 90", True, 0.15),
            ("Crosses per 90", True, 0.15),
            ("Accurate crosses, %", True, 0.15),
        ],
        "Box entries": [
            ("Progressive runs per 90", True, 0.30),
            ("Touches in box per 90", True, 0.30),
            ("Accelerations per 90", True, 0.25),
            ("Fouls suffered per 90", True, 0.15),
        ],
        "Goal threat": [
            ("Shots per 90", True, 0.30),
            ("xG per 90", True, 0.35),
            ("Non-penalty goals per 90", True, 0.20),
            ("Goal conversion, %", True, 0.15),
        ],
        "Cross delivery": [
            ("Crosses per 90", True, 0.30),
            ("Crosses to goalie box per 90", True, 0.25),
            ("Deep completed crosses per 90", True, 0.25),
            ("Accurate crosses, %", True, 0.20),
        ],
        "Work rate": [
            ("Successful defensive actions per 90", True, 0.35),
            ("Defensive duels per 90", True, 0.35),
            ("Duels per 90", True, 0.30),
        ],
    },

    "WF": {
        "Goal threat": [
            ("Non-penalty goals per 90", True, 0.30),
            ("xG per 90", True, 0.35),
            ("Shots per 90", True, 0.20),
            ("Shots on target, %", True, 0.15),
        ],
        "Box presence": [
            ("Touches in box per 90", True, 0.35),
            ("Shots per 90", True, 0.30),
            ("Goal conversion, %", True, 0.20),
            ("Head goals per 90", True, 0.15),
        ],
        "1v1 threat": [
            ("Dribbles per 90", True, 0.35),
            ("Successful dribbles, %", True, 0.30),
            ("Progressive runs per 90", True, 0.20),
            ("Fouls suffered per 90", True, 0.05),
            ("Offensive duels won, %", True, 0.10),
        ],
        "Creation": [
            ("xA per 90", True, 0.30),
            ("Shot assists per 90", True, 0.25),
            ("Key passes per 90", True, 0.20),
            ("Smart passes per 90", True, 0.15),
            ("Passes to penalty area per 90", True, 0.10),
        ],
        "Work rate": [
            ("Successful defensive actions per 90", True, 0.35),
            ("Defensive duels per 90", True, 0.35),
            ("Duels per 90", True, 0.30),
        ],
    },

    "CF": {
        "Finishing": [
            ("Non-penalty goals per 90", True, 0.30),
            ("Goal conversion, %", True, 0.25),
            ("Shots on target, %", True, 0.25),
            ("xG per 90", True, 0.20),
        ],
        "Shot volume": [
            ("Shots per 90", True, 0.40),
            ("Shots on target, %", True, 0.35),
            ("xG per 90", True, 0.30),
        ],
        "Box presence": [
            ("Touches in box per 90", True, 0.40),
            ("Shots per 90", True, 0.20),
            ("Head goals per 90", True, 0.20),
            ("Aerial duels per 90", True, 0.20),
        ],
        "Duelling": [
            ("Aerial duels per 90", True, 0.35),
            ("Aerial duels won, %", True, 0.20),
            ("Offensive duels per 90", True, 0.45),
        ],
        "Hold up and Link play": [
            ("Received passes per 90", True, 0.30),
            ("Received long passes per 90", True, 0.30),
            ("Assists per 90", True, 0.15),
            ("Shot assists per 90", True, 0.15),
            ("Fouls suffered per 90", True, 0.10),
        ],
        "Creativity": [
            ("xA per 90", True, 0.30),
            ("Shot assists per 90", True, 0.30),
            ("Smart passes per 90", True, 0.20),
            ("Key passes per 90", True, 0.20),
        ],
        "Out of possession work": [
            ("Successful defensive actions per 90", True, 0.40),
            ("Defensive duels per 90", True, 0.30),
            ("Interceptions per 90", True, 0.20),
            ("Duels per 90", True, 0.10),
        ],
        "1v1 threat": [
            ("Dribbles per 90", True, 0.35),
            ("Progressive runs per 90", True, 0.25),
            ("Successful attacking actions per 90", True, 0.20),
            ("Fouls suffered per 90", True, 0.10),
            ("Offensive duels won, %", True, 0.10),
        ],
    },

    "TM": {
        "Aerial dominance": [
            ("Aerial duels per 90", True, 0.35),
            ("Aerial duels won, %", True, 0.45),
            ("Received long passes per 90", True, 0.20),
        ],
        "Hold up and Link play": [
            ("Received passes per 90", True, 0.30),
            ("Received long passes per 90", True, 0.30),
            ("Assists per 90", True, 0.15),
            ("Shot assists per 90", True, 0.15),
            ("Fouls suffered per 90", True, 0.10),
        ],
        "Box presence": [
            ("Touches in box per 90", True, 0.35),
            ("Head goals per 90", True, 0.25),
            ("Shots per 90", True, 0.25),
            ("xG per 90", True, 0.15),
        ],
        "Finishing": [
            ("Non-penalty goals per 90", True, 0.30),
            ("Goal conversion, %", True, 0.25),
            ("Shots on target, %", True, 0.25),
            ("xG per 90", True, 0.20),
        ],
        "Discipline and control": [
            ("Fouls per 90", False, 0.50),
            ("Yellow cards per 90", False, 0.35),
            ("Red cards per 90", False, 0.15),
        ],
    },
}

#-----------------------------------------------------------------------
# FUNCTION TO CALCULATE TIER ADJUSTED RATING FROM Z-SCORE
#-----------------------------------------------------------------------    



def calculate_tier_adjusted_rating(z_score, league_tier_label):
    coef = TIER_STRENGTH.get(league_tier_label, 0.50)
    # Map Z-score (-3 to 3) to 1-4 scale with tier weight
    base_rating = 2.5 + (z_score * 0.5)
    return max(1.0, min(4.0, base_rating * coef + (1.0 - coef) * 2.0))

#-----------------------------------------------------------------------
# FUNCTION TO NORMALISE PROFILE KEYS TO ROLE GROUPS
#-----------------------------------------------------------------------

def role_group_from_profile(profile_key: str) -> str:
    """Normalise profile keys into role groups used by ROLES."""
    rg = (profile_key or "").strip().upper()

    # keep your existing normalisations
    if rg == "WB":
        return "FB"

    # do not collapse wide profiles now
    if rg in {"WM", "WF"}:
        return rg

    # legacy support: if anything still returns "W", treat it as WM (safer than WF)
    if rg == "W":
        return "WM"

    # if you do not have a separate TM pack, treat as CF
    if rg == "TM":
        return "CF"

    return rg


#-----------------------------------------------------------------------
# FUNCTION TO DISPLAY A DOT RATING ROW IN STREAMLIT
#-----------------------------------------------------------------------
def _dot_rating_row(label: str, pct: float, *, dots: int = 10) -> None:
    # pct expected 0 to 100
    try:
        v = float(pct)
    except Exception:
        v = float("nan")

    if v != v:  # NaN check
        st.markdown(f"**{label}**  \nNA")
        return

    filled = int(round((max(0.0, min(100.0, v)) / 100.0) * dots))

    on = "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#f59e0b;margin-right:6px'></span>"
    off = "<span style='display:inline-block;width:10px;height:10px;border-radius:50%;border:1px solid #f59e0b;margin-right:6px'></span>"

    dots_html = (on * filled) + (off * (dots - filled))

    st.markdown(
        f"""
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
          <div style="min-width:170px;"><b>{label}</b></div>
          <div style="flex:1;white-space:nowrap;">{dots_html}</div>
          <div style="min-width:40px;text-align:right;">{v:.0f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def norm_col_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())

def _resolve_metric_col(df, wanted: str):
    if wanted in df.columns:
        return wanted

    w = norm_col_name(wanted)
    if not w:
        return None

    for c in df.columns:
        if norm_col_name(c) == w:
            return c

    for c in df.columns:
        nc = norm_col_name(c)
        if w in nc or nc in w:
            return c

    return None

def _to_num(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def _weighted_mean(vals, weights):
    vv = []
    ww = []
    for v, w in zip(vals, weights):
        if v is None:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        vv.append(float(v))
        ww.append(float(w))
    if not vv:
        return float("nan")
    wsum = sum(ww) if sum(ww) > 0 else float(len(vv))
    return float(sum(v * w for v, w in zip(vv, ww)) / wsum)

#-----------------------------------------------------------------------
# FUNCTION TO CALCULATE METRIC PERCENTILE WITHIN A COHORT
#-----------------------------------------------------------------------
def _safe_num(v):
    try:
        x = float(v)
        if math.isnan(x):
            return None
        return x
    except Exception:
        return None

def _percentile_of_value(series: np.ndarray, value: float) -> float:
    if series.size == 0:
        return float("nan")
    return float(np.sum(series <= value) / series.size * 100.0)

def _metric_percentile(cohort_df, metric_col: str, player_val, higher_is_better: bool) -> float:
    if metric_col not in cohort_df.columns:
        return float("nan")
    s_raw = cohort_df[metric_col]
    if s_raw.dtype == object:
        s_raw = s_raw.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)

    s = pd.to_numeric(s_raw, errors="coerce").dropna()

    pv = _safe_num(player_val)
    if s.size == 0 or pv is None:
        return float("nan")

    pct = _percentile_of_value(s, pv)
    return pct if higher_is_better else (100.0 - pct)

#-----------------------------------------------------------------------
# FUNCTION TO COMPUTE RESPONSIBILITY SCORES FOR A PLAYER WITHIN A COHORT
#-----------------------------------------------------------------------
def _compute_responsibility_scores(cohort_df: pd.DataFrame, player_row: pd.Series, profile_key: str):
    spec = RESPONSIBILITIES.get(profile_key)

    out = {}
    breakdown = {}

    for resp_name, metric_list in spec.items():
        pct_vals = []
        weights = []
        per_metric = {}

        for metric_col, higher_is_better, w in metric_list:
            real_col = _resolve_metric_col(cohort_df, metric_col)
            if real_col is None:
                pct = float("nan")
            else:
                pv = _to_num(player_row.get(real_col, None))
                pct = _metric_percentile(cohort_df, real_col, pv, higher_is_better)

            per_metric[metric_col] = pct
            pct_vals.append(pct)
            weights.append(w)

        out[resp_name] = _weighted_mean(pct_vals, weights)
        breakdown[resp_name] = per_metric

    return out, breakdown
#-----------------------------------------------------------------------

def _render_responsibilities_bar(resp_scores: dict):
    if go is None:
        st.caption("Plotly not available, responsibility chart skipped.")
        return

    names = list(resp_scores.keys())
    vals = [
        0.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
        for v in resp_scores.values()
    ]

    order = np.argsort(vals)[::-1]
    names = [names[i] for i in order]
    vals = [vals[i] for i in order]

    # definitions per responsibility bar
    custom = [RESPONSIBILITY_DEFINITIONS.get(n, "Definition not set for this label yet.") for n in names]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=vals,
            y=names,
            orientation="h",
            customdata=custom,
            hovertemplate=(
                "<b>%{y}</b>"
                "<br>%{customdata}"
                "<br><b>Percentile vs cohort</b>: %{x:.0f}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        height=max(260, 28 * len(names)),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(range=[0, 100], title="Percentile vs cohort"),
        yaxis=dict(autorange="reversed"),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

def _render_breakdown_radial(resp_breakdown: dict, *, title: str):
    if go is None:
        return

    metrics = list(resp_breakdown.keys())
    vals = []
    for m in metrics:
        v = resp_breakdown[m]
        if v is None or (isinstance(v, float) and math.isnan(v)):
            vals.append(0.0)
        else:
            vals.append(float(v))

    theta = metrics
    r = vals

    fig = go.Figure()
    fig.add_trace(
        go.Barpolar(
            r=r,
            theta=theta,
            marker_line_width=0.5,
            opacity=0.85,
            hovertemplate="%{theta}: %{r:.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        margin=dict(l=30, r=30, t=40, b=20),
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

####################################################################################
# LEAGUE STRENGTH COEFFICIENTS
####################################################################################

# More separation at the bottom end, so very weak leagues do not sit near "Low Tier".
TIER_STRENGTH = {
    "Top Tier": 1.00,
    "High Tier": 0.85,
    "Middle Tier": 0.70,
    "Low Tier": 0.55,
    "Bottom Tier": 0.40,
    "Very Low Tier": 0.25,
}

# Key must match df["__league"] values: "{nation} T{tier}"
def _build_league_tier_label() -> dict[str, str]:
    # Tier ladders (T1..T5)
    PATTERN_ENGLAND = ["Top Tier", "High Tier", "Low Tier", "Low Tier", "Bottom Tier"]
    PATTERN_BIG5 = ["Top Tier", "Middle Tier", "Low Tier", "Bottom Tier", "Very Low Tier"]
    PATTERN_HIGH = ["High Tier", "Low Tier", "Low Tier", "Bottom Tier", "Very Low Tier"]
    PATTERN_MIDDLE = ["Middle Tier", "Low Tier", "Bottom Tier", "Very Low Tier", "Very Low Tier"]
    PATTERN_LOW = ["Low Tier", "Bottom Tier", "Very Low Tier", "Very Low Tier", "Very Low Tier"]
    PATTERN_BOTTOM = ["Bottom Tier", "Very Low Tier", "Very Low Tier", "Very Low Tier", "Very Low Tier"]
    PATTERN_VERY_LOW = ["Very Low Tier"] * 5

    # Nation grouping
    england = {"England"}  # Championship is strong, so England gets its own ladder

    big5 = {"Italy", "Spain", "Germany", "France"}  # big five but less elite second tiers than England overall

    # Strong outside big five (Opta type profile)
    high = {
        "Portugal", "Belgium",
        "Brazil", "Argentina",
        "United States", "USA", "Mexico",
"Poland",
    }

    # Solid leagues that still need a step down from the above
    middle = {
        "Turkey", "Austria", "Czech Republic", "Dutch",
        "Norway", "Sweden", "Switzerland",
        "Croatia", "Serbia", "Ukraine", "Russia",
        "Japan", "Greece",
    }

    # Decent but clearly below the “middle” group
    low = {
        "Israel", "Cyprus", "Korea", "Australia",
        "Hungary", "Romania", "Saudi",
        "Slovakia", "Slovenia", "Bulgaria", "Scotland",
        "Republic of Ireland", "Iceland", "China"
    }

    # Generally weaker leagues globally
    bottom = {
        "Uruguay", "Chile", "Colombia", "Ecuador", "Peru", "Paraguay", "Venezuela", "Bolivia",
        "Canada", "Costa Rica", "Honduras", "Guatemala", "El Salvador", "Panama", "Jamaica", "Trinidad and Tobago",
        "Iran", "Qatar", "UAE", "United Arab Emirates",
        "New Zealand",
        "South Africa", "Egypt", "Morocco", "Tunisia", "Algeria",
        "Nigeria", "Ghana", "Senegal", "Ivory Coast", "Cameroon",
    }

    # Very weak domestic leagues (big separation from Low)
    very_low = {
        "Mali", "Burkina Faso",
        "Faroe Islands", "Malta", "Northern Ireland",
        "Lithuania", "Latvia", "Estonia",
        "Armenia", "Moldova", "Kosovo", "Kazakhstan", "Bosnia and Herzegovina",
        "Andorra", "Gibraltar", "San Marino", "Liechtenstein",
        "Luxembourg", "Azerbaijan", "Belarus", "Georgia", "North Macedonia", "Montenegro", "Albania",
        "Finland", "Wales",
    }

    label: dict[str, str] = {}

    def _apply(nations: set[str], pattern: list[str]) -> None:
        for nation in nations:
            for i, tier_label in enumerate(pattern, start=1):
                label[f"{nation} T{i}"] = tier_label

    _apply(england, PATTERN_ENGLAND)
    _apply(big5, PATTERN_BIG5)
    _apply(high, PATTERN_HIGH)
    _apply(middle, PATTERN_MIDDLE)
    _apply(low, PATTERN_LOW)
    _apply(bottom, PATTERN_BOTTOM)
    _apply(very_low, PATTERN_VERY_LOW)

    return label


LEAGUE_TIER_LABEL = _build_league_tier_label()


def tier_strength_coef(tier_label: str, default: float = 0.50) -> float:
    return float(TIER_STRENGTH.get(tier_label, default))

#Aliases
ROLES = POSITION_ROLES
TRAITS = GLOBAL_TRAITS
POSITION_RESPONSIBILITIES = RESPONSIBILITIES