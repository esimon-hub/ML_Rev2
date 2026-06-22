###############################################################################
#                                                                             #
#                       BASE CASE SIMULATION EXECUTOR                         #
#                                                                             #
#  Description:                                                               #
#  This script runs a single-pass "Least-Cost Optimization" of the power      #
#  system. It does NOT enforce a variance (risk) limit, allowing the model    #
#  to find the absolute minimum cost configuration (Unconstrained Opt).       #
#                                                                             #
#  Key Features:                                                              #
#   - Objective: Minimize discounted (Investment + Operation + Deficit Costs) #
#   - Risk Constraint: Relaxed                                                #
#   - Method: Solves the multistage LP model once using HiGHS                 #
#   - Horizon: N_y stages (years), each subdivided into 12 monthly blocks     #
#                                                                             #
###############################################################################

import os
import shutil
import sys
import pandas as pd
from pyomo.environ import value
from pyomo.opt import SolverFactory
from model import create_model_structure, add_constraints
from data_loader import load_data_from_excel
from reports import save_reports

# --- CONFIGURATION ---
# Inputs (.xlsx) live in the same folder as this script; outputs go to ./outputs/.
# To use a different layout, override via the MLIGHT_INPUT_DIR / MLIGHT_OUTPUT_DIR
# environment variables, or edit the two defaults below.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "01.Inputs", "02.Chile")
OUTPUT_DIR = os.path.join(BASE_DIR, "06.Outputs", "06.Chile_k_372")

def clean_previous_results():
    """Deletes all files (and known subdirs) within OUTPUT_DIR without removing the directory itself."""
    if os.path.exists(OUTPUT_DIR):
        print(f"Cleaning files in: {OUTPUT_DIR}")
        try:
            for entry in os.listdir(OUTPUT_DIR):
                entry_path = os.path.join(OUTPUT_DIR, entry)
                if os.path.isfile(entry_path):
                    os.remove(entry_path)
                elif os.path.isdir(entry_path):
                    shutil.rmtree(entry_path)
            print("  [OK] Files deleted.")
        except Exception as e:
            print(f"  [ERROR] Could not delete files: {e}")
            sys.exit(1)
    else:
        os.makedirs(OUTPUT_DIR)

def main():
    # 1. Clean old output files
    clean_previous_results()
    print(f"--- Starting Base Case Simulation ---")

    # 2. Create Model Structure (Empty Sets/Vars)
    # Note: Constraints are NOT created here yet.
    print("1. Building model structure...")
    # Multistage horizon: N_y investment years, each split into 12 monthly operational blocks (k = 1..12*N_y).
    # Inputs (demand, hydro/renewable series, existing transmission) are configured for 3 years (k = 1..36).
    N_Y = 31
    # Number of hydro scenarios. 1 = fast deterministic run on a single hydrology
    # (~10x smaller LP); set to 10 to use the full scenario set in param_prob.xlsx.
    # Probabilities are renormalized to sum to 1.0 over the active scenarios (data_loader).
    N_C = 1
    # Number of planned (committed) hydro projects defined in planned_hydro.xlsx.
    # These are exogenous planner decisions (fixed capacity, fixed online year), not
    # optimization variables. Set to match the rows/ids in planned_hydro.xlsx.
    N_PH = 0
    model = create_model_structure(
        N_s=14, N_k=12 * N_Y, N_p=4, N_hp=0, N_te=42, N_tp=10, N_re=28, N_rp=21, N_ue=28, N_up=20, N_bt=28, N_ag=0,
        N_y=N_Y, N_c=N_C, N_ph=N_PH
    )

    # 3. Load Data (Populate Sets and Parameters)
    print("2. Loading data from Excel...")
    try:
        load_data_from_excel(model, base_path=INPUT_DIR)
    except Exception as e:
        print(f"[CRITICAL ERROR] Data loading failed: {e}")
        sys.exit(1)

    # 4. Construct Constraints (Now that Sets are full)
    print("3. Constructing constraints...")
    add_constraints(model)

    # 5. Initialize solver
    print("4. Solving optimization problem...")
    solver = SolverFactory("highs")
    
    # Solve
    results = solver.solve(model, tee=True) # tee=True shows solver log in console

    # Check status
    term_cond = str(results.solver.termination_condition)
    print(f"\nSolver Status: {term_cond}")

    if term_cond != "optimal":
        print("[WARNING] The solver did not find an optimal solution. Results may be invalid.")
    else:
        obj_val = value(model.obj)
        print(f"Optimal Solution Found! Total Cost: ${obj_val:,.2f}")

    # 6. Generate Reports
    print("5. Generating reports...")
    save_reports(model, results=results, output_dir=OUTPUT_DIR)

    # 7. Generate Renewables Capacity Report (per year increment + cumulative)
    print("6. Generating renewables capacity report...")
    renewables_rows = []

    df_new = pd.read_excel(os.path.join(INPUT_DIR, "new_renewable.xlsx"))
    new_tech_map = dict(zip(df_new['rp'], df_new['tech_type']))

    for rp in model.rp:
        tech = new_tech_map.get(rp, "Unknown")
        cumulative = 0.0
        for y in model.y:
            increment = value(model.x_rp[rp, y])
            cumulative += increment
            renewables_rows.append({
                "id": int(rp),
                "tech_type": tech,
                "year": int(y),
                "increment_mw": increment,
                "cumulative_mw": cumulative,
            })

    df_renewables = pd.DataFrame(renewables_rows)
    renewables_path = os.path.join(OUTPUT_DIR, "renewables.csv")
    df_renewables.to_csv(renewables_path, index=False)
    print(f"  - renewables.csv saved")
    
    print(f"\n--- Simulation Complete ---")
    print(f"Results saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()