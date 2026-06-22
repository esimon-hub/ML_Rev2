###############################################################################
#                                                                             #
#                  INPUT TEMPLATE GENERATOR (HEADERS ONLY)                    #
#                                                                             #
#  Creates every .xlsx file the multistage model reads, with the column       #
#  headers in the exact order data_loader.py expects. No rows of data are     #
#  written — fill them in yourself.                                           #
#                                                                             #
#  Run from anywhere:                                                         #
#      python3 generate_input_templates.py                                    #
#                                                                             #
###############################################################################

import os
import pandas as pd

# Templates are written to the same folder the executors read from (this script's
# directory by default; override with MLIGHT_INPUT_DIR to match base_case_exec.py).
INPUT_DIR = os.environ.get("MLIGHT_INPUT_DIR", os.path.dirname(os.path.abspath(__file__)))

# (filename, [columns in the order they appear in data_loader.py])
TEMPLATES = [
    # ---------- Deficit costs & demand ----------
    ("cost_deficit_capacity.xlsx",       ["value"]),                          # scalar
    ("cost_deficit_energy.xlsx",         ["s", "p", "value"]),
    ("demand.xlsx",                      ["s", "k", "p", "value"]),
    ("demand_peak.xlsx",                 ["s", "k", "value"]),
    ("demand_RM.xlsx",                   ["value"]),                          # scalar
    ("discount_rate.xlsx",               ["value"]),                          # scalar (NEW)
    ("param_PHG.xlsx",                    ["value"]),                          # scalar: hydro min-gen violation penalty ($/MWh)

    # ---------- Scenario probabilities ----------
    ("param_prob.xlsx",                  ["c", "p"]),

    # ---------- Existing hydro ----------
    ("existing_hydro_genseries.xlsx",    ["c", "s", "k", "value"]),
    ("existing_hydro_capseries.xlsx",    ["c", "s", "k", "value"]),
    ("existing_hydro_min.xlsx",          ["s", "value"]),
    ("existing_hydro_installed.xlsx",    ["s", "value"]),
    ("existing_hydro_retirement.xlsx",   ["s", "retire_year"]),   # OPTIONAL: subsystem hydro retired from this year onward

    # ---------- New hydro ----------
    ("new_hydro.xlsx",                   ["h", "s", "FC", "capacity"]),
    ("new_hydro_genseries.xlsx",         ["c", "h", "k", "value"]),
    ("new_hydro_capseries.xlsx",         ["c", "h", "k", "value"]),
    ("new_hydro_min.xlsx",               ["h", "value"]),
    # Planned (committed) hydro: exogenous planner decision, NOT optimized.
    ("planned_hydro.xlsx",               ["h", "s", "capacity_mw", "online_year", "cf"]),

    # ---------- Existing renewables ----------
    ("existing_renewable_capacity.xlsx", ["s", "re", "EC"]),
    ("existing_renewable_cc.xlsx",       ["re", "k", "value"]),
    ("existing_renewable_cf.xlsx",       ["re", "k", "p", "value"]),
    ("existing_renewable_retirement.xlsx", ["re", "retire_year"]),  # OPTIONAL: re retired from this year onward

    # ---------- New renewables ----------
    ("new_renewable.xlsx",               ["s", "rp", "FC", "UX", "UX_year", "tech_type"]),
    ("new_renewable_cc.xlsx",            ["rp", "k", "value"]),
    ("new_renewable_cf.xlsx",            ["rp", "k", "p", "value"]),

    # ---------- Other existing renewables ----------
    ("existing_other_renewable_capacity.xlsx", ["s", "ue", "EC"]),
    ("existing_other_renewable_cf.xlsx",       ["s", "ue", "k", "p", "value"]),
    ("existing_other_renewable_cc.xlsx",       ["s", "ue", "k", "value"]),
    ("existing_other_renewable_retirement.xlsx", ["ue", "retire_year"]),  # OPTIONAL: ue retired from this year onward

    # ---------- Other new renewables ----------
    ("new_other_renewable.xlsx",         ["s", "up", "FC", "UX", "UX_year"]),
    ("new_other_renewable_cf.xlsx",      ["s", "up", "k", "p", "value"]),
    ("new_other_renewable_cc.xlsx",      ["s", "up", "k", "value"]),

    # ---------- Existing thermal ----------
    ("existing_thermal_capacity.xlsx",   ["s", "te", "EC"]),
    ("existing_thermal_min.xlsx",        ["te", "k", "min_gen_mw"]),
    ("existing_thermal_VC.xlsx",         ["te", "value"]),
    ("existing_thermal_retirement.xlsx", ["te", "retire_year"]),  # OPTIONAL: te retired from this stage year onward

    # ---------- New thermal ----------
    ("new_thermal.xlsx",                 ["s", "tp", "FC"]),
    ("new_thermal_amax.xlsx",            ["tp", "A"]),
    ("new_thermal_capmax.xlsx",          ["tp", "UX", "UX_year"]),
    ("new_thermal_min_factor.xlsx",      ["tp", "k", "min_gen_factor"]),
    ("new_thermal_VC.xlsx",              ["tp", "value"]),

    # ---------- New storage ----------
    ("new_storage.xlsx",                 ["s", "bt", "FC", "Eff", "Duration", "UX", "UX_year", "CC"]),

    # ---------- Transmission ----------
    ("transmission_capex.xlsx",          ["u", "v", "value", "UX_year"]),
    ("transmission_existing_energy.xlsx",   ["u", "v", "k", "p", "value"]),
    ("transmission_existing_capacity.xlsx", ["u", "v", "k", "value"]),

    # ---------- Transmission grouping ----------
    ("group_mapping.xlsx",               ["ag", "from_sys", "to_sys"]),
    ("group_limits_energy.xlsx",         ["ag", "k", "p", "max_mw"]),
    ("group_limits_capacity.xlsx",       ["ag", "k", "max_mw"]),

    # ---------- General time parameters ----------
    ("param_block_duration.xlsx",        ["p", "value"]),
    ("param_hours.xlsx",                 ["k", "value"]),   # one year only (k=1..12); tiled across the horizon
]


def main():
    os.makedirs(INPUT_DIR, exist_ok=True)
    print(f"Writing templates to: {INPUT_DIR}\n")

    created = 0
    skipped = 0
    for filename, cols in TEMPLATES:
        path = os.path.join(INPUT_DIR, filename)
        if os.path.exists(path):
            print(f"  [skip ] {filename:<42} (exists)")
            skipped += 1
            continue
        pd.DataFrame(columns=cols).to_excel(path, index=False)
        print(f"  [write] {filename:<42} cols={cols}")
        created += 1

    print(f"\nDone. Created {created} file(s), skipped {skipped} existing file(s).")
    print(f"Total templates expected: {len(TEMPLATES)}")


if __name__ == "__main__":
    main()
