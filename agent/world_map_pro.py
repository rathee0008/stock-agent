"""Pro-style (TradingView/Bloomberg dark) world market map used by pages/13_World_Heatmap.py."""

import plotly.graph_objects as go

BG, PANEL, GRID, TXT, MUTED = "#0b0e14", "#0f1320", "#1c2333", "#e6e9ef", "#7d8590"
UP, DOWN = "#089981", "#f23645"

# Diverging scale: red -> near-background neutral -> green
SCALE = [
    [0.00, "#f23645"], [0.20, "#b22833"], [0.40, "#5c2430"],
    [0.50, "#1e222d"],
    [0.60, "#1d4d3a"], [0.80, "#1f8f5f"], [1.00, "#089981"],
]

# Tiny markets are invisible as polygons; draw them as dots at their centroid.
SMALL = {
    "SGP": (1.35, 103.82), "HKG": (22.32, 114.17), "TWN": (23.7, 121.0),
    "ISR": (31.5, 34.9), "NLD": (52.2, 5.3), "BEL": (50.6, 4.6),
    "CHE": (46.8, 8.2), "DNK": (56.0, 10.0), "AUT": (47.5, 14.5),
}


def world_map(df, lim, center_lon=10, height=400):
    """df columns: iso3, country, index, exchange, price, pct, live (bool), asof."""
    d = df.dropna(subset=["pct"]).reset_index(drop=True)
    live_tag = "<span style='color:#26a69a'>● LIVE</span>"
    shut_tag = f"<span style='color:{MUTED}'>○ Closed · last session</span>"
    hover = [
        f"<b>{r.country}</b>  <span style='color:{MUTED}'>{r.index}</span><br>"
        f"<b>{'▲' if r.pct > 0 else '▼' if r.pct < 0 else '■'} {r.pct:+.2f}%</b><br>"
        f"Price  {r.price:,.2f}<br>{live_tag if bool(r.live) else shut_tag}"
        for r in d.itertuples()
    ]
    half = lim / 2
    fig = go.Figure(go.Choropleth(
        locations=d["iso3"], z=d["pct"], zmin=-lim, zmax=lim, colorscale=SCALE,
        text=hover, hovertemplate="%{text}<extra></extra>",
        marker=dict(line=dict(color=BG, width=0.6)),
        colorbar=dict(
            title=dict(text="1D %", font=dict(color=MUTED, size=11)),
            orientation="h", thickness=8, len=0.45, x=0.5, y=0.02, yanchor="bottom", outlinewidth=0, bgcolor="rgba(0,0,0,0)",
            tickfont=dict(color=MUTED, size=10),
            tickvals=[-lim, -half, 0, half, lim],
            ticktext=[f"≤−{lim:g}", f"−{half:g}", "0", f"+{half:g}", f"≥+{lim:g}"],
        ),
    ))

    sm = d[d["iso3"].isin(SMALL)]
    if len(sm):
        fig.add_trace(go.Scattergeo(
            lat=[SMALL[i][0] for i in sm["iso3"]], lon=[SMALL[i][1] for i in sm["iso3"]],
            mode="markers", showlegend=False,
            marker=dict(size=9, color=sm["pct"], cmin=-lim, cmax=lim, colorscale=SCALE,
                        line=dict(color=TXT, width=1)),
            text=[hover[i] for i in sm.index], hovertemplate="%{text}<extra></extra>",
        ))

    lv = d[d["live"].astype(bool)]
    if len(lv):
        fig.add_trace(go.Scattergeo(
            locations=lv["iso3"], locationmode="ISO-3", mode="markers", showlegend=False,
            marker=dict(size=13, color="rgba(0,0,0,0)", line=dict(color="#26a69a", width=1.6)),
            hoverinfo="skip",
        ))

    fig.update_geos(
        projection_type="natural earth", projection_rotation=dict(lon=center_lon),
        showframe=False, showcoastlines=False, showcountries=True,
        countrycolor="#161b27", countrywidth=0.4, showland=True, landcolor="#141925",
        showocean=True, oceancolor="rgba(0,0,0,0)", showlakes=False, bgcolor="rgba(0,0,0,0)", lataxis_range=[-58, 84],
    )
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TXT), dragmode="pan",
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(color=TXT, size=12)),
    )
    return fig
