import os
import pandas as pd
from pyomo.environ import value 

def _val(x):
    """Helper to safely extract value from Pyomo variable/param."""
    v = getattr(x, "value", x)
    return 0.0 if v is None else float(v)

def save_reports(model, results=None, output_dir="outputs"):
    """
    Generates all model reports with updated sign conventions for Balance.
    
    For operational variables (generation, flows, deficits), reports contain:
    - Expected values (probability-weighted averages across scenarios)
    - Scenario-specific reports are saved separately
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Generating reports in: {output_dir}")

    # Pre-compute scenario probabilities
    prob = {c: _val(model.p_c[c]) for c in model.c}

    # =========================
    # 1. CAPACITY REPORT (Investment decisions per stage year)
    # =========================
    # Existing assets repeat for every year (always installed). New investments report
    # both the incremental build in year y and the cumulative installed capacity.
    cap_rows = []

    years = list(model.y)

    def _cum(var, idx_prefix, y):
        return sum(_val(var[idx_prefix + (yp,)]) for yp in years if yp <= y)

    for s in model.s:
        # Existing assets (availability reflects scheduled retirements; AV in [0,1])
        val_he = _val(model.EC_he[s])
        if val_he > 0:
            prev = val_he
            for y in years:
                avail = val_he * _val(model.AV_he[s, y])
                cap_rows.append({"subsystem": s, "tech": "existing_hydro", "id": 0,
                                 "year": int(y), "increment_mw": avail - prev,
                                 "cumulative_mw": avail})
                prev = avail

        # Planned (committed) hydro: exogenous capacity phased in by online year.
        if s in model.PH_s:
            for ph in model.PH_s[s]:
                cap = _val(model.Cap_ph[ph])
                prev = 0.0
                for y in years:
                    online = cap * _val(model.ON_ph[ph, y])
                    cap_rows.append({"subsystem": s, "tech": "planned_hydro", "id": int(ph),
                                     "year": int(y),
                                     "increment_mw": online - prev,  # positive in commissioning year
                                     "cumulative_mw": online})
                    prev = online

        if s in model.TE_s:
            for te in model.TE_s[s]:
                cap = _val(model.EC_te[te])
                prev = cap
                for y in years:
                    # Available capacity reflects scheduled retirements (AV_te in [0,1]).
                    avail = cap * _val(model.AV_te[te, y])
                    cap_rows.append({"subsystem": s, "tech": "existing_thermal", "id": int(te),
                                     "year": int(y),
                                     "increment_mw": avail - prev,  # negative in the retirement year
                                     "cumulative_mw": avail})
                    prev = avail

        if s in model.RE_s:
            for re in model.RE_s[s]:
                cap = _val(model.EC_re[re])
                prev = cap
                for y in years:
                    avail = cap * _val(model.AV_re[re, y])
                    cap_rows.append({"subsystem": s, "tech": "existing_renewable", "id": int(re),
                                     "year": int(y), "increment_mw": avail - prev,
                                     "cumulative_mw": avail})
                    prev = avail

        if s in model.UE_s:
            for ue in model.UE_s[s]:
                cap = _val(model.EC_ue[ue])
                prev = cap
                for y in years:
                    avail = cap * _val(model.AV_ue[ue, y])
                    cap_rows.append({"subsystem": s, "tech": "existing_other_renewable", "id": int(ue),
                                     "year": int(y), "increment_mw": avail - prev,
                                     "cumulative_mw": avail})
                    prev = avail

        # New investments per stage year
        if s in model.HP_s:
            for h in model.HP_s[s]:
                nameplate = _val(model.Nameplate_hp[h])
                for y in years:
                    inc_frac = _val(model.x_hp[h, y])
                    cum_frac = _cum(model.x_hp, (h,), y)
                    if cum_frac > 0.001 or inc_frac > 0.001:
                        cap_rows.append({
                            "subsystem": s, "tech": "new_hydro", "id": int(h), "year": int(y),
                            "increment_mw": inc_frac * nameplate,
                            "cumulative_mw": cum_frac * nameplate,
                            "x_hp_frac_cum": round(cum_frac, 4),
                        })

        if s in model.TP_s:
            for tp in model.TP_s[s]:
                for y in years:
                    cap_rows.append({"subsystem": s, "tech": "new_thermal", "id": int(tp), "year": int(y),
                                     "increment_mw": _val(model.x_tp[tp, y]),
                                     "cumulative_mw": _cum(model.x_tp, (tp,), y)})

        if s in model.RP_s:
            for rp in model.RP_s[s]:
                for y in years:
                    cap_rows.append({"subsystem": s, "tech": "new_renewable", "id": int(rp), "year": int(y),
                                     "increment_mw": _val(model.x_rp[rp, y]),
                                     "cumulative_mw": _cum(model.x_rp, (rp,), y)})

        if s in model.UP_s:
            for up in model.UP_s[s]:
                for y in years:
                    cap_rows.append({"subsystem": s, "tech": "new_other_renewable", "id": int(up), "year": int(y),
                                     "increment_mw": _val(model.x_up[up, y]),
                                     "cumulative_mw": _cum(model.x_up, (up,), y)})

        if s in model.BT_s:
            for bt in model.BT_s[s]:
                for y in years:
                    cap_rows.append({"subsystem": s, "tech": "new_battery", "id": int(bt), "year": int(y),
                                     "increment_mw": _val(model.x_bt[bt, y]),
                                     "cumulative_mw": _cum(model.x_bt, (bt,), y)})

    pd.DataFrame(cap_rows).to_csv(os.path.join(output_dir, "capacity.csv"), index=False)
    print("  - capacity.csv saved")

    # =========================
    # 2. DISPATCH REPORT (Expected values across scenarios)
    # =========================
    disp_rows = []
    time_weights = {(k, p): _val(model.H[k]) * _val(model.d_p[p]) for k in model.k for p in model.p}

    for s in model.s:
        for k in model.k:
            year_k = int(model.year_of_k[k])
            for p in model.p:
                h_factor = time_weights[(k, p)]

                def add_row(tech, uid, val, _y=year_k):
                    disp_rows.append({
                        "subsystem": s, "tech": tech, "id": uid, "k": k, "p": p, "year": _y,
                        "gen_mw": val, "gen_mwh": val * h_factor
                    })

                # Expected value of existing hydro generation
                val_he = sum(prob[c] * _val(model.g_he[c, s, k, p]) for c in model.c)
                if val_he > 1e-4:
                    add_row("existing_hydro", 0, val_he)

                if s in model.PH_s:
                    for ph in model.PH_s[s]:
                        val_ph = sum(prob[c] * _val(model.g_ph[c, ph, k, p]) for c in model.c)
                        if val_ph > 1e-4:
                            add_row("planned_hydro", int(ph), val_ph)

                if s in model.HP_s:
                    for h in model.HP_s[s]:
                        val_hp = sum(prob[c] * _val(model.g_hp[c, h, k, p]) for c in model.c)
                        if val_hp > 1e-4:
                            add_row("new_hydro", int(h), val_hp)
                
                if s in model.TE_s:
                    for te in model.TE_s[s]:
                        val_te = sum(prob[c] * _val(model.g_te[c, te, k, p]) for c in model.c)
                        add_row("existing_thermal", int(te), val_te)
                
                if s in model.TP_s:
                    for tp in model.TP_s[s]:
                        val_tp = sum(prob[c] * _val(model.g_tp[c, tp, k, p]) for c in model.c)
                        add_row("new_thermal", int(tp), val_tp)
                
                if s in model.RE_s:
                    for re in model.RE_s[s]:
                        val_re = sum(prob[c] * _val(model.g_re[c, re, k, p]) for c in model.c)
                        add_row("existing_renewable", int(re), val_re)

                if s in model.RP_s:
                    for rp in model.RP_s[s]:
                        val_rp = sum(prob[c] * _val(model.g_rp[c, rp, k, p]) for c in model.c)
                        add_row("new_renewable", int(rp), val_rp)

                if s in model.UE_s:
                    for ue in model.UE_s[s]:
                        val_ue = sum(prob[c] * _val(model.g_ue[c, ue, k, p]) for c in model.c)
                        add_row("existing_other_renewable", int(ue), val_ue)
                
                if s in model.UP_s:
                    for up in model.UP_s[s]:
                        val_up = sum(prob[c] * _val(model.g_up[c, up, k, p]) for c in model.c)
                        add_row("new_other_renewable", int(up), val_up)

                if s in model.BT_s:
                    for bt in model.BT_s[s]:
                        dis = sum(prob[c] * _val(model.g_bt_dis[c, bt, k, p]) for c in model.c)
                        ch  = sum(prob[c] * _val(model.g_bt_ch[c, bt, k, p]) for c in model.c)
                        if dis > 0: add_row("battery_discharge", int(bt), dis)
                        if ch > 0:  add_row("battery_charge", int(bt), -ch)
                        add_row("battery_net", int(bt), dis - ch)
            
    pd.DataFrame(disp_rows).to_csv(os.path.join(output_dir, "dispatch.csv"), index=False)
    print("  - dispatch.csv saved")

    # =========================
    # 3. DEFICIT REPORT (Expected values across scenarios)
    # =========================
    def_rows = []
    for s in model.s:
        for k in model.k:
            year_k = int(model.year_of_k[k])
            # Expected capacity deficit
            exp_def_p = sum(prob[c] * _val(model.def_p[c, s, k]) for c in model.c)
            def_rows.append({
                "subsystem": s, "type": "capacity", "k": k, "p": 0, "year": year_k,
                "mw": exp_def_p, "mwh": 0.0
            })
            for p in model.p:
                h_factor = time_weights[(k, p)]
                exp_def_e = sum(prob[c] * _val(model.def_e[c, s, k, p]) for c in model.c)
                def_rows.append({
                    "subsystem": s, "type": "energy", "k": k, "p": p, "year": year_k,
                    "mw": exp_def_e, "mwh": exp_def_e * h_factor
                })
            
    pd.DataFrame(def_rows).to_csv(os.path.join(output_dir, "deficits.csv"), index=False)
    print("  - deficits.csv saved")
    
    # =========================
    # 4. TRANSMISSION REPORT (Expected values across scenarios)
    # =========================
    trans_rows = []
    year_of_k = {int(k): int(model.year_of_k[k]) for k in model.k}
    # Pre-compute cumulative new transmission capacity by year
    cum_tr = {(u, v, int(y)): sum(_val(model.x_tr[u, v, yp]) for yp in model.y if yp <= y)
              for (u, v) in model.arcs for y in model.y}
    for (u, v) in model.arcs:
        for k in model.k:
            y_k = year_of_k[int(k)]
            new_cap = cum_tr[(u, v, y_k)]
            for p in model.p:
                exp_flow = sum(prob[c] * _val(model.f_e[c, u, v, k, p]) for c in model.c)
                h_factor = time_weights[(k, p)]
                trans_rows.append({
                    "from_s": u, "to_s": v, "k": k, "p": p, "year": y_k,
                    "new_capacity_mw": new_cap,
                    "flow_mw": exp_flow,
                    "flow_mwh": exp_flow * h_factor
                })

    pd.DataFrame(trans_rows).to_csv(os.path.join(output_dir, "transmission.csv"), index=False)
    print("  - transmission.csv saved")

    # =========================
    # 5. BALANCE REPORT (Expected values across scenarios)
    # =========================
    bal_rows = []
    
    # Pre-calculate expected flows
    # Incoming = Positive (+), Outcoming = Negative (-)
    flow_map = {(s, k, p): {'in': 0.0, 'out': 0.0} for s in model.s for k in model.k for p in model.p}
    
    for (u, v) in model.arcs:
        for k in model.k:
            for p in model.p:
                # Expected flow value
                exp_val = sum(prob[c] * _val(model.f_e[c, u, v, k, p]) for c in model.c)
                if exp_val > 0:
                    # u -> v: u exports (negative), v imports (positive)
                    flow_map[(u, k, p)]['out'] -= exp_val       # Negative
                    flow_map[(v, k, p)]['in']  += exp_val       # Positive
                else:
                    # v -> u: v exports (negative), u imports (positive)
                    flow_map[(v, k, p)]['out'] -= abs(exp_val)  # Negative
                    flow_map[(u, k, p)]['in']  += abs(exp_val)  # Positive

    for s in model.s:
        for k in model.k:
            for p in model.p:
                # Generation (Expected values - Positive)
                gen_he = sum(prob[c] * _val(model.g_he[c, s, k, p]) for c in model.c)
                gen_hp = sum(prob[c] * sum(_val(model.g_hp[c, h, k, p]) for h in model.HP_s[s]) for c in model.c) if s in model.HP_s else 0.0
                gen_ph = sum(prob[c] * sum(_val(model.g_ph[c, ph, k, p]) for ph in model.PH_s[s]) for c in model.c) if s in model.PH_s else 0.0
                gen_te = sum(prob[c] * sum(_val(model.g_te[c, i, k, p]) for i in model.TE_s[s]) for c in model.c) if s in model.TE_s else 0.0
                gen_tp = sum(prob[c] * sum(_val(model.g_tp[c, j, k, p]) for j in model.TP_s[s]) for c in model.c) if s in model.TP_s else 0.0
                gen_re = sum(prob[c] * sum(_val(model.g_re[c, r, k, p]) for r in model.RE_s[s]) for c in model.c) if s in model.RE_s else 0.0
                gen_rp = sum(prob[c] * sum(_val(model.g_rp[c, q, k, p]) for q in model.RP_s[s]) for c in model.c) if s in model.RP_s else 0.0
                gen_ue = sum(prob[c] * sum(_val(model.g_ue[c, ue, k, p]) for ue in model.UE_s[s]) for c in model.c) if s in model.UE_s else 0.0
                gen_up = sum(prob[c] * sum(_val(model.g_up[c, up, k, p]) for up in model.UP_s[s]) for c in model.c) if s in model.UP_s else 0.0
                
                # Storage (Expected values)
                stor_dis = sum(prob[c] * sum(_val(model.g_bt_dis[c, b, k, p]) for b in model.BT_s[s]) for c in model.c) if s in model.BT_s else 0.0
                stor_ch  = sum(prob[c] * sum(-1.0 * _val(model.g_bt_ch[c, b, k, p]) for b in model.BT_s[s]) for c in model.c) if s in model.BT_s else 0.0
                
                # Deficit (Expected value)
                def_mw = sum(prob[c] * _val(model.def_e[c, s, k, p]) for c in model.c)
                
                # Demand (scenario-independent)
                dem_mw = _val(model.D[s, k, p]) if (s, k, p) in model.D else 0.0

                bal_rows.append({
                    "subsystem": s, "k": k, "p": p, "year": int(model.year_of_k[k]),
                    "Existing Hydro":     gen_he,
                    "New Hydro":          gen_hp,
                    "Planned Hydro":      gen_ph,
                    "Existing Thermal":   gen_te,
                    "New Thermal":        gen_tp,
                    "Existing Renewable": gen_re,
                    "New Renewable":      gen_rp,
                    "Existing Other Renewable": gen_ue,
                    "New Other Renewable":      gen_up,
                    "Storage Discharge":  stor_dis, # Positive
                    "Storage Charging":   stor_ch,  # Negative
                    "Incoming":           flow_map[(s,k,p)]['in'],  # Positive
                    "Outcoming":          flow_map[(s,k,p)]['out'], # Negative
                    "Deficit":            def_mw,
                    "Demand":             dem_mw
                })

    bal_cols = ["subsystem", "k", "p", "year",
                "Existing Hydro", "New Hydro", "Planned Hydro", "Existing Thermal", "New Thermal", "Existing Renewable", "New Renewable",
                "Existing Other Renewable", "New Other Renewable", "Storage Discharge", "Storage Charging",
                "Incoming", "Outcoming", "Deficit", "Demand"]
    
    pd.DataFrame(bal_rows)[bal_cols].to_csv(os.path.join(output_dir, "balance.csv"), index=False)
    print("  - balance.csv saved")

    # =========================
    # 6. SCENARIO-SPECIFIC DISPATCH (for detailed analysis)
    # =========================
    scenario_dir = os.path.join(output_dir, "scenarios")
    if not os.path.exists(scenario_dir):
        os.makedirs(scenario_dir)
    
    for c in model.c:
        scen_rows = []
        for s in model.s:
            for k in model.k:
                for p in model.p:
                    h_factor = time_weights[(k, p)]
                    
                    # Hydro
                    gen_he = _val(model.g_he[c, s, k, p])
                    gen_hp = sum(_val(model.g_hp[c, h, k, p]) for h in model.HP_s[s]) if s in model.HP_s else 0.0
                    
                    # Thermal
                    gen_te = sum(_val(model.g_te[c, te, k, p]) for te in model.TE_s[s]) if s in model.TE_s else 0.0
                    gen_tp = sum(_val(model.g_tp[c, tp, k, p]) for tp in model.TP_s[s]) if s in model.TP_s else 0.0
                    
                    # Renewables
                    gen_re = sum(_val(model.g_re[c, re, k, p]) for re in model.RE_s[s]) if s in model.RE_s else 0.0
                    gen_rp = sum(_val(model.g_rp[c, rp, k, p]) for rp in model.RP_s[s]) if s in model.RP_s else 0.0
                    gen_ue = sum(_val(model.g_ue[c, ue, k, p]) for ue in model.UE_s[s]) if s in model.UE_s else 0.0
                    gen_up = sum(_val(model.g_up[c, up, k, p]) for up in model.UP_s[s]) if s in model.UP_s else 0.0
                    
                    # Storage
                    stor_dis = sum(_val(model.g_bt_dis[c, b, k, p]) for b in model.BT_s[s]) if s in model.BT_s else 0.0
                    stor_ch = sum(_val(model.g_bt_ch[c, b, k, p]) for b in model.BT_s[s]) if s in model.BT_s else 0.0
                    
                    # Deficit
                    def_e = _val(model.def_e[c, s, k, p])
                    def_p_val = _val(model.def_p[c, s, k]) if p == 1 else 0.0  # Only report once per k
                    
                    scen_rows.append({
                        "subsystem": s, "k": k, "p": p, "year": int(model.year_of_k[k]),
                        "existing_hydro": gen_he,
                        "new_hydro": gen_hp,
                        "existing_thermal": gen_te,
                        "new_thermal": gen_tp,
                        "existing_renewable": gen_re,
                        "new_renewable": gen_rp,
                        "existing_other_renewable": gen_ue,
                        "new_other_renewable": gen_up,
                        "storage_discharge": stor_dis,
                        "storage_charge": stor_ch,
                        "deficit_energy": def_e,
                        "deficit_capacity": def_p_val
                    })
        
        pd.DataFrame(scen_rows).to_csv(os.path.join(scenario_dir, f"dispatch_scenario_{c}.csv"), index=False)
    
    print(f"  - scenario-specific dispatch files saved to {scenario_dir}/")

    # =========================
    # 7. SUMMARY
    # =========================
    summary = {
        "Objective_Z": value(model.obj),
        "Solver_Status": str(results.solver.status) if results else "Unknown",
        "Num_Scenarios": len(list(model.c)),
        "Num_Years": len(list(model.y)),
        "Num_Months": len(list(model.k)),
        "Discount_Rate": _val(model.disc),
    }
    pd.DataFrame([summary]).to_csv(os.path.join(output_dir, "model_summary.csv"), index=False)
    print("  - model_summary.csv saved")