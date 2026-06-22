###############################################################################
#                                                                             #
#                       OUTPUT CHART GENERATOR                                #
#                                                                             #
#  Reads the .csv reports produced by base_case_exec.py / reports.py and      #
#  renders a set of basic summary charts as .png images.                      #
#                                                                             #
#  Run AFTER a simulation (the outputs/ folder must already be populated):    #
#      python3 generate_charts.py                                             #
#                                                                             #
#  Images are written to <OUTPUT_DIR>/charts/. The output folder defaults to  #
#  ./outputs (next to this script) and can be overridden with MLIGHT_OUTPUT_DIR #
#  to match base_case_exec.py.                                                #
#                                                                             #
###############################################################################

import os
import sys

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # headless: write files, never open a window
import matplotlib.pyplot as plt

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "06.Outputs", "06.Chile_k_372")
INPUT_DIR = os.path.join(BASE_DIR, "01.Inputs", "02.Chile")
CHART_DIR = os.path.join(BASE_DIR, "06.Outputs", "06.Chile_k_372", "charts")

# Consistent colour + label per technology across every chart. Anything not
# listed falls back to a matplotlib default colour.
TECH_STYLE = {
    "existing_hydro":           ("#1f4e79", "Existing Hydro"),
    "new_hydro":                ("#5b9bd5", "New Hydro"),
    "planned_hydro":            ("#2e75b6", "Planned Hydro"),
    "existing_thermal":         ("#595959", "Existing Thermal"),
    "new_thermal":              ("#a6a6a6", "New Thermal"),
    "existing_renewable":       ("#ed7d31", "Existing Renewable"),
    "new_renewable":            ("#ffc000", "New Renewable"),
    "existing_other_renewable": ("#548235", "Existing Other Renew."),
    "new_other_renewable":      ("#a9d18e", "New Other Renew."),
    "new_battery":              ("#7030a0", "New Battery"),
    "battery_discharge":        ("#7030a0", "Battery Discharge"),
}
# Order used for stacked plots (bottom -> top); unknown techs appended after.
TECH_ORDER = [
    "existing_hydro", "new_hydro", "planned_hydro",
    "existing_thermal", "new_thermal",
    "existing_renewable", "new_renewable",
    "existing_other_renewable", "new_other_renewable",
    "battery_discharge", "new_battery",
]

# Generation technologies that count as energy supply (excludes battery_charge /
# battery_net which are negative / derived and would double-count).
SUPPLY_TECHS = [
    "existing_hydro", "new_hydro", "planned_hydro", "existing_thermal", "new_thermal",
    "existing_renewable", "new_renewable",
    "existing_other_renewable", "new_other_renewable", "battery_discharge",
]


def _style(tech):
    """(color, label) for a tech, with a sensible fallback."""
    if tech in TECH_STYLE:
        return TECH_STYLE[tech]
    return (None, str(tech).replace("_", " ").title())


def _ordered_cols(cols):
    """Order a set of tech column names by TECH_ORDER, unknowns last."""
    known = [t for t in TECH_ORDER if t in cols]
    extra = sorted(c for c in cols if c not in TECH_ORDER)
    return known + extra


def _read(name):
    """Load a report CSV, or return None (with a note) if it is missing/empty."""
    path = os.path.join(OUTPUT_DIR, name)
    if not os.path.exists(path):
        print(f"  [skip ] {name} not found")
        return None
    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"  [skip ] {name} unreadable: {e}")
        return None
    if df.empty:
        print(f"  [skip ] {name} is empty")
        return None
    return df


def _save(fig, name):
    path = os.path.join(CHART_DIR, name)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [write] charts/{name}")


def _stacked_bar(ax, pivot, title, ylabel, xlabel="Year"):
    """Render a stacked bar from a (index x tech) pivot using the tech palette."""
    bottom = None
    x = range(len(pivot.index))
    for tech in _ordered_cols(pivot.columns):
        color, label = _style(tech)
        vals = pivot[tech].values
        ax.bar(x, vals, bottom=bottom, label=label, color=color)
        bottom = vals if bottom is None else bottom + vals
    ax.set_xticks(list(x))
    ax.set_xticklabels([str(i) for i in pivot.index])
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(axis="y", alpha=0.3)


# ---------------------------------------------------------------------------
# 1. Installed capacity mix by year (cumulative MW)
# ---------------------------------------------------------------------------
def chart_capacity_by_year():
    df = _read("capacity.csv")
    if df is None:
        return
    piv = (df.groupby(["year", "tech"])["cumulative_mw"].sum()
             .unstack(fill_value=0.0).sort_index())
    if piv.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 5.5))
    _stacked_bar(ax, piv, "Installed Capacity by Technology (cumulative)", "Capacity (MW)")
    _save(fig, "capacity_by_year.png")


# ---------------------------------------------------------------------------
# 2. Capacity additions (+) and retirements (-) per year (incremental MW)
# ---------------------------------------------------------------------------
def chart_new_capacity_additions():
    df = _read("capacity.csv")
    if df is None:
        return
    # increment_mw is positive for new builds and negative for scheduled
    # retirements of existing units, so a single net-change view shows both:
    # builds above the zero line, retirements (hatched) below it.
    piv = (df.groupby(["year", "tech"])["increment_mw"].sum()
              .unstack(fill_value=0.0).sort_index())
    piv = piv.loc[:, piv.abs().sum(axis=0) > 1e-6]  # drop techs that never change
    if piv.empty:
        print("  [skip ] no capacity changes to plot")
        return

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = list(range(len(piv.index)))
    pos_bottom = [0.0] * len(x)
    neg_bottom = [0.0] * len(x)
    any_retire = False
    for tech in _ordered_cols(piv.columns):
        color, label = _style(tech)
        vals = list(piv[tech].values)
        pos = [v if v > 0 else 0.0 for v in vals]
        neg = [v if v < 0 else 0.0 for v in vals]
        if any(pos):
            ax.bar(x, pos, bottom=pos_bottom, color=color, label=label)
            pos_bottom = [b + v for b, v in zip(pos_bottom, pos)]
        if any(neg):
            any_retire = True
            # retirements: same tech colour, hatched, labelled only if no positive bar
            ax.bar(x, neg, bottom=neg_bottom, color=color, hatch="//",
                   edgecolor="white", label=(None if any(pos) else label))
            neg_bottom = [b + v for b, v in zip(neg_bottom, neg)]
    ax.axhline(0, color="black", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels([str(i) for i in piv.index])
    title = "Capacity Additions (+) and Retirements (−) per Stage Year" if any_retire \
            else "New Capacity Additions per Stage Year"
    ax.set_title(title)
    ax.set_xlabel("Year")
    ax.set_ylabel("Capacity change (MW)")
    if any_retire:
        ax.text(0.99, 0.02, "hatched bars below 0 = retirements",
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=8, color="gray")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "new_capacity_additions.png")


# ---------------------------------------------------------------------------
# 3. Annual generation mix (GWh) + overall share donut
# ---------------------------------------------------------------------------
def chart_generation_mix():
    df = _read("dispatch.csv")
    if df is None:
        return
    gen = df[df["tech"].isin(SUPPLY_TECHS)].copy()
    if gen.empty:
        print("  [skip ] no supply generation to plot")
        return
    gen["gwh"] = gen["gen_mwh"] / 1000.0

    # 3a. Stacked bar by year
    piv = (gen.groupby(["year", "tech"])["gwh"].sum()
              .unstack(fill_value=0.0).sort_index())
    fig, ax = plt.subplots(figsize=(9, 5.5))
    _stacked_bar(ax, piv, "Annual Generation by Technology", "Energy (GWh)")
    _save(fig, "generation_mix_by_year.png")

    # 3b. Overall share donut
    totals = gen.groupby("tech")["gwh"].sum()
    totals = totals[totals > 0]
    if not totals.empty:
        order = _ordered_cols(totals.index)
        totals = totals.reindex(order)
        colors = [_style(t)[0] for t in totals.index]
        labels = [_style(t)[1] for t in totals.index]
        fig, ax = plt.subplots(figsize=(8, 7))
        wedges, _texts, _auto = ax.pie(
            totals.values, colors=colors, labels=None,
            autopct=lambda pct: f"{pct:.0f}%" if pct >= 4 else "",
            pctdistance=0.78, startangle=90,
            wedgeprops=dict(width=0.42, edgecolor="white"),
        )
        ax.set_title("Generation Share over Horizon")
        ax.legend(wedges, labels, loc="center left",
                  bbox_to_anchor=(1.0, 0.5), fontsize=9)
        ax.axis("equal")
        _save(fig, "generation_share.png")


# ---------------------------------------------------------------------------
# 4. System-wide monthly generation stack (GWh by month k)
# ---------------------------------------------------------------------------
def chart_monthly_generation():
    df = _read("dispatch.csv")
    if df is None:
        return
    gen = df[df["tech"].isin(SUPPLY_TECHS)].copy()
    if gen.empty:
        return
    gen["gwh"] = gen["gen_mwh"] / 1000.0
    piv = (gen.groupby(["k", "tech"])["gwh"].sum()
              .unstack(fill_value=0.0).sort_index())
    if piv.empty:
        return
    fig, ax = plt.subplots(figsize=(11, 5.5))
    bottom = None
    x = piv.index.values
    for tech in _ordered_cols(piv.columns):
        color, label = _style(tech)
        vals = piv[tech].values
        ax.fill_between(x, bottom if bottom is not None else 0, vals if bottom is None else bottom + vals,
                        step="mid", color=color, label=label, alpha=0.9)
        bottom = vals if bottom is None else bottom + vals
    ax.set_title("System-wide Monthly Generation by Technology")
    ax.set_xlabel("Month index k (1 = first month of horizon)")
    ax.set_ylabel("Energy (GWh)")
    ax.set_xlim(x.min(), x.max())
    ax.margins(x=0)
    ax.legend(loc="upper left", fontsize=8, ncol=3)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "monthly_generation.png")


# ---------------------------------------------------------------------------
# 5. Deficits per year (energy GWh + peak capacity MW)
# ---------------------------------------------------------------------------
def chart_deficits():
    df = _read("deficits.csv")
    if df is None:
        return
    energy = df[df["type"] == "energy"]
    cap = df[df["type"] == "capacity"]
    e_by_year = (energy.groupby("year")["mwh"].sum() / 1000.0) if not energy.empty else pd.Series(dtype=float)
    # Peak capacity shortfall: largest system-wide monthly value within each year.
    if not cap.empty:
        cap_sys = cap.groupby(["year", "k"])["mw"].sum().reset_index()
        c_by_year = cap_sys.groupby("year")["mw"].max()
    else:
        c_by_year = pd.Series(dtype=float)

    total_def = float(e_by_year.sum()) + float(c_by_year.sum())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    years = sorted(set(e_by_year.index) | set(c_by_year.index))
    axes[0].bar(years, [e_by_year.get(y, 0.0) for y in years], color="#c00000")
    axes[0].set_title("Energy Deficit per Year")
    axes[0].set_xlabel("Year"); axes[0].set_ylabel("Unserved Energy (GWh)")
    axes[0].grid(axis="y", alpha=0.3)
    axes[1].bar(years, [c_by_year.get(y, 0.0) for y in years], color="#ff8c00")
    axes[1].set_title("Peak Capacity Deficit per Year")
    axes[1].set_xlabel("Year"); axes[1].set_ylabel("Peak Shortfall (MW)")
    axes[1].grid(axis="y", alpha=0.3)
    if total_def < 1e-6:
        for ax in axes:
            ax.text(0.5, 0.5, "No deficits\n(demand fully served)",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=12, color="gray")
    _save(fig, "deficits.png")


# ---------------------------------------------------------------------------
# 6. Transmission: top corridors by energy flow + new capacity built
# ---------------------------------------------------------------------------
def chart_transmission():
    df = _read("transmission.csv")
    if df is None:
        return
    df = df.copy()
    df["corridor"] = df["from_s"].astype(int).astype(str) + "-" + df["to_s"].astype(int).astype(str)
    flow = df.groupby("corridor")["flow_mwh"].apply(lambda s: s.abs().sum()) / 1000.0
    flow = flow[flow > 1e-6].sort_values(ascending=True)
    # Built capacity = max cumulative new capacity reached over the horizon.
    built = df.groupby("corridor")["new_capacity_mw"].max()
    built = built[built > 1e-6]

    if flow.empty and built.empty:
        print("  [skip ] no transmission flow or builds to plot")
        return

    n_panels = (1 if not flow.empty else 0) + (1 if not built.empty else 0)
    fig, axes = plt.subplots(1, n_panels, figsize=(6 * n_panels, 5.5), squeeze=False)
    axes = axes[0]
    i = 0
    if not flow.empty:
        top = flow.tail(15)
        axes[i].barh(top.index, top.values, color="#2e75b6")
        axes[i].set_title("Energy Flow by Corridor (top 15, |GWh|)")
        axes[i].set_xlabel("Energy (GWh)"); axes[i].set_ylabel("Corridor (from-to)")
        axes[i].grid(axis="x", alpha=0.3)
        i += 1
    if not built.empty:
        built = built.sort_values()
        axes[i].barh(built.index, built.values, color="#70ad47")
        axes[i].set_title("New Transmission Capacity Built")
        axes[i].set_xlabel("Capacity (MW)"); axes[i].set_ylabel("Corridor (from-to)")
        axes[i].grid(axis="x", alpha=0.3)
    _save(fig, "transmission.png")


# ---------------------------------------------------------------------------
# 7. Renewable build-out (cumulative MW by tech_type over years)
# ---------------------------------------------------------------------------
def chart_renewables_buildout():
    df = _read("renewables.csv")
    if df is None:
        return
    piv = (df.groupby(["year", "tech_type"])["cumulative_mw"].sum()
              .unstack(fill_value=0.0).sort_index())
    if piv.empty or piv.values.sum() < 1e-6:
        print("  [skip ] no renewable build-out to plot")
        return
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for tech in piv.columns:
        ax.plot(piv.index, piv[tech].values, marker="o", label=str(tech))
    ax.set_title("Cumulative New Renewable Capacity by Type")
    ax.set_xlabel("Year"); ax.set_ylabel("Capacity (MW)")
    ax.set_xticks(list(piv.index))
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    _save(fig, "renewables_buildout.png")


# ---------------------------------------------------------------------------
# 8. Battery intraday operation + round-trip energy check
# ---------------------------------------------------------------------------
def _block_hour_widths(n_blocks):
    """Width (hours of the representative day) of each intraday block p=1..n.

    Read from param_block_duration.xlsx (value = fraction of a day) if available;
    otherwise fall back to equal widths summing to 24 h.
    """
    path = os.path.join(INPUT_DIR, "param_block_duration.xlsx")
    try:
        df = pd.read_excel(path).sort_values("p")
        widths = [float(v) * 24.0 for v in df["value"].tolist()[:n_blocks]]
        if len(widths) == n_blocks and abs(sum(widths) - 24.0) < 1.0:
            return widths
    except Exception:
        pass
    return [24.0 / n_blocks] * n_blocks


def chart_battery_intraday():
    bal = _read("balance.csv")
    if bal is None:
        return
    if "Storage Discharge" not in bal.columns or "Storage Charging" not in bal.columns:
        print("  [skip ] balance.csv has no storage columns")
        return

    # System-wide (sum over subsystems) by month k and intraday block p.
    ren_cols = [c for c in ["Existing Renewable", "New Renewable",
                            "Existing Other Renewable", "New Other Renewable"]
                if c in bal.columns]
    agg = bal.groupby(["k", "p"]).agg(
        dis=("Storage Discharge", "sum"),
        ch=("Storage Charging", "sum"),      # already negative
        dem=("Demand", "sum"),
    )
    agg["vre"] = bal.groupby(["k", "p"])[ren_cols].sum().sum(axis=1) if ren_cols else 0.0
    agg = agg.reset_index()

    if agg["dis"].abs().sum() < 1e-6 and agg["ch"].abs().sum() < 1e-6:
        print("  [skip ] no battery activity to plot")
        return

    # Representative day = month with the most battery throughput.
    kbest = int(agg.groupby("k")["dis"].sum().idxmax())
    day = agg[agg["k"] == kbest].sort_values("p")
    year_k = (kbest - 1) // 12 + 1

    blocks = day["p"].tolist()
    widths = _block_hour_widths(len(blocks))
    edges = [0.0]
    for w in widths:
        edges.append(edges[-1] + w)
    lefts = edges[:-1]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    # --- Panel A: intraday charge/discharge across the representative day ---
    axA = axes[0]
    axA.bar(lefts, day["dis"].values, width=widths, align="edge",
            color="#7030a0", label="Discharge (+)", edgecolor="white")
    axA.bar(lefts, day["ch"].values, width=widths, align="edge",
            color="#2e9bd6", label="Charge (-)", edgecolor="white")
    axA.axhline(0, color="black", lw=0.8)
    # Demand on a secondary axis (it dwarfs the battery in MW).
    axD = axA.twinx()
    dem_step = list(day["dem"].values) + [day["dem"].values[-1]]
    axD.step(edges, dem_step, where="post", color="#c00000", lw=2, label="Demand")
    if ren_cols:
        vre_step = list(day["vre"].values) + [day["vre"].values[-1]]
        axD.step(edges, vre_step, where="post", color="#ffa500", lw=2,
                 ls="--", label="Renewable gen")
    axA.set_xlim(0, edges[-1])
    axA.set_xticks(edges)
    axA.set_xticklabels([f"{int(round(e))}h" for e in edges])
    axA.set_title(f"Intraday Battery Operation  (month k={kbest}, year {year_k})")
    axA.set_xlabel("Hour of representative day")
    axA.set_ylabel("Battery power (MW)")
    axD.set_ylabel("Demand / Renewable generation (MW)")
    axD.set_ylim(bottom=0)
    h1, l1 = axA.get_legend_handles_labels()
    h2, l2 = axD.get_legend_handles_labels()
    axA.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)
    axA.grid(axis="y", alpha=0.3)

    # --- Panel B: monthly round-trip check (discharge vs charge energy) ---
    axB = axes[1]
    disp = _read("dispatch.csv")
    eff = None
    if disp is not None and "tech" in disp.columns:
        chg = (-disp[disp["tech"] == "battery_charge"]
               .groupby("k")["gen_mwh"].sum()) / 1000.0      # GWh, positive
        dsg = (disp[disp["tech"] == "battery_discharge"]
               .groupby("k")["gen_mwh"].sum()) / 1000.0
        m = pd.concat([chg.rename("charge"), dsg.rename("discharge")], axis=1).fillna(0.0)
        m = m[(m["charge"] > 1e-9) | (m["discharge"] > 1e-9)]
        if not m.empty:
            axB.scatter(m["charge"], m["discharge"], s=28, color="#7030a0",
                        zorder=3, label="Each month")
            hi = float(max(m["charge"].max(), m["discharge"].max())) * 1.05
            tot_c, tot_d = m["charge"].sum(), m["discharge"].sum()
            eff = tot_d / tot_c if tot_c else None
            axB.plot([0, hi], [0, hi], ls="--", color="gray", lw=1,
                     label="100% (no loss)")
            if eff is not None:
                axB.plot([0, hi], [0, eff * hi], ls="-", color="#c00000", lw=1.5,
                         label=f"round-trip = {eff*100:.1f}%")
            axB.set_xlim(0, hi); axB.set_ylim(0, hi)
    axB.set_title("Daily Round-trip Check (per month)")
    axB.set_xlabel("Monthly charging energy (GWh)")
    axB.set_ylabel("Monthly discharging energy (GWh)")
    axB.legend(loc="upper left", fontsize=8)
    axB.grid(alpha=0.3)

    _save(fig, "battery_intraday.png")


def main():
    if not os.path.isdir(OUTPUT_DIR):
        print(f"[ERROR] Output directory not found: {OUTPUT_DIR}")
        print("Run base_case_exec.py first to generate the CSV reports.")
        sys.exit(1)

    os.makedirs(CHART_DIR, exist_ok=True)
    print(f"Reading reports from: {OUTPUT_DIR}")
    print(f"Writing charts to:    {CHART_DIR}\n")

    charts = [
        chart_capacity_by_year,
        chart_new_capacity_additions,
        chart_generation_mix,
        chart_monthly_generation,
        chart_deficits,
        chart_transmission,
        chart_renewables_buildout,
        chart_battery_intraday,
    ]
    for fn in charts:
        try:
            fn()
        except Exception as e:
            print(f"  [ERROR] {fn.__name__} failed: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
