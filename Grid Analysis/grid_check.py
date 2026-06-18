#NOTE: ONLY CONSIDER GENERATION FROM ElmSym Elements (Machines) and ElmLod (loads). External grid, static gen, and other loads/gens not considered.

import sys
import os
import math

# ==========================================
# 0. DIGSILENT PATH CONFIGURATION
# ==========================================
PF_PATH = r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9"

if not os.path.exists(PF_PATH):
    PF_PATH_ALT = r"C:\Program Files\DIgSILENT\PowerFactory 2022 SP1\Python\3.10"
    if os.path.exists(PF_PATH_ALT):
        PF_PATH = PF_PATH_ALT
    else:
        print(f"[ERROR] DIgSILENT path not found at: {PF_PATH}")
        sys.exit(1)

if PF_PATH not in sys.path:
    sys.path.append(PF_PATH)

try:
    import powerfactory as pf
except ImportError:
    print("[ERROR] Failed to import 'powerfactory'. Check Path/Python Version.")
    sys.exit(1)

# ==========================================
# 1. NORMAL LIMITS CONFIGURATION
# ==========================================
PROJECT_NAME = "YOUR PROJECT"  # Change to your actual project name

# Normal limits per km
R_PER_KM_MIN, R_PER_KM_MAX = 0.001, 5.0 
X_PER_KM_MIN, X_PER_KM_MAX = 0.01, 3.0
B_PER_KM_MIN, B_PER_KM_MAX = 0.0, 1000.0 # uS/km (Range expanded for cables)

V_MIN, V_MAX = 0.90, 1.05
LOAD_WARN, LOAD_CRIT = 80.0, 100.0

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def print_header(text):
    print("\n" + "="*80)
    print(f" {text}")
    print("="*80)

def check_sanity(name, val, v_min, v_max, unit, param_name):
    if val is None: return None
    if val < v_min:
        return f"[ANOMALY] {name}: {param_name} is too LOW ({val:.4f} {unit} < {v_min})"
    elif val > v_max:
        return f"[ANOMALY] {name}: {param_name} is too HIGH ({val:.4f} {unit} > {v_max})"
    return None

def show_top_bottom(data_list, label, unit):
    if not data_list: return
    valid_data = [d for d in data_list if d['val'] is not None]
    sorted_data = sorted(valid_data, key=lambda x: x['val'])
    
    print(f"\n--- Ranking {label} ({unit}) ---")
    print(f"   [Bottom 5] (Lowest)")
    for item in sorted_data[:5]:
        print(f"    - {item['name']:<20} | Type: {item['type']:<15} | {item['val']:.4f} {unit}")
    print(f"   [Top 5] (Highest)")
    for item in sorted_data[-5:]:
        print(f"    - {item['name']:<20} | Type: {item['type']:<15} | {item['val']:.4f} {unit}")

# ==========================================
# MAIN PROGRAM
# ==========================================
def run_analysis():
    app = pf.GetApplicationExt()
    if not app: raise Exception("Connection Failed")
    
    app.ClearOutputWindow()
    app.ActivateProject(PROJECT_NAME)
    
    print_header("CHAPTER 2: GRID HEALTH CHECK (V7 - HYBRID CALC & TYPE CHECK)")
    
    suspicious_components = [] 
    
    # ----------------------------------------------------
    # STEP 1: PARAMETER CHECK (MANUAL R/X, HYBRID B)
    # ----------------------------------------------------
    print_header("STEP 1: PER KM PARAMETER CHECK")
    
    data_r, data_x, data_b, data_len = [], [], [], []
    
    lines = app.GetCalcRelevantObjects("*.ElmLne")
    print(f"Checking {len(lines)} transmission lines...")
    
    anomaly_found = False
    
    for l in lines:
        if l.GetAttribute("outserv"): continue
        
        name = l.loc_name
        length = l.GetAttribute("dline") # km
        
        l_type = l.GetAttribute("typ_id")
        t_name = l_type.loc_name if l_type else "Manual Input"

        # Container variables
        r_km, x_km, b_km = None, None, None

        # 1. GET R & X (MANUALLY FROM ELEMENT)
        try:
            R_total = l.GetAttribute("R1")
            X_total = l.GetAttribute("X1")
            
            if length > 0.0001:
                r_km = R_total / length
                x_km = X_total / length
        except:
            pass 

        # 2. GET B (SUSCEPTANCE) - HYBRID LOGIC
        try:
            B_total = l.GetAttribute("B1") # uS
            if B_total is not None and B_total > 0 and length > 0:
                 b_km = B_total / length
        except: pass
        
        if b_km is None:
            try:
                C_total = l.GetAttribute("C1") # Usually uF
                if C_total is not None and C_total > 0 and length > 0:
                    b_km = (314.159 * C_total) / length
            except: pass
            
        if b_km is None and l_type:
            try:
                b_km = l_type.GetAttribute("bline") # uS/km
            except: pass

        # SAVE & CHECK
        data_len.append({'name': name, 'type': t_name, 'val': length})
        
        if r_km is not None:
            data_r.append({'name': name, 'type': t_name, 'val': r_km})
            res = check_sanity(name, r_km, R_PER_KM_MIN, R_PER_KM_MAX, "Ohm/km", "R")
            if res: 
                print(f"   [!] {res}")
                suspicious_components.append(res)
                anomaly_found = True

        if x_km is not None:
            data_x.append({'name': name, 'type': t_name, 'val': x_km})
            res = check_sanity(name, x_km, X_PER_KM_MIN, X_PER_KM_MAX, "Ohm/km", "X")
            if res:
                print(f"   [!] {res}")
                suspicious_components.append(res)
                anomaly_found = True

        if b_km is not None:
            data_b.append({'name': name, 'type': t_name, 'val': b_km})
            res = check_sanity(name, b_km, B_PER_KM_MIN, B_PER_KM_MAX, "uS/km", "B")
            if res:
                print(f"   [!] {res}")
                suspicious_components.append(res)
                anomaly_found = True
        
        if length <= 0:
             msg = f"{name}: Length is 0 km"
             print(f"   [!] {msg}")
             suspicious_components.append(msg)
             anomaly_found = True

    if not anomaly_found: print("   >> Physical parameters look NORMAL.")

    # ----------------------------------------------------
    # STEP 2: MISSING TYPE & CRITICAL CONFIGURATION CHECK
    # ----------------------------------------------------
    print_header("STEP 2: MISSING TYPE & CRITICAL CONFIGURATION CHECK")
    
    missing_type_flag = False
    
    # Dict of components to check for typ_id
    comp_types_to_check = {
        "Line": app.GetCalcRelevantObjects("*.ElmLne"),
        "Transformer": app.GetCalcRelevantObjects("*.ElmTr2"),
        "Generator": app.GetCalcRelevantObjects("*.ElmSym")
    }
    
    for c_type, c_list in comp_types_to_check.items():
        for comp in c_list:
            if comp.GetAttribute("outserv") == 0:
                if not comp.GetAttribute("typ_id"):
                    msg = f"{c_type} '{comp.loc_name}' is MISSING a Type (typ_id)."
                    print(f"   [!] {msg}")
                    suspicious_components.append(msg)
                    missing_type_flag = True

    # Check Buses for missing Nominal Voltage
    buses = app.GetCalcRelevantObjects("*.ElmTerm")
    for b in buses:
        if b.GetAttribute("outserv") == 0:
            uknom = b.GetAttribute("uknom")
            if uknom is None or uknom <= 0:
                msg = f"Bus '{b.loc_name}' has 0 kV or MISSING Nominal Voltage (uknom)."
                print(f"   [!] {msg}")
                suspicious_components.append(msg)
                missing_type_flag = True

    if not missing_type_flag:
        print("   >> All checked components have valid Types and Nominal Voltages.")
    else:
        print("   >>> WARNING: Missing Types or 0kV buses will almost certainly cause Load Flow divergence!")

    # ----------------------------------------------------
    # STEP 3: RANKING
    # ----------------------------------------------------
    print_header("STEP 3: EXTREME RANKING")
    show_top_bottom(data_r, "RESISTANCE PER KM", "Ohm/km")
    show_top_bottom(data_x, "INDUCTANCE PER KM", "Ohm/km")
    show_top_bottom(data_b, "SUSCEPTANCE PER KM", "uS/km")
    show_top_bottom(data_len, "LINE LENGTH", "km")

    # ----------------------------------------------------
    # STEP 4: LOAD FLOW
    # ----------------------------------------------------
    print_header("STEP 4: LOAD FLOW CHECK")
    sc = app.GetActiveStudyCase()
    if not sc:
        print("[ERROR] Activate Study Case first!")
        return

    ldf = app.GetFromStudyCase("ComLdf")
    
    # Ensure standard execution first
    ldf.SetAttribute("iKeepCalc", 0) 
    err = ldf.Execute()
    
    if err == 0:
        print("\n>>> STATUS: CONVERGED (Safe)")
        
        # Overload Check
        trafos = app.GetCalcRelevantObjects("*.ElmTr2")
        all_branches = lines + trafos
        print("\n[A] LOADING CHECK")
        ov_flag = False
        for elm in all_branches:
            if elm.GetAttribute("outserv"): continue
            try:
                load = elm.GetAttribute("c:loading")
                if load > LOAD_WARN:
                    status = "CRITICAL" if load > LOAD_CRIT else "WARNING"
                    print(f"   [{status}] {elm.loc_name:<20} : {load:.2f} %")
                    ov_flag = True
            except: pass
        if not ov_flag: print("   >> Safe.")

        # Voltage Check
        print("\n[B] VOLTAGE CHECK")
        v_flag = False
        for b in buses:
            if b.GetAttribute("outserv"): continue
            try:
                v = b.GetAttribute("m:u")
                if v < V_MIN or v > V_MAX:
                    status = "UNDER" if v < V_MIN else "OVER"
                    print(f"   [{status}]    {b.loc_name:<20} : {v:.4f} p.u.")
                    v_flag = True
            except: pass
        if not v_flag: print("   >> Safe.")
        
    else:
        print("\n>>> STATUS: DIVERGED (Failed)")
        
        # --- DIAGNOSTIC LOAD FLOW ---
        print("\n[*] Running Diagnostic Load Flow (Maintaining calculation to isolate failure)...")
        ldf.SetAttribute("iKeepCalc", 1) # Maintain calculation if calc fails
        ldf.Execute()
        
        low_v_buses = []
        good_v_buses = 0
        
        for b in buses:
            if b.GetAttribute("outserv"): continue
            try:
                v = b.GetAttribute("m:u")
                if v < 0.8:
                    low_v_buses.append((b.loc_name, v))
                elif v >= 0.9:
                    good_v_buses += 1
            except: pass
            
        print("\n[1] VOLTAGE DIAGNOSIS")
        if len(low_v_buses) > 0:
            print(f"    -> Found {len(low_v_buses)} buses with severely low voltage (< 0.8 p.u.):")
            for name, v in low_v_buses[:5]:
                print(f"       * {name:<20} : {v:.4f} p.u.")
            if len(low_v_buses) > 5:
                print(f"       * ... and {len(low_v_buses) - 5} more.")
                
            if good_v_buses > 0:
                print("\n    >>> DIAGNOSIS: Localized Voltage Collapse Detected!")
                print("    Because other parts of the grid have normal voltage, the divergence is likely caused by an isolated severe voltage drop.")
                print("    RECOMMENDED ACTIONS:")
                print("    1. Adjust transformer taps to boost voltage in the affected area.")
                print("    2. Install Capacitor Banks (Shunt Capacitors) near these specific buses.")
                print("    3. Check if the lines/cables connected to these buses have Capacitance (C1) values defined.")
        else:
            print("    -> No isolated severe voltage drops found. The issue might be global.")

        # Reset iKeepCalc to default
        ldf.SetAttribute("iKeepCalc", 0)
        
        # Diagnostic Weird Components
        print("\n[2] WEIRD COMPONENTS & MISSING TYPES (Check these inputs!)")
        if suspicious_components:
            # Using set to avoid duplicate prints if an element triggered multiple flags
            for s in list(dict.fromkeys(suspicious_components))[:15]: 
                print(f"    * {s}")
        else:
            print("    Physical data looks safe. Likely extreme power overload.")

        # Power Balance
        print("\n[3] POWER BALANCE (Estimation)")
        gens = app.GetCalcRelevantObjects("*.ElmSym")
        loads = app.GetCalcRelevantObjects("*.ElmLod")
        
        sum_p_g = sum([g.GetAttribute("pgini") for g in gens if not g.GetAttribute("outserv")])
        sum_p_l = sum([l.GetAttribute("plini") for l in loads if not l.GetAttribute("outserv")])
        
        sum_q_g = sum([g.GetAttribute("qgini") for g in gens if not g.GetAttribute("outserv")])
        sum_q_l = sum([l.GetAttribute("qlini") for l in loads if not l.GetAttribute("outserv")])
        
        diff_p = sum_p_g - sum_p_l
        diff_q = sum_q_g - sum_q_l
        
        print(f"    P Gen: {sum_p_g:.2f} MW   vs P Load: {sum_p_l:.2f} MW  (Diff: {diff_p:.2f})")
        print(f"    Q Gen: {sum_q_g:.2f} Mvar vs Q Load: {sum_q_l:.2f} Mvar (Diff: {diff_q:.2f})")
        
        if diff_p < 0: print("    >> CRITICAL: MW Shortage! Increase Generator Dispatch.")
        if diff_q < 0: print("    >> CRITICAL: MVar Shortage! Voltage Collapse imminent.")

if __name__ == "__main__":
    run_analysis()
