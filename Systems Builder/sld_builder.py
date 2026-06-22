import sys

# ==========================================
# 0. PATH CONFIGURATION
# ==========================================
PF_PATH = r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9"
if PF_PATH not in sys.path:
    sys.path.append(PF_PATH)

import powerfactory as pf

class TopologyBuilder:
    """A generic utility class to build and draw PowerFactory networks."""
    
    def __init__(self, project_name, netdat_name="Grid.ElmNet", canvas_name="Grid.IntGrfnet"):
        """Initializes the connection to PowerFactory and sets up target folders."""
        self.app = pf.GetApplicationExt()
        if not self.app: 
            raise Exception("Connection to PowerFactory Failed!")

        err = self.app.ActivateProject(project_name)
        if err:
            raise Exception(f"Failed to activate project: {project_name}")

        try:
            self.netdat = self.app.GetProjectFolder("netdat").GetContents(netdat_name)[0]
            self.canvas = self.app.GetProjectFolder("dia").GetContents(canvas_name)[0]
        except IndexError:
            raise Exception("Network Data (netdat) or Canvas (dia) folder/contents not found.")

        self.canvas.Show()
        print(f"[INITIALIZED] Project '{project_name}' activated and canvas ready.")

    def _connect_element(self, element, target_bus, side="bus1"):
        """Internal helper to create a cubicle and connect an element to a bus."""
        cub = target_bus.CreateObject("StaCubic", f"Cub_{element.loc_name}")
        element.SetAttribute(side, cub)

    def _create_connection_lines(self, parent_grf, conn_num, points):
        """Internal helper to draw graphic connection lines between elements."""
        con = parent_grf.CreateObject("IntGrfcon", f"GCO_{conn_num+1}")
        if not con: 
            return
        
        try: 
            con.SetAttribute("iDatConNr", conn_num)
        except: 
            pass
        
        rx_list = con.GetAttribute("rX")
        ry_list = con.GetAttribute("rY")
        
        if rx_list and ry_list:
            for idx, (x, y) in enumerate(points):
                if idx < len(rx_list):
                    rx_list[idx] = float(x)
                    ry_list[idx] = float(y)
            try:
                con.SetAttribute("rX", rx_list)
                con.SetAttribute("rY", ry_list)
            except Exception as e:
                print(f"       [WARN] Failed to reset coordinates: {e}")

    def create_bus(self, name, y_pos, x_center, size_x):
        """Creates a Bus (ElmTerm) and its visual representation."""
        print(f"    -> Creating Bus: {name}")
        bus = self.netdat.CreateObject("ElmTerm", name)
        bus.uknom = 20.0 # Default voltage, can be modified later
        
        grf = self.canvas.CreateObject("IntGrf", f"Vis_{name}")
        grf.SetAttribute("pDataObj", bus)
        grf.SetAttribute("sSymNam", "TermStrip")
        
        grf.SetAttribute("rCenterX", x_center) 
        grf.SetAttribute("rCenterY", y_pos)
        grf.SetAttribute("rSizeX", size_x) 
        grf.SetAttribute("rSizeY", 1.0)
        
        return bus

    def create_branch(self, class_type, name, sym_name, x_pos, y_pos, bus_from, bus_to=None, rot=0, connections=None):
        """Creates an electrical component (Line, Trafo, Load, Gen) and places it on the canvas."""
        print(f"    -> Creating Component: {name}")
        
        elm = self.netdat.CreateObject(class_type, name)
        
        # Connection handling based on element type
        if class_type == "ElmTr2":
            self._connect_element(elm, bus_from, "bushv")
            if bus_to: 
                self._connect_element(elm, bus_to, "buslv")
        else:
            # For ElmLne, ElmSym, ElmLod (all use bus1 for the first connection)
            self._connect_element(elm, bus_from, "bus1")
            # ElmLne has bus2
            if bus_to and class_type == "ElmLne": 
                self._connect_element(elm, bus_to, "bus2")

        # Graphics handling
        grf = self.canvas.CreateObject("IntGrf", f"Vis_{name}")
        grf.SetAttribute("pDataObj", elm)
        grf.SetAttribute("sSymNam", sym_name)
        grf.SetAttribute("rCenterX", x_pos)
        grf.SetAttribute("rCenterY", y_pos)
        grf.SetAttribute("rSizeX", 1.0)
        grf.SetAttribute("rSizeY", 1.0)
        
        if rot != 0:
            try: 
                grf.SetAttribute("iAngle", rot)
            except: 
                pass

        if connections and grf:
            for i, points in enumerate(connections):
                self._create_connection_lines(grf, i, points)
                
        return elm

    def save(self):
        """Commits changes to the PowerFactory database."""
        self.app.WriteChangesToDb()
        print("\n[FINISHED] Database changes saved successfully!")


# ==========================================
# MAIN EXECUTION (EXAMPLE NETWORK BUILDER)
# ==========================================
if __name__ == "__main__":
    try:
        # 1. Initialize the Utility Class
        builder = TopologyBuilder(project_name="YOUR PROJECT")

        print("\n[*] STARTING COMPLETE TOPOLOGY REPLICATION...")

        # --- A. BUSES (TERMINALS) ---
        bus_t2 = builder.create_bus("Terminal(2)", 161.875, x_center=113.75, size_x=4.0)  
        bus_t1 = builder.create_bus("Terminal(1)", 135.625, x_center=105.0, size_x=4.0)  
        bus_au = builder.create_bus("Bus_Auto_02", 93.75, x_center=105.0, size_x=4.0)    
        bus_b1 = builder.create_bus("Terminal", 54.375, x_center=126.875, size_x=4.0)       

        # --- B. COMPONENTS & CONNECTIONS ---
        
        # 1. Transformer
        builder.create_branch(
            "ElmTr2", "EL_TRF2", "d_tr2", 
            96.25, 148.75, bus_t2, bus_t1, rot=180,
            connections=[
                [(96.25, 144.375), (96.25, 135.625)], 
                [(96.25, 153.125), (96.25, 161.875)]  
            ]
        )

        # 2. Line 1
        builder.create_branch(
            "ElmLne", "Line(1)", "d_lin", 
            87.5, 114.6875, bus_t1, bus_au,
            connections=[
                [(87.5, 114.6875), (87.5, 93.75)],
                [(87.5, 114.6875), (113.75, 114.6875), (113.75, 135.625)]
            ]
        )

        # 3. Generator
        builder.create_branch(
            "ElmSym", "EL_GEN2", "d_symg", 
            91.875, 74.375, bus_au,
            connections=[
                [(91.875, 78.75), (91.875, 93.75)]
            ]
        )

        # 4. Line 2
        builder.create_branch(
            "ElmLne", "Line", "d_lin", 
            122.5, 74.0625, bus_au, bus_b1,
            connections=[
                [(122.5, 74.0625), (122.5, 93.75)],
                [(122.5, 74.0625), (122.5, 54.375)]
            ]
        )

        # 5. General Load 1 (Top)
        builder.create_branch(
            "ElmLod", "General Load 1", "d_load", 
            131.25, 144.375, bus_t2, 
            connections=[
                [(131.25, 148.75), (131.25, 161.875)]
            ]
        )

        # 6. General Load 2 (Bottom)
        builder.create_branch(
            "ElmLod", "General Load 2", "d_load", 
            131.25, 36.5625, bus_b1, 
            connections=[
                [(131.25, 40.9375), (131.25, 54.375)]
            ]
        )

        # 2. Save Changes
        builder.save()

    except Exception as e:
        print(f"\n[ABORTED] Process failed: {e}")
