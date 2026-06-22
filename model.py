from pyomo.environ import (
    ConcreteModel, RangeSet, Param, Var, Set, Expression,
    NonNegativeReals, Reals,
    Objective, Constraint, minimize
)

def create_model_structure(
    N_s=14, N_k=60, N_p=4, N_hp=22, N_te=36, N_tp=33, N_re=21, N_rp=38, N_ue=11, N_up=11, N_bt=17, N_ag=13,
    N_y=5,
    N_c=10,
    N_ph=0,
    BIG_M=1e6
):
    """
    Creates the Sets, Parameters, and Variables for a multistage capacity-expansion model.

    Time structure:
        - y in 1..N_y    : investment stages (years)
        - k in 1..N_k    : operational months (typically N_k = 12 * N_y)
        - p in 1..N_p    : load sub-blocks within each month
        - year_of_k(k)   : the stage y that month k belongs to (= ceil(k/12))

    Investment variables x_xx[..., y] are INCREMENTS built in year y.
    Cumulative installed capacity in year y is the Expression X_xx[..., y].
    """
    model = ConcreteModel()

    # =========================
    # 1. SETS / INDICES
    # =========================
    model.s  = RangeSet(1, N_s)
    model.arcs = Set(initialize=[(u, v) for u in model.s for v in model.s if u < v])

    model.k  = RangeSet(1, N_k)
    model.p  = RangeSet(1, N_p)
    model.c  = RangeSet(1, N_c)
    model.y  = RangeSet(1, N_y)

    # Map every month k to its investment stage y = ceil(k / 12)
    model.year_of_k = Param(model.k, within=model.y, initialize=lambda m, k: ((k - 1) // 12) + 1)

    model.hp = RangeSet(1,N_hp)
    model.ph = RangeSet(1, N_ph)   # planned (committed) hydro: exogenous, not a decision variable
    model.te = RangeSet(1, N_te)
    model.tp = RangeSet(1, N_tp)
    model.re = RangeSet(1, N_re)
    model.rp = RangeSet(1, N_rp)
    model.ue = RangeSet(1, N_ue)
    model.up = RangeSet(1, N_up)
    model.bt = RangeSet(1, N_bt)

    # Mapping Sets (Populated later by data_loader)
    model.HP_s = Set(model.s, within=model.hp)
    model.PH_s = Set(model.s, within=model.ph)
    model.TE_s = Set(model.s, within=model.te)
    model.TP_s = Set(model.s, within=model.tp)
    model.RE_s = Set(model.s, within=model.re)
    model.RP_s = Set(model.s, within=model.rp)
    model.UE_s = Set(model.s, within=model.ue)
    model.UP_s = Set(model.s, within=model.up)
    model.BT_s = Set(model.s, within=model.bt)

    # Grouping Sets
    model.ag = RangeSet(1, N_ag)
    model.ag_map = {}

    # =========================
    # 2. PARAMETERS
    # =========================

    # System
    model.H      = Param(model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.d_p    = Param(model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.RM     = Param(within=Reals, mutable=True, default=0.0)

    # Discount rate (scalar) and per-year discount factor delta_y = 1/(1+r)^(y-1)
    model.disc   = Param(within=NonNegativeReals, mutable=True, default=0.0)
    model.delta  = Param(model.y, within=NonNegativeReals, mutable=True, default=1.0)

    # Scenario probabilities
    model.p_c    = Param(model.c, within=NonNegativeReals, mutable=True, default=0.0)

    # Zonal
    model.D      = Param(model.s, model.k, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.Dmax   = Param(model.s, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.DC_e   = Param(model.s, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.DC_p   = Param(model.s, within=NonNegativeReals, mutable=True, default=0.0)

    # Transmission
    # FC_tr defaults to BIG_M: an arc not listed in transmission_capex.xlsx is buildable only at a
    # prohibitive cost, so it is never built (big-M soft "do not build"). BIG_M is finite and tame
    # (see signature) to keep the LP well-scaled, unlike the previous 1e9 that HiGHS flagged.
    model.FC_tr  = Param(model.arcs, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.UT_e   = Param(model.s, model.s, model.k, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.UT_p   = Param(model.s, model.s, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.Derate = Param(model.arcs, model.k, within=NonNegativeReals, mutable=True, default=1.0)
    # Per-year build cap for transmission expansion
    model.UY_tr  = Param(model.arcs, within=NonNegativeReals, mutable=True, default=BIG_M)

    # Transmission Grouping
    model.AG_Max_e = Param(model.ag, model.k, model.p, within=Reals, mutable=True, default=float('inf'))
    model.AG_Max_p = Param(model.ag, model.k, within=Reals, mutable=True, default=float('inf'))

    # Generation
    model.SG_he = Param(model.c, model.s, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.PD_he = Param(model.c, model.s, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.LG_he = Param(model.s, within=NonNegativeReals, mutable=True, default=0.0)
    model.EC_he = Param(model.s, within=NonNegativeReals, mutable=True, default=0.0)
    # Availability of existing hydro in subsystem s in stage year y (1=available,
    # 0=retired). Default 1.0 unless set from existing_hydro_retirement.xlsx.
    model.AV_he = Param(model.s, model.y, within=NonNegativeReals, mutable=True, default=1.0)

    # --- Planned (committed) hydro: exogenous capacity the planner mandates ---
    # Not an optimization decision. Cap_ph = capacity (MW); CF_ph = capacity factor
    # used for the monthly energy budget AND the firm-capacity (adequacy) credit;
    # ON_ph[ph, y] = 1 once the project is online (from its commissioning year).
    model.Cap_ph = Param(model.ph, within=NonNegativeReals, mutable=True, default=0.0)
    model.CF_ph  = Param(model.ph, within=NonNegativeReals, mutable=True, default=1.0)
    model.ON_ph  = Param(model.ph, model.y, within=NonNegativeReals, mutable=True, default=0.0)

    model.SG_hp = Param(model.c, model.hp, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.PD_hp = Param(model.c, model.hp, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.LG_hp = Param(model.hp, within=NonNegativeReals, mutable=True, default=0.0)
    model.FC_hp = Param(model.hp, within=NonNegativeReals, mutable=True, default=0.0)
    model.Nameplate_hp = Param(model.hp, within=NonNegativeReals, mutable=True, default=0.0)

    model.PHG   = Param(within=NonNegativeReals, mutable=True, default=25000.0)

    model.EC_te  = Param(model.te, within=NonNegativeReals, mutable=True, default=0.0)
    model.LC_te  = Param(model.te, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.VC_te  = Param(model.te, within=NonNegativeReals, mutable=True, default=0.0)
    # Availability of existing thermal unit te in stage year y (1 = fully available,
    # 0 = retired). Default 1.0 => no retirements unless set by data_loader from
    # existing_thermal_retirement.xlsx. Scales both the adequacy contribution and the
    # dispatch max/min so a retired unit can neither generate nor be forced to must-run.
    model.AV_te  = Param(model.te, model.y, within=NonNegativeReals, mutable=True, default=1.0)

    model.FC_tp  = Param(model.tp, within=NonNegativeReals, mutable=True, default=0.0)
    model.A_tp   = Param(model.tp, within=NonNegativeReals, mutable=True, default=0.0)
    model.UX_tp  = Param(model.tp, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.UY_tp  = Param(model.tp, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.LF_tp  = Param(model.tp, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    model.VC_tp  = Param(model.tp, within=NonNegativeReals, mutable=True, default=0.0)

    model.EC_re  = Param(model.re, within=NonNegativeReals, mutable=True, default=0.0)
    model.CF_re  = Param(model.re, model.k, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.CC_re  = Param(model.re, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    # Availability of existing renewable re in stage year y (1=available, 0=retired).
    model.AV_re  = Param(model.re, model.y, within=NonNegativeReals, mutable=True, default=1.0)

    model.FC_rp  = Param(model.rp, within=NonNegativeReals, mutable=True, default=0.0)
    model.UX_rp  = Param(model.rp, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.UY_rp  = Param(model.rp, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.CF_rp  = Param(model.rp, model.k, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.CC_rp  = Param(model.rp, model.k, within=NonNegativeReals, mutable=True, default=0.0)

    model.EC_ue  = Param(model.ue, within=NonNegativeReals, mutable=True, default=0.0)
    model.CF_ue  = Param(model.ue, model.k, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.CC_ue  = Param(model.ue, model.k, within=NonNegativeReals, mutable=True, default=0.0)
    # Availability of existing other-renewable ue in stage year y (1=available, 0=retired).
    model.AV_ue  = Param(model.ue, model.y, within=NonNegativeReals, mutable=True, default=1.0)

    model.FC_up  = Param(model.up, within=NonNegativeReals, mutable=True, default=0.0)
    model.UX_up  = Param(model.up, within=NonNegativeReals, mutable=True, default=0.0)
    model.UY_up  = Param(model.up, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.CF_up  = Param(model.up, model.k, model.p, within=NonNegativeReals, mutable=True, default=0.0)
    model.CC_up  = Param(model.up, model.k, within=NonNegativeReals, mutable=True, default=0.0)

    model.FC_bt   = Param(model.bt, within=NonNegativeReals, mutable=True, default=0.0)
    model.Eff_bt  = Param(model.bt, within=NonNegativeReals, mutable=True, default=1.0)
    model.Dur_bt  = Param(model.bt, within=NonNegativeReals, mutable=True, default=1.0)
    model.UX_bt   = Param(model.bt, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.UY_bt   = Param(model.bt, within=NonNegativeReals, mutable=True, default=BIG_M)
    model.CC_bt   = Param(model.bt, within=NonNegativeReals, mutable=True, default=1.0)

    # =========================
    # 3. VARIABLES (incremental investments, indexed by stage y)
    # =========================
    # Hydro: fraction of project built in year y; cumulative <= 1 (enforced in add_constraints)
    model.x_hp = Var(model.hp, model.y, within=NonNegativeReals, bounds=(0, 1))
    # Per-year cap from UY_*, total cap (sum over y <= UX_*) enforced as a constraint
    model.x_tp = Var(model.tp, model.y, within=NonNegativeReals, bounds=lambda m, tp, y: (0.0, m.UY_tp[tp]))
    model.x_rp = Var(model.rp, model.y, within=NonNegativeReals, bounds=lambda m, rp, y: (0.0, m.UY_rp[rp]))
    model.x_up = Var(model.up, model.y, within=NonNegativeReals, bounds=lambda m, up, y: (0.0, m.UY_up[up]))
    model.x_bt = Var(model.bt, model.y, within=NonNegativeReals, bounds=lambda m, b,  y: (0.0, m.UY_bt[b]))
    model.x_tr = Var(model.arcs, model.y, within=NonNegativeReals, bounds=lambda m, u, v, y: (0.0, m.UY_tr[u, v]))

    # Cumulative installed by end of year y = sum of increments y' <= y
    model.X_hp = Expression(model.hp, model.y, rule=lambda m, h, y:  sum(m.x_hp[h, yp]  for yp in m.y if yp <= y))
    model.X_tp = Expression(model.tp, model.y, rule=lambda m, tp, y: sum(m.x_tp[tp, yp] for yp in m.y if yp <= y))
    model.X_rp = Expression(model.rp, model.y, rule=lambda m, rp, y: sum(m.x_rp[rp, yp] for yp in m.y if yp <= y))
    model.X_up = Expression(model.up, model.y, rule=lambda m, up, y: sum(m.x_up[up, yp] for yp in m.y if yp <= y))
    model.X_bt = Expression(model.bt, model.y, rule=lambda m, b,  y: sum(m.x_bt[b,  yp] for yp in m.y if yp <= y))
    model.X_tr = Expression(model.arcs, model.y, rule=lambda m, u, v, y: sum(m.x_tr[u, v, yp] for yp in m.y if yp <= y))

    # Operational variables (k spans full horizon 1..N_k)
    model.g_he  = Var(model.c, model.s, model.k, model.p, within=NonNegativeReals)
    model.g_hp  = Var(model.c, model.hp, model.k, model.p, within=NonNegativeReals)
    model.g_ph  = Var(model.c, model.ph, model.k, model.p, within=NonNegativeReals)  # planned hydro dispatch
    model.hp_he = Var(model.c, model.s, model.k, model.p, within=NonNegativeReals)
    model.hp_hp = Var(model.c, model.hp, model.k, model.p, within=NonNegativeReals)

    model.g_te = Var(model.c, model.te, model.k, model.p, within=NonNegativeReals)
    model.g_tp = Var(model.c, model.tp, model.k, model.p, within=NonNegativeReals)
    model.g_re = Var(model.c, model.re, model.k, model.p, within=NonNegativeReals)
    model.g_rp = Var(model.c, model.rp, model.k, model.p, within=NonNegativeReals)
    model.g_ue = Var(model.c, model.ue, model.k, model.p, within=NonNegativeReals)
    model.g_up = Var(model.c, model.up, model.k, model.p, within=NonNegativeReals)

    model.g_bt_dis = Var(model.c, model.bt, model.k, model.p, within=NonNegativeReals)
    model.g_bt_ch  = Var(model.c, model.bt, model.k, model.p, within=NonNegativeReals)

    model.f_e = Var(model.c, model.arcs, model.k, model.p, within=Reals)
    model.f_p = Var(model.c, model.arcs, model.k, within=Reals)

    model.def_e = Var(model.c, model.s, model.k, model.p, within=NonNegativeReals)
    model.def_p = Var(model.c, model.s, model.k, within=NonNegativeReals)

    return model


def add_constraints(model):
    """
    Constructs Constraints and Objective.
    Must be called AFTER data_loader has populated the sets (TE_s, RE_s, etc.).
    """

    # Convenience: stage y that month k belongs to
    def _y(m, k):
        return int(m.year_of_k[k])

    # --- TOTAL-CAPACITY CAPS (sum of yearly increments <= UX_*) ---
    def hp_total_rule(m, h):
        return sum(m.x_hp[h, y] for y in m.y) <= 1.0
    model.hp_total_cap = Constraint(model.hp, rule=hp_total_rule)

    def tp_total_rule(m, tp):
        return sum(m.x_tp[tp, y] for y in m.y) <= m.UX_tp[tp]
    model.tp_total_cap = Constraint(model.tp, rule=tp_total_rule)

    def rp_total_rule(m, rp):
        return sum(m.x_rp[rp, y] for y in m.y) <= m.UX_rp[rp]
    model.rp_total_cap = Constraint(model.rp, rule=rp_total_rule)

    def up_total_rule(m, up):
        return sum(m.x_up[up, y] for y in m.y) <= m.UX_up[up]
    model.up_total_cap = Constraint(model.up, rule=up_total_rule)

    def bt_total_rule(m, b):
        return sum(m.x_bt[b, y] for y in m.y) <= m.UX_bt[b]
    model.bt_total_cap = Constraint(model.bt, rule=bt_total_rule)

    # --- ENERGY BALANCE (Eq. 9) ---
    def balance_rule(m, c, s, k, p):
        incoming = sum(m.f_e[c, u, v, k, p] for (u, v) in m.arcs if v == s)
        outgoing = sum(m.f_e[c, u, v, k, p] for (u, v) in m.arcs if u == s)

        gen_local = (
            m.g_he[c, s, k, p] +
            sum(m.g_hp[c, h, k, p] for h in m.HP_s[s]) +
            sum(m.g_ph[c, ph, k, p] for ph in m.PH_s[s]) +
            sum(m.g_te[c, te, k, p] for te in m.TE_s[s]) +
            sum(m.g_tp[c, tp, k, p] for tp in m.TP_s[s]) +
            sum(m.g_re[c, re, k, p] for re in m.RE_s[s]) +
            sum(m.g_rp[c, rp, k, p] for rp in m.RP_s[s]) +
            sum(m.g_ue[c, ue, k, p] for ue in m.UE_s[s]) +
            sum(m.g_up[c, up, k, p] for up in m.UP_s[s]) +
            sum(m.g_bt_dis[c, bt, k, p] - m.g_bt_ch[c, bt, k, p] for bt in m.BT_s[s])
        )

        return gen_local + (incoming - outgoing) + m.def_e[c, s, k, p] >= m.D[s, k, p]
    model.balance = Constraint(model.c, model.s, model.k, model.p, rule=balance_rule)

    # --- CAPACITY BALANCE (Eq. 10) ---
    def capacity_rule(m, c, s, k):
        y = _y(m, k)
        incoming = sum(m.f_p[c, u, v, k] for (u, v) in m.arcs if v == s)
        outgoing = sum(m.f_p[c, u, v, k] for (u, v) in m.arcs if u == s)

        exist = (
            m.PD_he[c, s, k] * m.AV_he[s, y] +
            sum(m.Cap_ph[ph] * m.CF_ph[ph] * m.ON_ph[ph, y] for ph in m.PH_s[s]) +
            sum(m.EC_te[te] * m.AV_te[te, y] for te in m.TE_s[s]) +
            sum(m.EC_re[re] * m.CC_re[re, k] * m.AV_re[re, y] for re in m.RE_s[s]) +
            sum(m.EC_ue[ue] * m.CC_ue[ue, k] * m.AV_ue[ue, y] for ue in m.UE_s[s])
        )

        new   = (
            sum(m.PD_hp[c, h, k] * m.X_hp[h, y] for h in m.HP_s[s]) +
            sum(m.A_tp[tp] * m.X_tp[tp, y] for tp in m.TP_s[s]) +
            sum(m.CC_rp[rp, k] * m.X_rp[rp, y] for rp in m.RP_s[s]) +
            sum(m.CC_up[up, k] * m.X_up[up, y] for up in m.UP_s[s]) +
            sum(m.CC_bt[bt] * m.X_bt[bt, y] for bt in m.BT_s[s])
        )

        return exist + new + (incoming - outgoing) + m.def_p[c, s, k] >= m.Dmax[s, k] * (1 + m.RM)
    model.capacity = Constraint(model.c, model.s, model.k, rule=capacity_rule)

    # --- TRANSMISSION LIMITS ---
    def tr_energy_min_rule(m, c, u, v, k, p):
        y = _y(m, k)
        return m.f_e[c, u, v, k, p] >= -(m.UT_e[v, u, k, p] + m.X_tr[u, v, y])
    model.tr_energy_min = Constraint(model.c, model.arcs, model.k, model.p, rule=tr_energy_min_rule)

    def tr_energy_max_rule(m, c, u, v, k, p):
        y = _y(m, k)
        return m.f_e[c, u, v, k, p] <= (m.UT_e[u, v, k, p] + m.X_tr[u, v, y])
    model.tr_energy_max = Constraint(model.c, model.arcs, model.k, model.p, rule=tr_energy_max_rule)

    def tr_cap_min_rule(m, c, u, v, k):
        y = _y(m, k)
        return m.f_p[c, u, v, k] >= -1.0 * m.Derate[u, v, k] * (m.UT_p[v, u, k] + m.X_tr[u, v, y])
    model.tr_cap_min = Constraint(model.c, model.arcs, model.k, rule=tr_cap_min_rule)

    def tr_cap_max_rule(m, c, u, v, k):
        y = _y(m, k)
        return m.f_p[c, u, v, k] <= m.Derate[u, v, k] * (m.UT_p[u, v, k] + m.X_tr[u, v, y])
    model.tr_cap_max = Constraint(model.c, model.arcs, model.k, rule=tr_cap_max_rule)


    # --- TRANSMISSION ENERGY LIMITS (GROUPING) ---
    def grouping_rule(m, c, ag, k, p):
        y = _y(m, k)
        limit = m.AG_Max_e[ag, k, p]
        flow_sum = 0
        expansion_sum = 0
        for (u_in, v_in) in m.ag_map[ag]:
            if u_in < v_in:
                u, v = u_in, v_in
                direction = 1
            else:
                u, v = v_in, u_in
                direction = -1
            if (u, v) in m.arcs:
                flow_sum += direction * m.f_e[c, u, v, k, p]
                expansion_sum += m.X_tr[u, v, y]
        return flow_sum - expansion_sum <= limit
    model.con_grouping = Constraint(model.c, model.ag, model.k, model.p, rule=grouping_rule)

    # --- TRANSMISSION CAPACITY LIMITS ---
    def grouping_capacity_rule(m, c, ag, k):
        y = _y(m, k)
        limit = m.AG_Max_p[ag, k]
        flow_sum = 0
        expansion_sum = 0
        for (u_in, v_in) in m.ag_map[ag]:
            if u_in < v_in:
                u, v, direction = u_in, v_in, 1
            else:
                u, v, direction = v_in, u_in, -1
            if (u, v) in m.arcs:
                flow_sum += direction * m.f_p[c, u, v, k]
                expansion_sum += m.X_tr[u, v, y]
        return flow_sum - expansion_sum <= limit
    model.con_grouping_capacity = Constraint(model.c, model.ag, model.k, rule=grouping_capacity_rule)

    # --- HYDRO LIMITS ---
    # All existing-hydro limits are scaled by AV_he[s, y] so a retired hydro
    # subsystem (AV=0) has zero energy budget, zero power, and no must-run floor.
    def he_energy_rule(m, c, s, k):
        y = _y(m, k)
        return sum(m.g_he[c, s, k, p] * m.d_p[p] for p in m.p) <= m.SG_he[c, s, k] * m.AV_he[s, y]
    model.con_he_energy = Constraint(model.c, model.s, model.k, rule=he_energy_rule)

    def he_power_rule(m, c, s, k, p):
        y = _y(m, k)
        return m.g_he[c, s, k, p] <= m.PD_he[c, s, k] * m.AV_he[s, y]
    model.con_he_power = Constraint(model.c, model.s, model.k, model.p, rule=he_power_rule)

    def he_min_rule(m, c, s, k, p):
        # Min-gen floor gated by availability so a retired plant incurs no penalty.
        y = _y(m, k)
        return m.g_he[c, s, k, p] + m.hp_he[c, s, k, p] >= m.LG_he[s] * m.AV_he[s, y]
    model.con_he_min = Constraint(model.c, model.s, model.k, model.p, rule=he_min_rule)

    # --- PLANNED (COMMITTED) HYDRO LIMITS ---
    # Exogenous capacity: power capped at the committed MW once online; monthly
    # energy capped by the capacity factor. Both gated by ON_ph (commissioning year).
    def ph_power_rule(m, c, ph, k, p):
        y = _y(m, k)
        return m.g_ph[c, ph, k, p] <= m.Cap_ph[ph] * m.ON_ph[ph, y]
    model.con_ph_power = Constraint(model.c, model.ph, model.k, model.p, rule=ph_power_rule)

    def ph_energy_rule(m, c, ph, k):
        y = _y(m, k)
        return sum(m.g_ph[c, ph, k, p] * m.d_p[p] for p in m.p) <= m.Cap_ph[ph] * m.CF_ph[ph] * m.ON_ph[ph, y]
    model.con_ph_energy = Constraint(model.c, model.ph, model.k, rule=ph_energy_rule)

    def hp_energy_rule(m, c, h, k):
        y = _y(m, k)
        return sum(m.g_hp[c, h, k, p] * m.d_p[p] for p in m.p) <= m.SG_hp[c, h, k] * m.X_hp[h, y]
    model.con_hp_energy = Constraint(model.c, model.hp, model.k, rule=hp_energy_rule)

    def hp_power_rule(m, c, h, k, p):
        y = _y(m, k)
        return m.g_hp[c, h, k, p] <= m.PD_hp[c, h, k] * m.X_hp[h, y]
    model.con_hp_power = Constraint(model.c, model.hp, model.k, model.p, rule=hp_power_rule)

    def hp_min_rule(m, c, h, k, p):
        y = _y(m, k)
        return m.g_hp[c, h, k, p] + m.hp_hp[c, h, k, p] >= m.LG_hp[h] * m.X_hp[h, y]
    model.con_hp_min = Constraint(model.c, model.hp, model.k, model.p, rule=hp_min_rule)

    # --- GENERATION DISPATCH LIMITS ---
    def tp_max_rule(m, c, tp, k, p):
        y = _y(m, k)
        return m.g_tp[c, tp, k, p] <= m.A_tp[tp] * m.X_tp[tp, y]
    model.tp_max_dispatch = Constraint(model.c, model.tp, model.k, model.p, rule=tp_max_rule)

    def tp_min_rule(m, c, tp, k, p):
        y = _y(m, k)
        return m.g_tp[c, tp, k, p] >= m.LF_tp[tp, k] * m.A_tp[tp] * m.X_tp[tp, y]
    model.tp_min_dispatch = Constraint(model.c, model.tp, model.k, model.p, rule=tp_min_rule)

    def te_max_rule(m, c, te, k, p):
        y = _y(m, k)
        return m.g_te[c, te, k, p] <= m.EC_te[te] * m.AV_te[te, y]
    model.te_max_dispatch = Constraint(model.c, model.te, model.k, model.p, rule=te_max_rule)

    def te_min_rule(m, c, te, k, p):
        # Must-run floor is gated by availability so a retired unit (AV=0) is not
        # forced to generate (which would be infeasible against the zeroed max).
        y = _y(m, k)
        return m.g_te[c, te, k, p] >= m.LC_te[te, k] * m.AV_te[te, y]
    model.te_min_dispatch = Constraint(model.c, model.te, model.k, model.p, rule=te_min_rule)

    def re_max_rule(m, c, re, k, p):
        y = _y(m, k)
        return m.g_re[c, re, k, p] <= m.CF_re[re, k, p] * m.EC_re[re] * m.AV_re[re, y]
    model.re_max_dispatch = Constraint(model.c, model.re, model.k, model.p, rule=re_max_rule)

    def rp_max_rule(m, c, rp, k, p):
        y = _y(m, k)
        return m.g_rp[c, rp, k, p] <= m.CF_rp[rp, k, p] * m.X_rp[rp, y]
    model.rp_max_dispatch = Constraint(model.c, model.rp, model.k, model.p, rule=rp_max_rule)

    def ue_max_rule(m, c, ue, k, p):
        y = _y(m, k)
        return m.g_ue[c, ue, k, p] <= m.CF_ue[ue, k, p] * m.EC_ue[ue] * m.AV_ue[ue, y]
    model.ue_max_dispatch = Constraint(model.c, model.ue, model.k, model.p, rule=ue_max_rule)

    def up_max_rule(m, c, up, k, p):
        y = _y(m, k)
        return m.g_up[c, up, k, p] <= m.CF_up[up, k, p] * m.X_up[up, y]
    model.up_max_dispatch = Constraint(model.c, model.up, model.k, model.p, rule=up_max_rule)

    # --- BESS ---
    def bt_dis_max_rule(m, c, b, k, p):
        y = _y(m, k)
        return m.g_bt_dis[c, b, k, p] <= m.X_bt[b, y]
    model.bt_dis_max = Constraint(model.c, model.bt, model.k, model.p, rule=bt_dis_max_rule)

    def bt_ch_max_rule(m, c, b, k, p):
        y = _y(m, k)
        return m.g_bt_ch[c, b, k, p] <= m.X_bt[b, y]
    model.bt_ch_max = Constraint(model.c, model.bt, model.k, model.p, rule=bt_ch_max_rule)

    def bt_energy_bal_rule(m, c, b, k):
        dis_mwh = sum(m.g_bt_dis[c, b, k, p] * m.H[k] * m.d_p[p] for p in m.p)
        ch_mwh  = sum(m.g_bt_ch[c, b, k, p]  * m.H[k] * m.d_p[p] for p in m.p)
        return dis_mwh <= ch_mwh * m.Eff_bt[b]
    model.bt_energy_bal = Constraint(model.c, model.bt, model.k, rule=bt_energy_bal_rule)

    def bt_duration_rule(m, c, b, k):
        y = _y(m, k)
        dis_mwh = sum(m.g_bt_dis[c, b, k, p] * m.H[k] * m.d_p[p] for p in m.p)
        max_mwh = (m.X_bt[b, y] * m.Dur_bt[b]) * (m.H[k] / 24.0)
        return dis_mwh <= max_mwh
    model.bt_duration = Constraint(model.c, model.bt, model.k, rule=bt_duration_rule)


    # =========================
    # 5. OBJECTIVE (discounted)
    # =========================
    def obj_rule(m):
        # Discounted capital cost. FC is an ANNUALIZED charge (CAPEX x CRF, $/MW-year),
        # so it must be paid in every year the capacity is in service, not just the build
        # year. We therefore charge FC on the CUMULATIVE installed capacity X_xx[..., y]
        # (= sum of increments up to year y), discounted by delta_y for each year y.
        capex = sum(
            m.delta[y] * (
                sum(m.FC_hp[h]   * m.X_hp[h, y]   for h  in m.hp) +
                sum(m.FC_tp[tp]  * m.X_tp[tp, y]  for tp in m.tp) +
                sum(m.FC_rp[rp]  * m.X_rp[rp, y]  for rp in m.rp) +
                sum(m.FC_up[up]  * m.X_up[up, y]  for up in m.up) +
                sum(m.FC_bt[bt]  * m.X_bt[bt, y]  for bt in m.bt) +
                sum(m.FC_tr[u, v] * m.X_tr[u, v, y] for (u, v) in m.arcs)
            )
            for y in m.y
        )

        # Discounted opex: each month k is in year y(k), so delta_{y(k)} multiplies its cost
        opex = sum(
            m.p_c[c] * sum(
                m.delta[m.year_of_k[k]] * (
                    sum(m.VC_te[te] * m.g_te[c, te, k, p] for te in m.te) +
                    sum(m.VC_tp[tp] * m.g_tp[c, tp, k, p] for tp in m.tp) +
                    sum(m.DC_e[s, p] * m.def_e[c, s, k, p] for s in m.s)
                ) * m.H[k] * m.d_p[p]
                for k in m.k for p in m.p
            )
            for c in m.c
        )

        penalties = sum(
            m.p_c[c] * sum(
                m.delta[m.year_of_k[k]] * m.PHG * m.d_p[p] * m.H[k] * (
                    sum(m.hp_he[c, s, k, p] for s in m.s) +
                    sum(m.hp_hp[c, h, k, p] for h in m.hp)
                )
                for k in m.k for p in m.p
            )
            for c in m.c
        )

        deficit_cap = sum(
            m.p_c[c] * sum(
                m.delta[m.year_of_k[k]] * m.DC_p[s] * m.def_p[c, s, k]
                for s in m.s for k in m.k
            )
            for c in m.c
        )

        return capex + opex + deficit_cap + penalties

    model.obj = Objective(rule=obj_rule, sense=minimize)

    return model

# Backward compatibility alias (so other scripts don't break immediately)
def create_model(**kwargs):
    return create_model_structure(**kwargs)
