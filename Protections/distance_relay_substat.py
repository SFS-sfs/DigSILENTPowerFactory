#automate distance relay setting on line in DigSILENT PowerFactory

import sys
import math
import cmath

# Ensure this path matches your DIgSILENT version
sys.path.append(r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9")
import powerfactory as pf

app = pf.GetApplicationExt()
if not app:
    raise Exception("Connection to DIgSILENT Failed!")

app.ActivateProject("YOUR PROJECT")

# ==========================================
# 1. GET LINE & SELECT LOCAL/REMOTE CUBICLE
# ==========================================
lines = app.GetCalcRelevantObjects("YOUR LINE TARGET.ElmLne")
if not lines:
    print("[ERROR] Line not found.")
    sys.exit()

line = lines[0]

# --- TERMINAL SELECTOR SWITCH ---
target_terminal = 'j' 

if target_terminal == 'i':
    cub_loc = line.bus1
    cub_rem = line.bus2
else:
    cub_loc = line.bus2
    cub_rem = line.bus1

if not cub_loc or not cub_rem:
    print(f"[ERROR] Terminal on {line.loc_name} is not perfectly connected.")
    sys.exit()

# ==========================================
# 2. FIND ADJACENT LINE (Penetrating Substation Recursively)
# ==========================================
adj_line = None
max_z1 = 0.0

if cub_rem.cterm:
    bus_remote = cub_rem.cterm
    substation = bus_remote.cpSubstat 
    
    remote_cubicles = []
    
    if substation:
        print(f"\n[*] Searching for adjacent lines across the entire Substation: {substation.loc_name} ...")
        # KEY: Add parameter '1' for recursive search (penetrating voltage levels)
        remote_cubicles = substation.GetContents("*.StaCubic", 1)
    else:
        print(f"\n[*] Searching for adjacent lines on single Bus: {bus_remote.loc_name} ...")
        remote_cubicles = bus_remote.GetContents("*.StaCubic", 1)
    
    print(f"    -> Found a total of {len(remote_cubicles)} cubicles at that location.")
    
    # Loop through each found cubicle
    for c in remote_cubicles:
        obj = c.obj_id
        if obj:
            # Ensure it is an ElmLne and not our own line
            if obj.GetClassName() == "ElmLne" and obj.loc_name != line.loc_name:
                
                # Ignore if the line is Out of Service
                if hasattr(obj, 'outserv') and obj.outserv == 1:
                    continue
                
                # Get the name of the busbar/terminal where this cubicle is attached for information
                parent_term = c.GetParent().loc_name if c.GetParent() else "Unknown"
                print(f"    -> [CANDIDATE] Found Line: {obj.loc_name} (at Terminal {parent_term}, Z1 = {obj.Z1:.4f} Ohm)")
                
                # Find the highest impedance value
                if obj.Z1 > max_z1:
                    max_z1 = obj.Z1
                    adj_line = obj

if adj_line:
    print(f"\n[RESULT] Selected Adjacent Line: {adj_line.loc_name} (Z1 = {max_z1:.4f} Ohm)")
else:
    print("\n[RESULT] Still no valid adjacent line found. Fallback Zone 3 active.")

# ==========================================
# 3. IMPEDANCE PARAMETERS
# ==========================================
Zm = line.Z1
Za = adj_line.Z1 if adj_line else 0.0

phi_deg = math.degrees(math.atan2(line.X1, line.R1))

# ==========================================
# 4. RELAY SETTINGS
# ==========================================
zone_cfg = {
    1: (0.8, 0.0, 0.0), # Zone 1: 80% Main, 0% Adj, Instant (0s)
    2: (1.2, 0.0, 0.4), # Zone 2: 120% Main, 0% Adj, Delay 0.4s
    3: (1.0, 1.2, 0.8)  # Zone 3: 100% Main + 120% Adj, Delay 0.8s
}

relay_name = f"F21_Distance_{target_terminal}"
relay = cub_loc.GetContents("*.ElmRelay")[0] if cub_loc.GetContents("*.ElmRelay") else cub_loc.CreateObject("ElmRelay", relay_name)

if not relay.typ_id:
    direct_path = "Prot\\ProtRelay\\ProtGeneric\\F21 Distance Polygonal\\F21 Distance Polygonal.*"
    hasil = app.GetGlobalLibrary().GetContents(direct_path)
    relay_type = next((obj for obj in hasil if "Folder" not in obj.GetClassName()), None)
    
    if relay_type:
        relay.typ_id = relay_type
        print(f"\n[*] Relay Type Successfully Assigned: {relay_type.loc_name}")
    else:
        print("[ERROR] Failed to retrieve relay type.")
        sys.exit()

print("[*] Injecting settings into Distance Relay internal blocks...")

# ==========================================
# 5. LOOPING INTERNAL BLOCKS
# ==========================================
for blk in relay.GetContents():
    name = blk.loc_name.lower()
    
    if any(x in name for x in ["load encroachment", "starting backup"]):
        try: blk.outserv = 1
        except: pass
        continue

    if name == "measurement":
        try: blk.SetAttribute("vnom", 100.0)
        except: pass

    if name == "polarizing":
        try:
            z1 = complex(line.R1, line.X1)
            z0 = complex(line.R0, line.X0)
            if abs(z1) > 0:
                k0_complex = (z0 - z1) / (3 * z1)
                blk.SetAttribute("k0", abs(k0_complex))
                k0_angle = math.degrees(cmath.phase(k0_complex))
                for attr in ["phik0", "ak0", "angle"]:
                    try: 
                        blk.SetAttribute(attr, k0_angle)
                        break
                    except: pass
        except: pass

    if name == "starting":
        try: blk.SetAttribute("ip2", 1.20)
        except: pass

    if "polygonal" in name:
        try:
            parts = name.split()
            zone_num = int(parts[-2]) if "delay" in name else int(parts[-1])
            
            if zone_num in zone_cfg:
                if "delay" in name:
                    blk.outserv = 0
                    blk.SetAttribute("Tdelay", zone_cfg[zone_num][2])
                else:
                    k_main, k_adj, _ = zone_cfg[zone_num]
                    z_pri = (Zm * k_main) + (Za * k_adj)
                    
                    blk.outserv = 0
                    blk.SetAttribute("cpXmax", z_pri)
                    blk.SetAttribute("cpRmax", z_pri)
                    blk.SetAttribute("phi", phi_deg)
                    print(f"    -> Zone {zone_num} set: Z_Primary = {z_pri:.4f} Ohm")
            else:
                blk.outserv = 1
        except: pass

app.WriteChangesToDb()
print(f"\n[FINISHED] F21 Distance Relay at Terminal {target_terminal} ({line.loc_name}) Successfully Configured!")
