# fcm_moneyball.py
import streamlit as st
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.decomposition import PCA
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="FCM Moneyball Model", layout="wide")
st.title("⚽ FC Midtjylland Moneyball Scouting Model")

st.markdown("Upload your Belgium1.csv (or similar) with the columns you listed. The app will auto-detect columns and give sensible presets.")

uploaded = st.sidebar.file_uploader("Upload CSV file", type="csv")
min_minutes = st.sidebar.number_input("Minimum minutes filter", min_value=0, value=600, step=50)

if not uploaded:
    st.info("Upload a CSV to get started.")
    st.stop()

df_raw = pd.read_csv(uploaded)
st.success(f"Loaded {df_raw.shape[0]} players with {df_raw.shape[1]} columns")

# Normalise column names for safe access (strip)
df_raw.columns = [c.strip() for c in df_raw.columns]

# Quick checks for required columns
required = ["Player", "Position", "Minutes played", "Market value"]
missing = [c for c in required if c not in df_raw.columns]
if missing:
    st.error(f"Missing required columns: {missing}. Please ensure these exist with exact spelling.")
    st.stop()

# Basic filtering
df = df_raw.copy()
df = df[df["Minutes played"] >= min_minutes].reset_index(drop=True)
st.write(f"Players remaining after minutes filter: {len(df)}")

# Position selection
positions = sorted(df["Position"].dropna().unique().tolist())
selected_pos = st.sidebar.selectbox("Select position", positions)

df_pos = df[df["Position"] == selected_pos].copy()
st.write(f"Players in position {selected_pos}: {len(df_pos)}")
if df_pos.empty:
    st.warning("No players in that position after filters.")
    st.stop()

# Position presets: mapping of positions to recommended metrics and default weights
presets = {
    "Winger": {
        "metrics": [
            "Progressive runs per 90",
            "Dribbles per 90",
            "Crosses per 90",
            "Accurate crosses, %",
            "Pressures per 90" if "Pressures per 90" in df.columns else "Successful attacking actions per 90",
            "Goals per 90",
            "Assists per 90"
        ],
        "desc": "Direct, vertical dribbler who presses and delivers into box"
    },
    "Striker": {
        "metrics": [
            "Goals per 90",
            "Non-penalty goals per 90",
            "xG per 90",
            "Shots per 90",
            "Touches in box per 90",
            "Aerial duels won, %",
            "Pressures per 90" if "Pressures per 90" in df.columns else "Offensive duels per 90"
        ],
        "desc": "Finisher, box presence, pressures last line"
    },
    "Centre Midfielder": {
        "metrics": [
            "Progressive passes per 90",
            "Passes per 90",
            "Accurate passes, %",
            "Forward passes per 90",
            "Accurate forward passes, %",
            "Pressures per 90" if "Pressures per 90" in df.columns else "Defensive duels per 90",
            "Progressive runs per 90"
        ],
        "desc": "Progressive passer, able to press and carry"
    },
    "Centre Back": {
        "metrics": [
            "Defensive duels per 90",
            "Defensive duels won, %",
            "Aerial duels won, %",
            "Interceptions per 90",
            "Conceded goals per 90",
            "Passes per 90",
            "Accurate long passes, %"
        ],
        "desc": "Defensive winning, dominant in air, capable in build"
    },
    "Full Back": {
        "metrics": [
            "Progressive runs per 90",
            "Dribbles per 90",
            "Accurate crosses, %",
            "Defensive duels won, %",
            "Pressures per 90" if "Pressures per 90" in df.columns else "Successful defensive actions per 90",
            "Accurate passes, %"
        ],
        "desc": "Vertical full back who defends and provides width"
    },
    "Goalkeeper": {
        "metrics": [
            "Clean sheets",
            "Save rate, %",
            "xG against per 90",
            "Prevented goals per 90",
            "Exits per 90"
        ],
        "desc": "Shot stopping, command of area, sweeping"
    }
}

# Fallback generic metrics if the exact preset name not in dictionary
preset_key = None
for key in presets:
    if key.lower() in selected_pos.lower() or selected_pos.lower() in key.lower():
        preset_key = key
        break
if preset_key is None:
    # fallback to Centre Midfielder style
    preset_key = "Centre Midfielder"

preset = presets[preset_key]
default_metrics = [m for m in preset["metrics"] if m in df_pos.columns]
if not default_metrics:
    # pick numeric columns as fallback
    numeric_cols = df_pos.select_dtypes(include=[np.number]).columns.tolist()
    default_metrics = numeric_cols[:6]

st.sidebar.markdown(f"Preset: **{preset_key}** — {preset['desc']}")
st.sidebar.write("Preset metrics detected (you can adjust):")
for m in default_metrics:
    st.sidebar.write(f"• {m}")

# Allow user to select metrics (but prefilled with preset)
all_numeric = df_pos.select_dtypes(include=[np.number]).columns.tolist()
selected_metrics = st.sidebar.multiselect("Select metrics to include in FCM Fit (and PCA)", all_numeric, default=default_metrics)

if len(selected_metrics) < 2:
    st.warning("Select at least two numeric metrics.")
    st.stop()

# Standardise metrics per position (z-score)
scaler = StandardScaler()
X = df_pos[selected_metrics].fillna(0).values
X_scaled = scaler.fit_transform(X)
df_scaled = pd.DataFrame(X_scaled, columns=selected_metrics, index=df_pos.index)

# PCA for 2D visualisation
pca = PCA(n_components=2)
pca_coords = pca.fit_transform(X_scaled)
df_pos["PCA1"] = pca_coords[:, 0]
df_pos["PCA2"] = pca_coords[:, 1]

st.subheader("PCA style map")
fig = px.scatter(df_pos, x="PCA1", y="PCA2", hover_name="Player",
                 color="Market value" if "Market value" in df_pos.columns else None,
                 size="Minutes played" if "Minutes played" in df_pos.columns else None)
st.plotly_chart(fig, use_container_width=True)

# Default weights from preset: equal distribution across selected metrics, but prioritise earlier preset metrics slightly
default_weights = {}
if preset_key:
    # give slight priority to first three preset metrics if present
    for m in selected_metrics:
        base = 1.0
        if m in preset["metrics"][:3]:
            base = 1.5
        default_weights[m] = base
# normalise
s = sum(default_weights.values())
for k in default_weights:
    default_weights[k] = default_weights[k] / s

st.sidebar.header("Adjust FCM Fit weights (per metric)")
weights = {}
total = 0.0
for m in selected_metrics:
    w = st.sidebar.slider(f"Weight {m}", 0.0, 2.0, float(default_weights.get(m, 1.0)), 0.05)
    weights[m] = w
    total += w

if total <= 0:
    st.error("Total weight must be greater than zero. Adjust sliders.")
    st.stop()

# normalise weights to sum to 1
for m in weights:
    weights[m] = weights[m] / total

# Compute FCM_Fit as weighted sum of standardised metric values (higher better)
df_pos_f = df_pos.copy()
for idx, m in enumerate(selected_metrics):
    # use scaled values
    df_pos_f[m + "_z"] = df_scaled[m]

df_pos_f["FCM_Fit"] = 0.0
for m, w in weights.items():
    df_pos_f["FCM_Fit"] += df_pos_f[m + "_z"] * w

# Optionally rescale FCM_Fit to 0-100 for readability
mm = MinMaxScaler(feature_range=(0, 100))
df_pos_f["FCM_Fit_norm"] = mm.fit_transform(df_pos_f[["FCM_Fit"]])

# Value index: Fit divided by market value (avoid divide by zero)
if "Market value" in df_pos_f.columns:
    # Convert Market value to numeric if needed (remove currency signs)
    def clean_mv(x):
        try:
            if pd.isna(x):
                return 0.0
            s = str(x).replace("€", "").replace("M", "").replace("m", "").replace(",", "").strip()
            return float(s)
        except:
            try:
                return float(x)
            except:
                return 0.0
    df_pos_f["MarketValueNum"] = df_pos_f["Market value"].apply(clean_mv)
    df_pos_f["ValueIndex"] = df_pos_f["FCM_Fit"] / (df_pos_f["MarketValueNum"] + 1e-6)
else:
    df_pos_f["ValueIndex"] = np.nan

# Show top players by FCM Fit
st.subheader("Top players by FCM Fit (normalised 0-100)")
top_n = st.slider("Number of players to show", 5, 50, 15)
top = df_pos_f.sort_values("FCM_Fit_norm", ascending=False).head(top_n)
cols_show = ["Player", "Team", "Minutes played", "Age", "FCM_Fit_norm"]
if "Market value" in df_pos_f.columns:
    cols_show += ["Market value", "ValueIndex"]
st.dataframe(top[cols_show])

# Show undervalued by ValueIndex if available
if "ValueIndex" in df_pos_f.columns and not df_pos_f["ValueIndex"].isna().all():
    st.subheader("Most undervalued players (high ValueIndex)")
    underv = df_pos_f.sort_values("ValueIndex", ascending=False).head(top_n)
    st.dataframe(underv[cols_show])

# Radar comparison
st.subheader("Radar comparison between two players")
players = df_pos_f["Player"].tolist()
p1 = st.selectbox("Player 1", players, index=0)
p2 = st.selectbox("Player 2", players, index=1 if len(players)>1 else 0)

def build_radar(player):
    row = df_pos_f[df_pos_f["Player"] == player]
    if row.empty:
        return None
    # use minmax scaled raw metric values for radar clarity
    raw = df_pos.loc[row.index, selected_metrics].fillna(0)
    scaler_mm = MinMaxScaler()
    raw_s = scaler_mm.fit_transform(raw)
    return raw_s.flatten().tolist()

r1 = build_radar(p1)
r2 = build_radar(p2)
if r1 is None or r2 is None:
    st.warning("Could not build radar for selected players.")
else:
    fig_r = go.Figure()
    fig_r.add_trace(go.Scatterpolar(r=r1, theta=selected_metrics, fill='toself', name=p1))
    fig_r.add_trace(go.Scatterpolar(r=r2, theta=selected_metrics, fill='toself', name=p2))
    fig_r.update_layout(polar=dict(radialaxis=dict(visible=True)), showlegend=True)
    st.plotly_chart(fig_r, use_container_width=True)

# PCA plot coloured by FCM Fit
st.subheader("PCA by FCM Fit")
fig2 = px.scatter(df_pos_f, x="PCA1", y="PCA2", hover_name="Player",
                  color="FCM_Fit_norm", size="Minutes played")
st.plotly_chart(fig2, use_container_width=True)

# Export results
st.subheader("Export")
export_cols = ["Player", "Team", "Position", "Minutes played", "Age", "Market value", "FCM_Fit", "FCM_Fit_norm", "ValueIndex"] + [m for m in selected_metrics]
export_df = df_pos_f[export_cols].copy()
csv = export_df.to_csv(index=False).encode()
st.download_button("Download results CSV", data=csv, file_name=f"{selected_pos}_fcm_moneyball.csv", mime="text/csv")

st.info("Adjust weights to taste. Use the PCA and radar views to eyeball players who fit the FCM profile but have low market values.")
