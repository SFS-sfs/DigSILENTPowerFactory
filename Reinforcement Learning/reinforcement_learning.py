import gymnasium as gym
from gymnasium import spaces
import numpy as np
import sys
import os
import time

# ==========================================
# 1. CONFIGURATION
# ==========================================
class GridConfig:
    PF_PATH = r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9"
    PROJECT_NAME = "14 Bus System" 
    
    TARGET_VOLTAGE = 1.0  
    AGGRESSIVENESS = 0.25  
    
    # Voltage Limits (Fixed)
    V_PENALTY_MIN, V_PENALTY_MAX = 0.95, 1.05
    
    # Loading Limits (For Logic Reference)
    GEN_LOAD_MIN = 70.0
    GEN_LOAD_MAX = 98.0
    
    TRAFO_LINE_WARN = 80.0
    TRAFO_LINE_MAX  = 98.0

# ==========================================
# 2. CONNECTION
# ==========================================
if not os.path.exists(GridConfig.PF_PATH): sys.exit(1)
if GridConfig.PF_PATH not in sys.path: sys.path.append(GridConfig.PF_PATH)
try: import powerfactory as pf
except ImportError: sys.exit(1)

# ==========================================
# 3. ENVIRONMENT
# ==========================================
class PowerGridEnv(gym.Env):
    def __init__(self):
        super(PowerGridEnv, self).__init__()
        
        print("\n[Env] Init V41 (Specific Rewards: Gen vs Grid)...")
        self.app = pf.GetApplicationExt()
        if not self.app: raise Exception("Connection Failed")
        
        self.app.SetGuiUpdateEnabled(0) 
        
        # 1. Project
        print(f"   [Init] Activating Project: '{GridConfig.PROJECT_NAME}'...")
        err = self.app.ActivateProject(GridConfig.PROJECT_NAME)
        if err != 0:
            print(f"   [ERROR] Failed to activate project. Check the name '{GridConfig.PROJECT_NAME}'.")
            sys.exit(1)
        
        # 2. Study Case
        self.active_case = self.app.GetActiveStudyCase()
        if not self.active_case:
            print("   [ERROR] No active Study Case!")
            sys.exit(1)
        print(f"   [Context] Study Case   : {self.active_case.loc_name}")

        # 3. Scenario (Passive)
        self.active_scen = self.app.GetActiveScenario()
        s_name = self.active_scen.loc_name if self.active_scen else "Base Case"
        print(f"   [Context] Scenario     : {s_name}")
        
        self.ldf = self.app.GetFromStudyCase("ComLdf")
        self.ldf.SetAttribute("iopt_at", 0) 
        
        # 4. Grid Objects
        raw_gens = self.app.GetCalcRelevantObjects("*.ElmSym")
        self.gens = []
        for g in raw_gens:
            if g.GetAttribute("outserv") == 0:
                g.SetAttribute("mode_inp", "PC")
                self.gens.append(g)
        
        raw_trafos = self.app.GetCalcRelevantObjects("*.ElmTr2")
        self.controllable_trafos = []
        for t in raw_trafos:
            if t.GetAttribute("outserv") == 0 and t.GetAttribute("t:ntpmn") is not None:
                self.controllable_trafos.append(t)

        raw_buses = self.app.GetCalcRelevantObjects("*.ElmTerm")
        self.buses = [b for b in raw_buses if b.GetAttribute("outserv") == 0]
        
        raw_lines = self.app.GetCalcRelevantObjects("*.ElmLne")
        self.lines = [l for l in raw_lines if l.GetAttribute("outserv") == 0]
        
        raw_loads = self.app.GetCalcRelevantObjects("*.ElmLod")
        self.loads = [l for l in raw_loads if l.GetAttribute("outserv") == 0]
        
        print(f"   [Valid] {len(self.buses)} Buses, {len(self.gens)} Gens, {len(self.controllable_trafos)} Transformers.")
        
        if len(self.buses) == 0:
            print("   [CRITICAL] 0 Buses detected. Check Network Data.")
            sys.exit(1)

        # 5. Init Snapshot
        self.snapshot = {'gens': [], 'trafos': []}
        if self.ldf.Execute() != 0:
            print("   [WARNING] Grid Diverged during startup.")
        
        self.update_snapshot() 

        # Spaces
        n_actions = (len(self.gens) * 2) + len(self.controllable_trafos)
        if n_actions > 0:
            self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(n_actions,), dtype=np.float32)
        else:
            self.action_space = spaces.Box(0, 0, shape=(0,), dtype=np.float32)

        n_obs = (len(self.loads)*2) + len(self.buses) + len(self.lines) + len(self.controllable_trafos) + len(self.gens)
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(n_obs,), dtype=np.float32)

    def update_snapshot(self):
        self.snapshot['gens'] = []
        for g in self.gens:
            self.snapshot['gens'].append({'p': g.GetAttribute("pgini"), 'pf': g.GetAttribute("cosgini")})
        self.snapshot['trafos'] = []
        for t in self.controllable_trafos:
            self.snapshot['trafos'].append(t.GetAttribute("nntap"))

    def restore_snapshot(self):
        for i, g in enumerate(self.gens):
            base = self.snapshot['gens'][i]
            g.SetAttribute("pgini", base['p'])
            g.SetAttribute("cosgini", base['pf'])
        for i, t in enumerate(self.controllable_trafos):
            base_tap = self.snapshot['trafos'][i]
            t.SetAttribute("nntap", int(base_tap))
        self.ldf.Execute()

    def step(self, action):
        idx = 0
        # Gen
        for i, g in enumerate(self.gens):
            base = self.snapshot['gens'][i]
            act_p = float(action[idx])
            act_c = float(action[idx+1])
            
            base_p = base['p'] if base['p'] > 1.0 else 10.0 
            new_p = base_p * (1.0 + (act_p * GridConfig.AGGRESSIVENESS))
            g.SetAttribute("pgini", max(0.0, new_p))
            
            new_pf = np.clip(base['pf'] + (act_c * 0.1), 0.80, 1.0)
            g.SetAttribute("cosgini", new_pf)
            idx += 2 

        # Transformer
        for i, t in enumerate(self.controllable_trafos):
            base_tap = self.snapshot['trafos'][i]
            tap_shift = int(round(action[idx] * 4 * GridConfig.AGGRESSIVENESS)) 
            if tap_shift == 0 and abs(action[idx]) > 0.5: tap_shift = 1 if action[idx] > 0 else -1
            
            min_tap = int(t.GetAttribute("t:ntpmn"))
            max_tap = int(t.GetAttribute("t:ntpmx"))
            new_tap = int(np.clip(base_tap + tap_shift, min_tap, max_tap))
            t.SetAttribute("nntap", new_tap)
            idx += 1

        err = self.ldf.Execute()
        is_converged = (err == 0)
        status = "OK" if is_converged else "DIVERGED"
        
        obs = self._get_obs()
        
        # --- REWARD SYSTEM V41 (SPECIFIC RULES) ---
        reward = -100000.0 # Penalty for Divergence
        
        if is_converged:
            # 1. Voltage Base Reward
            voltages = []
            for b in self.buses:
                try: voltages.append(b.GetAttribute("m:u"))
                except: pass 
            
            if len(voltages) > 0:
                mse = np.mean([(v - GridConfig.TARGET_VOLTAGE)**2 for v in voltages])
                reward = -mse * 100.0
                
                # Voltage Penalty (Strict)
                if any(v < GridConfig.V_PENALTY_MIN or v > GridConfig.V_PENALTY_MAX for v in voltages):
                    reward -= 100
            else:
                reward = -50000.0

            # 2. GENERATOR LOADING RULES
            for g in self.gens:
                try:
                    load = g.GetAttribute("c:loading")
                    if load > GridConfig.GEN_LOAD_MAX: # > 98%
                        reward -= 200.0
                    elif load < GridConfig.GEN_LOAD_MIN: # < 60%
                        reward -= 100.0
                except: pass

            # 3. TRANSFORMER & LINE LOADING RULES
            # Combined lists because the rules are identical
            grid_components = self.lines + self.controllable_trafos
            
            for comp in grid_components:
                try:
                    load = comp.GetAttribute("c:loading")
                    if load > GridConfig.TRAFO_LINE_MAX: # > 98%
                        reward -= 100.0
                    elif load > GridConfig.TRAFO_LINE_WARN: # > 80%
                        reward -= 25.0
                    # < 60% is Safe (No Penalty)
                except: pass
        
        info = {"status": status}
        return np.array(obs, dtype=np.float32), reward, not is_converged, False, info

    def _get_obs(self):
        obs = []
        for l in self.loads: 
            try: obs.extend([l.GetAttribute("m:P:bus1"), l.GetAttribute("m:Q:bus1")])
            except: obs.extend([0,0])
        for b in self.buses: 
            try: obs.append(b.GetAttribute("m:u"))
            except: obs.append(1.0)
        for l in self.lines: 
            try: obs.append(l.GetAttribute("c:loading"))
            except: obs.append(0)
        for t in self.controllable_trafos: 
            try: obs.append(t.GetAttribute("c:loading"))
            except: obs.append(0)
        for g in self.gens: 
            try: obs.append(g.GetAttribute("c:loading"))
            except: obs.append(0)
        return obs

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.restore_snapshot()
        return np.array(self._get_obs(), dtype=np.float32), {}
    
    def save_final(self):
        self.app.SetGuiUpdateEnabled(1)
        print("\n" + "="*60)
        print("[DB] SAVING CHANGES...")
        
        if self.active_scen:
            print(f"     Target: Scenario '{self.active_scen.loc_name}'")
            self.active_scen.Save()
        else:
            print(f"     Target: Base Case")
        
        self.app.WriteChangesToDb()
        time.sleep(1.0)
        print("[DB] Saved.")
        print("="*60)

# ==========================================
# 4. MAIN PROGRAM
# ==========================================
if __name__ == "__main__":
    env = PowerGridEnv()
    
    # --- CAPTURE INITIAL CONDITIONS (BEFORE) ---
    print("\n[INFO] Recording initial grid conditions...")
    initial_state = {
        'gens': [],
        'trafos': []
    }
    for g in env.gens:
        initial_state['gens'].append({
            'name': g.loc_name,
            'p': g.GetAttribute("pgini"),
            'pf': g.GetAttribute("cosgini")
        })
    for t in env.controllable_trafos:
        initial_state['trafos'].append({
            'name': t.loc_name,
            'tap': t.GetAttribute("nntap")
        })

    # Note: Updated print to match the 200 loops in the code below
    print("\n--- DYNAMIC BASE OPTIMIZATION (200 EPISODES) ---")
    
    # Init Baseline
    env.reset()
    obs, best_reward, done, _, info = env.step(np.zeros(env.action_space.shape))
    print(f"[INIT] Reward: {best_reward:.6f} | Status: {info['status']}")
    
    if info['status'] == "DIVERGED":
        best_reward = -100000.0
    else:
        env.update_snapshot()
    
    # Loop
    for ep in range(200):
        env.reset()
        action = env.action_space.sample()
        obs, reward, done, _, info = env.step(action)
        
        print(f"Ep {ep+1:<2} | Reward: {reward:<10.6f} | Status: {info['status']}", end="")
        
        if info['status'] == "OK" and reward > best_reward:
            best_reward = reward
            print(f"   >>> NEW BEST! Updating Base...")
            env.update_snapshot()
        else:
            print("") 

    print("\n" + "="*60)
    print(f"   FINAL RESULT (Reward: {best_reward:.6f})")
    
    if best_reward > -50000:
        env.restore_snapshot() # Apply best state
        
        # --- FULL CHANGE REPORT ---
        print("\n" + "="*80)
        print(f"{'COMPONENT':<20} | {'PARAMETER':<10} | {'INITIAL (Before)':<15} -> {'FINAL (After)':<15} | {'DIFF':<10}")
        print("-" * 80)
        
        # 1. Check Generator
        for i, g in enumerate(env.gens):
            init = initial_state['gens'][i]
            
            curr_p = g.GetAttribute("pgini")
            curr_pf = g.GetAttribute("cosgini")
            
            # Compare P
            if abs(curr_p - init['p']) > 0.01:
                print(f"{init['name']:<20} | P (MW)     | {init['p']:<15.2f} -> {curr_p:<15.2f} | {curr_p - init['p']:+.2f}")
            
            # Compare CosPhi
            if abs(curr_pf - init['pf']) > 0.001:
                print(f"{init['name']:<20} | CosPhi     | {init['pf']:<15.4f} -> {curr_pf:<15.4f} | {curr_pf - init['pf']:+.4f}")

        # 2. Check Transformer
        for i, t in enumerate(env.controllable_trafos):
            init = initial_state['trafos'][i]
            curr_tap = int(t.GetAttribute("nntap"))
            
            if curr_tap != init['tap']:
                print(f"{init['name']:<20} | Tap Pos    | {init['tap']:<15} -> {curr_tap:<15} | {curr_tap - init['tap']:+}")
        
        print("="*80)
        
        # Save
        env.save_final()
    else:
        print("[FAIL] No valid solution found (All diverged/severe overload).")
