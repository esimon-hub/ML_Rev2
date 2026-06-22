import os
import sys
import pandas as pd

def load_data_from_excel(model, base_path="inputs"):
    """
    Load parameters from Excel files into the Pyomo model.
    """
    
    def _read_or_quit(filename):
        path = os.path.join(base_path, filename)
        if not os.path.exists(path):
            print(f"\n[CRITICAL ERROR] File not found: {path}")
            sys.exit(1)
        return pd.read_excel(path)

    # Helper to map (u,v) to the undirected arc (min, max) in the model
    def normalize_arc(u, v):
        u, v = int(u), int(v)
        if u == v: return None
        a = (u, v) if u < v else (v, u)
        if a not in model.arcs: return None
        return a

    # ==========================================
    # 1. DEFICIT COSTS & DEMAND
    # ==========================================

    # --- Deficit Costs ---
    # We apply this scalar to all zones.
    df = _read_or_quit("cost_deficit_capacity.xlsx")
    val = float(df['value'].iloc[0])
    for s in model.s:
        model.DC_p[s] = val

    # Energy: File 'cost_deficit_energy.xlsx'
    df = _read_or_quit("cost_deficit_energy.xlsx")
    for _, row in df.iterrows():
        s = int(row['s'])
        p = int(row['p'])
        if s in model.s and p in model.p:
            model.DC_e[s, p] = float(row['value'])

    # --- Demand ---
    # File 'demand.xlsx' has s, k, p, value.
    df = _read_or_quit("demand.xlsx")
    for _, row in df.iterrows():
        s = int(row["s"])
        k = int(row["k"])
        p = int(row['p'])
        if s in model.s and k in model.k and p in model.p:
            model.D[s, int(row["k"]), int(row["p"])] = float(row["value"])

    # File 'demand_peak.xlsx' has s, k, value.
    df = _read_or_quit("demand_peak.xlsx")
    for _, row in df.iterrows():
        s = int(row["s"])
        k = int(row["k"])
        if s in model.s and k in model.k:
            model.Dmax[s, int(row["k"])] = float(row["value"])

    # File 'demand_RM.xlsx' is scalar.
    df = _read_or_quit("demand_RM.xlsx")
    model.RM.set_value(float(df.loc[0, "value"]))

    # --- Discount rate (scalar) and per-year discount factors delta_y = 1/(1+r)^(y-1) ---
    df = _read_or_quit("discount_rate.xlsx")
    r = float(df.loc[0, "value"])
    model.disc.set_value(r)
    for y in model.y:
        model.delta[y] = 1.0 / ((1.0 + r) ** (int(y) - 1))

    # ==========================================
    # 2. GENERATION (Mapping & Parameters)
    # ==========================================

    # --- Scenario Probabilities ---
    # Load probabilities only for the ACTIVE scenarios (c in model.c), then renormalize
    # so they sum to 1.0. This lets you run a reduced scenario set (e.g. a single hydro
    # scenario with N_c=1) without distorting the objective: capex is NOT probability-
    # weighted, but opex / penalties / deficits ARE, so the active weights must sum to 1.
    df = _read_or_quit("param_prob.xlsx")
    loaded_prob = {}
    for _, row in df.iterrows():
        c = int(row["c"])
        if c in model.c:
            loaded_prob[c] = float(row["p"])

    prob_sum = sum(loaded_prob.values())
    if prob_sum <= 0:
        print("[CRITICAL ERROR] Active scenario probabilities sum to <= 0. "
              "Check param_prob.xlsx and N_c.")
        sys.exit(1)
    for c, pv in loaded_prob.items():
        model.p_c[c] = pv / prob_sum

    # --- Existing hydro (aggregated by subsystem)
    df = _read_or_quit("existing_hydro_genseries.xlsx")
    for _, row in df.iterrows():
        c = int(row["c"])
        s = int(row["s"])
        k = int(row["k"])
        if c in model.c and s in model.s and k in model.k:
            model.SG_he[c, s, k] = float(row["value"])
    
    df = _read_or_quit("existing_hydro_capseries.xlsx")
    for _, row in df.iterrows():
        c = int(row["c"])
        s = int(row["s"])
        k = int(row["k"])
        if c in model.c and s in model.s and k in model.k:
            model.PD_he[c, s, k] = float(row["value"])

    df = _read_or_quit("existing_hydro_min.xlsx")
    for _, row in df.iterrows():
        s = int(row["s"])
        if s in model.s:
            model.LG_he[s] = float(row["value"])

    df = _read_or_quit("existing_hydro_installed.xlsx")
    for _, row in df.iterrows():
        s = int(row["s"])
        if s in model.s:
            model.EC_he[s] = float(row["value"])

    # --- Planned (committed) hydro (OPTIONAL) ---
    # 'planned_hydro.xlsx' has columns [h, s, capacity_mw, online_year, cf].
    # These are exogenous planner decisions (NOT optimized): project h adds
    # capacity_mw to subsystem s, online from stage year online_year. cf (default
    # 1.0) sets the monthly energy budget and the firm-capacity credit.
    ph_path = os.path.join(base_path, "planned_hydro.xlsx")
    if os.path.exists(ph_path):
        df = pd.read_excel(ph_path)
        n_ph, bad_h, bad_s = 0, [], []
        max_ph = max(model.ph) if len(model.ph) else 0
        for _, row in df.iterrows():
            if pd.isna(row.get("h")) or pd.isna(row.get("s")):
                continue
            h = int(row["h"]); s = int(row["s"])
            if h not in model.ph:
                bad_h.append(h); continue
            if s not in model.s:
                bad_s.append(s); continue
            model.PH_s[s].add(h)
            model.Cap_ph[h] = float(row.get("capacity_mw", 0.0))
            cf = row.get("cf", 1.0)
            model.CF_ph[h] = float(cf) if pd.notna(cf) else 1.0
            ry = int(row["online_year"]) if pd.notna(row.get("online_year")) else 1
            for y in model.y:
                if int(y) >= ry:
                    model.ON_ph[h, y] = 1.0
            n_ph += 1
        print(f"  [info] planned_hydro.xlsx loaded: {n_ph} committed hydro project(s).")
        if bad_h:
            print(f"  [WARN] planned_hydro.xlsx: IGNORED project id(s) {sorted(set(bad_h))} "
                  f"> N_ph={max_ph}. Increase N_PH in base_case_exec.py to match planned_hydro.xlsx.")
        if bad_s:
            print(f"  [WARN] planned_hydro.xlsx: IGNORED invalid subsystem(s) {sorted(set(bad_s))} "
                  f"(valid 1..{max(model.s)}).")
    else:
        print("  [info] No planned_hydro.xlsx found; no committed hydro projects.")

    # --- New hydro (project specific) ---
    df = _read_or_quit("new_hydro.xlsx")
    for _, row in df.iterrows():
        h = int(row["h"])
        s = int(row["s"])
        if h in model.hp and s in model.s:
            model.FC_hp[h] = float(row["FC"])
            model.HP_s[s].add(h)
            model.Nameplate_hp[h] = float(row.get("capacity", 0.0))
    
    df = _read_or_quit("new_hydro_genseries.xlsx")
    for _, row in df.iterrows():
        c = int(row["c"])
        h = int(row["h"])
        k = int(row["k"])
        if c in model.c and h in model.hp and k in model.k:
            model.SG_hp[c, h, k] = float(row["value"])

    df = _read_or_quit("new_hydro_capseries.xlsx")
    for _, row in df.iterrows():
        c = int(row["c"])
        h = int(row["h"])
        k = int(row["k"])
        if c in model.c and h in model.hp and k in model.k:
            model.PD_hp[c, h, k] = float(row["value"])

    df = _read_or_quit("new_hydro_min.xlsx")
    for _, row in df.iterrows():
        h = int(row["h"])
        if h in model.hp:
            model.LG_hp[h] = float(row["value"])
    
    # --- Hydro minimum-generation violation penalty (scalar, $/MWh) ---
    df = _read_or_quit("param_PHG.xlsx")
    model.PHG.set_value(float(df.loc[0, "value"]))

    # --- Existing Renewables ---
    df = _read_or_quit("existing_renewable_capacity.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        re = int(row["re"])
        if s in model.s and re in model.re:
            model.RE_s[s].add(re)  # Map project to zone
            model.EC_re[re] = float(row["EC"])

    df = _read_or_quit("existing_renewable_cc.xlsx")
    for _, row in df.iterrows():
        re = int(row["re"])
        k = int(row["k"])
        if re in model.re and k in model.k:
            model.CC_re[int(row["re"]), int(row["k"])] = float(row["value"])

    df = _read_or_quit("existing_renewable_cf.xlsx")
    for _, row in df.iterrows():
        re = int(row["re"])
        k = int(row["k"])
        p = int(row["p"])
        if re in model.re and k in model.k and p in model.p:
            model.CF_re[int(row["re"]), int(row["k"]), int(row["p"])] = float(row["value"])

    # --- New Renewables ---
    df = _read_or_quit("new_renewable.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        rp = int(row["rp"])
        if s in model.s and rp in model.rp:
            model.RP_s[s].add(rp)
            model.FC_rp[rp] = float(row["FC"])
            ux_val = float(row["UX"])
            model.UX_rp[rp] = ux_val
            model.UY_rp[rp] = float(row["UX_year"]) if "UX_year" in row and pd.notna(row["UX_year"]) else ux_val

    df = _read_or_quit("new_renewable_cc.xlsx")
    for _, row in df.iterrows():
        rp = int(row["rp"])
        k  = int(row["k"])
        if rp in model.rp and k in model.k:
            model.CC_rp[int(row["rp"]), int(row["k"])] = float(row["value"])

    df = _read_or_quit("new_renewable_cf.xlsx")
    for _, row in df.iterrows():
        rp = int(row["rp"])
        k  = int(row["k"])
        p  = int(row["p"])
        if rp in model.rp and k in model.k and p in model.p:
            model.CF_rp[int(row["rp"]), int(row["k"]), int(row["p"])] = float(row["value"])

    # --- Other Existing Renewables ---
    df = _read_or_quit("existing_other_renewable_capacity.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        ue = int(row["ue"])
        if s in model.s and ue in model.ue:
            model.EC_ue[ue] = float(row["EC"])
            model.UE_s[s].add(ue)
    
    df = _read_or_quit("existing_other_renewable_cf.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        ue = int(row["ue"])
        k  = int(row["k"])
        p  = int(row["p"])
        if s in model.s and ue in model.ue and k in model.k and p in model.p:
            model.CF_ue[ue, k, p] = float(row["value"])

    df = _read_or_quit("existing_other_renewable_cc.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        ue = int(row["ue"])
        k  = int(row["k"])
        if s in model.s and ue in model.ue and k in model.k:
             model.CC_ue[ue, k] = float(row["value"])

    # --- Other New Renewables ---
    df = _read_or_quit("new_other_renewable.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        up = int(row["up"])
        if s in model.s and up in model.up:
            model.FC_up[up] = float(row["FC"])
            ux_val = float(row["UX"])
            model.UX_up[up] = ux_val
            model.UY_up[up] = float(row["UX_year"]) if "UX_year" in row and pd.notna(row["UX_year"]) else ux_val
            model.UP_s[s].add(up)

    df = _read_or_quit("new_other_renewable_cf.xlsx")
    for _, row in df.iterrows():
        s   = int(row["s"])
        up  = int(row["up"])
        k   = int(row["k"])
        p   = int(row["p"])
        if s in model.s and up in model.up and k in model.k and p in model.p:
            model.CF_up[up, k, p] = float(row["value"])

    df = _read_or_quit("new_other_renewable_cc.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        up = int(row["up"])
        k  = int(row["k"])
        if s in model.s and up in model.up and k in model.k:
            model.CC_up[up, k] = float(row["value"])

    # --- Existing Thermal ---
    df = _read_or_quit("existing_thermal_capacity.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        te = int(row["te"])
        if s in model.s and te in model.te:
            model.TE_s[s].add(te)
            model.EC_te[te] = float(row["EC"])

    df = _read_or_quit("existing_thermal_min.xlsx")
    for _, row in df.iterrows():
        te = int(row["te"])
        k  = int(row["k"])
        if te in model.te and k in model.k:
            model.LC_te[int(row["te"]), int(row["k"])] = float(row["min_gen_mw"])

    df = _read_or_quit("existing_thermal_VC.xlsx")
    for _, row in df.iterrows():
        te = int(row["te"])
        if te in model.te:
            model.VC_te[int(row["te"])] = float(row["value"])

    # --- Existing-technology retirements (OPTIONAL, one file per technology) ---
    # Each file has columns [<id>, retire_year]. retire_year = the first stage year
    # (1..N_y) in which the unit is NO LONGER available; it operates in years
    # < retire_year and is retired (AV = 0) from retire_year onward. Units not listed
    # (or no file at all) never retire, so this is fully backward-compatible.
    def _load_retirements(filename, id_col, av_param, valid_set, label):
        path = os.path.join(base_path, filename)
        if not os.path.exists(path):
            print(f"  [info] No {filename}; existing {label} never retires.")
            return
        rdf = pd.read_excel(path)
        n, bad_id, bad_year = 0, [], []
        max_id = max(valid_set) if valid_set else 0
        n_y = len(model.y)
        for _, row in rdf.iterrows():
            if pd.isna(row.get(id_col)) or pd.isna(row.get("retire_year")):
                continue
            uid = int(row[id_col])
            ry = int(row["retire_year"])
            if uid not in valid_set:
                bad_id.append(uid)
                continue
            if ry > n_y:
                # Retires after the modelled horizon => never retires within it. Not an
                # error, but flag it so a typo (e.g. a calendar year) isn't missed silently.
                bad_year.append((uid, ry))
            for y in model.y:
                if int(y) >= ry:
                    av_param[uid, y] = 0.0
            n += 1
        print(f"  [info] {filename} loaded: {n} {label} unit(s) retiring.")
        if bad_id:
            print(f"  [WARN] {filename}: IGNORED out-of-range {id_col} id {sorted(set(bad_id))} "
                  f"(valid 1..{max_id}). Increase the {label} count (N_*) in base_case_exec.py.")
        if bad_year:
            print(f"  [WARN] {filename}: retire_year beyond horizon (N_y={n_y}) for "
                  f"{id_col}={[u for u, _ in bad_year]} -> no retirement within the study window.")

    _load_retirements("existing_thermal_retirement.xlsx",          "te", model.AV_te, set(model.te), "thermal")
    _load_retirements("existing_renewable_retirement.xlsx",        "re", model.AV_re, set(model.re), "renewable")
    _load_retirements("existing_other_renewable_retirement.xlsx",  "ue", model.AV_ue, set(model.ue), "other-renewable")
    _load_retirements("existing_hydro_retirement.xlsx",            "s",  model.AV_he, set(model.s),  "hydro")

    # --- New Thermal ---
    # 'new_thermal.xlsx' has s, tp, FC.
    df = _read_or_quit("new_thermal.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        tp = int(row["tp"])
        if s in model.s and tp in model.tp:
            model.TP_s[s].add(tp)
            model.FC_tp[tp] = float(row["FC"])

    df = _read_or_quit("new_thermal_amax.xlsx")
    for _, row in df.iterrows():
        tp = int(row["tp"])
        if tp in model.tp:
            model.A_tp[int(row["tp"])] = float(row["A"])

    df = _read_or_quit("new_thermal_capmax.xlsx")
    for _, row in df.iterrows():
        tp = int(row["tp"])
        if tp in model.tp:
            ux_val = float(row["UX"])
            model.UX_tp[tp] = ux_val
            model.UY_tp[tp] = float(row["UX_year"]) if "UX_year" in row and pd.notna(row["UX_year"]) else ux_val

    df = _read_or_quit("new_thermal_min_factor.xlsx")
    for _, row in df.iterrows():
        tp = int(row["tp"])
        k  = int(row["k"])
        if tp in model.tp and k in model.k:
            model.LF_tp[int(row["tp"]), int(row["k"])] = float(row["min_gen_factor"])

    df = _read_or_quit("new_thermal_VC.xlsx")
    for _, row in df.iterrows():
        tp = int(row["tp"])
        if tp in model.tp:
            model.VC_tp[int(row["tp"])] = float(row["value"])
        
    # --- New Storage ---
    # 'new_storage.xlsx' has s, bt, ....
    df = _read_or_quit("new_storage.xlsx")
    for _, row in df.iterrows():
        s  = int(row["s"])
        bt = int(row["bt"])
        if s in model.s and bt in model.bt:
            model.BT_s[s].add(bt)
            model.FC_bt[bt]  = float(row["FC"])
            model.Eff_bt[bt] = float(row["Eff"])
            model.Dur_bt[bt] = float(row["Duration"])
            ux_val = float(row["UX"])
            model.UX_bt[bt]  = ux_val
            model.UY_bt[bt]  = float(row["UX_year"]) if "UX_year" in row and pd.notna(row["UX_year"]) else ux_val
            model.CC_bt[bt]  = float(row.get("CC", 1.0))


    # ==========================================
    # 3. TRANSMISSION
    # ==========================================

    # --- Transmission costs ---
    df = _read_or_quit("transmission_capex.xlsx")
    for _, row in df.iterrows():
        a = normalize_arc(row["u"], row["v"])
        if a is not None:
            model.FC_tr[a] = float(row["value"])
            if "UX_year" in row and pd.notna(row["UX_year"]):
                model.UY_tr[a] = float(row["UX_year"])
    
    # --- Transmission limits energy ---
    df = _read_or_quit("transmission_existing_energy.xlsx")
    for _, row in df.iterrows():
        u, v = int(row["u"]), int(row["v"])
        k = int(row["k"])
        p = int(row["p"])
        if u in model.s and v in model.s and k in model.k and p in model.p:
            model.UT_e[u, v, k, p] = float(row["value"])

    # --- Transmission limits capacity ---
    df = _read_or_quit("transmission_existing_capacity.xlsx")
    for _, row in df.iterrows():
        u, v = int(row["u"]), int(row["v"])
        k = int(row["k"])
        if u in model.s and v in model.s and k in model.k:
            model.UT_p[u, v, k] = float(row["value"])

    # --- Group Mapping ---
    df = _read_or_quit("group_mapping.xlsx")
    for _, row in df.iterrows():
        ag_id = int(row['ag'])
        u, v = int(row["from_sys"]), int(row["to_sys"])
        if ag_id in model.ag:
            if ag_id not in model.ag_map:
                model.ag_map[ag_id] = []
            model.ag_map[ag_id].append((u, v))
    
    # --- Group Limits (Energy) ---
    df = _read_or_quit("group_limits_energy.xlsx")
    for _, row in df.iterrows():
        ag_id = int(row['ag'])
        k = int(row['k'])
        p = int(row['p'])
        val = float(row['max_mw'])
        if ag_id in model.ag and k in model.k and p in model.p:
            model.AG_Max_e[ag_id, k, p] = val

    # --- Group Limits (Capacity) ---
    df = _read_or_quit("group_limits_capacity.xlsx")
    for _, row in df.iterrows():
        ag_id = int(row['ag'])
        k = int(row['k'])
        val = float(row['max_mw'])
        if ag_id in model.ag and k in model.k:
            model.AG_Max_p[ag_id, k] = val

    # ==========================================
    # 5. GENERAL PARAMETERS
    # ==========================================

    # --- Time Parameters ---
    df = _read_or_quit("param_block_duration.xlsx")
    for _, row in df.iterrows():
        model.d_p[int(row["p"])] = float(row["value"])

    # Hours per month depend only on the month-of-year (1..12) and repeat every year,
    # so the input only needs one year (12 rows, k = 1..12). Tile it across the full
    # horizon (k = 1..N_k) so every modelled month gets its hours regardless of N_y/N_k.
    df = _read_or_quit("param_hours.xlsx")
    hours_by_moy = {}
    for _, row in df.iterrows():
        moy = ((int(row["k"]) - 1) % 12) + 1
        hours_by_moy[moy] = float(row["value"])
    missing = sorted({((int(k) - 1) % 12) + 1 for k in model.k} - hours_by_moy.keys())
    if missing:
        print(f"[CRITICAL ERROR] param_hours.xlsx missing month-of-year value(s): {missing}")
        sys.exit(1)
    for k in model.k:
        model.H[int(k)] = hours_by_moy[((int(k) - 1) % 12) + 1]

    return model