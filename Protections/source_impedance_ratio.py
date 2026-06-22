import sys
import math

# Ensure this path matches your DIgSILENT version
sys.path.append(r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9")
import powerfactory as pf

app = pf.GetApplicationExt()
if not app:
    raise Exception("Connection to DIgSILENT Failed!")

app.ActivateProject("YOUR PROJECT") # Replace with your project name

# ==========================================
# 1. SELECT TARGET LINE AND LOCAL BUS
# ==========================================
# Replace with your actual line name
lines = app.GetCalcRelevantObjects("line_ext-trafo_1_150.ElmLne")
if not lines:
    print("[ERROR] Line not found.")
    sys.exit()

line = lines[0]

# Assuming the relay is installed at bus1 (Terminal i)
if not line.bus1 or not line.bus1.cterm:
    print("[ERROR] Local bus not connected properly.")
    sys.exit()

local_bus = line.bus1.cterm

# ==========================================
# 2. CALCULATE LINE IMPEDANCE (Zl)
# ==========================================
# Pulling the positive sequence resistance and reactance directly from the line
r1_line = line.R1
x1_line = line.X1
Zl = math.sqrt(r1_line**2 + x1_line**2)

if Zl == 0:
    print("[ERROR] Line impedance is zero. Check line parameters.")
    sys.exit()

# ==========================================
# 3. CONFIGURE & EXECUTE SHORT CIRCUIT
# ==========================================
print(f"[*] Executing 3-Phase Short Circuit at {local_bus.loc_name}...")

shc = app.GetFromStudyCase("ComShc")
if not shc:
    shc = app.GetActiveStudyCase().CreateObject("ComShc")

# Set fault location to our local bus
shc.shcobj = local_bus

# Execute the short circuit calculation
err = shc.Execute()
if err != 0:
    print("[ERROR] Short circuit calculation failed.")
    sys.exit()

# ==========================================
# 4. RETRIEVE SOURCE IMPEDANCE (Zs)
# ==========================================
# Mengambil Source Impedance dari terminal tempat rele dipasang (bus1)
Zs = line.GetAttribute("m:Zs:bus2")

# Fallback otomatis jika atribut m:Zs:bus1 kosong atau bernilai 0
# (Sering terjadi jika variabel tidak dicentang di Result/Output DIgSILENT)
if not Zs or Zs == 0:
    print("[WARN] m:Zs:bus1 kosong. Menggunakan kalkulasi Thevenin dari I_kss...")
    
    ikss = local_bus.GetAttribute("m:Ikss") # Arus gangguan hubung singkat awal (kA)
    un = local_bus.uknom # Tegangan nominal bus (kV)
    
    # Menggunakan faktor tegangan c = 1.1 (Standar IEC untuk tegangan di atas 1kV)
    if ikss and ikss > 0:
        # Rumus Thevenin: Zs = V / (akar(3) * Isc)
        Zs = (1.1 * un) / (math.sqrt(3) * ikss)
    else:
        print("[ERROR] Gagal mendapatkan arus hubung singkat (Ikss) dari bus.")
        sys.exit()

# ==========================================
# 5. CALCULATE & DISPLAY SIR
# ==========================================
SIR = Zs / Zl

print("\n" + "="*50)
print(" SOURCE IMPEDANCE RATIO (SIR) RESULTS")
print("="*50)
print(f" Line       : {line.loc_name}")
print(f" Relay Node : {local_bus.loc_name}")
print(f" Z_Line (Zl): {Zl:.4f} Ohm")
print(f" Z_Source(Zs): {Zs:.4f} Ohm")
print("-" * 50)
print(f" SIR        : {SIR:.4f}")
print("="*50)

# Typical Protection Engineering Guide:
if SIR < 0.5:
    print(" -> Category: Long Line (Low SIR). Distance protection operates very reliably.")
elif 0.5 <= SIR <= 4.0:
    print(" -> Category: Medium Line. Distance protection is generally reliable.")
else:
    print(" -> Category: Short Line (High SIR). Consider Line Differential (87L) or strict Distance zone reductions.")
