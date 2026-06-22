import sys
import difflib

# ==========================================
# 0. PATH CONFIGURATION & INITIALIZATION
# ==========================================
PF_PATH = r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9"
if PF_PATH not in sys.path:
    sys.path.append(PF_PATH)

import powerfactory as pf

class ProfileAssigner:
    """A utility class to map Time Characteristics (ChaTime) to network elements."""
    
    def __init__(self, app):
        """Initializes with the PowerFactory application instance."""
        self.app = app

    def assign_profiles(self, element_filter, oplib_folder_name, profile_prefix="*", threshold=0.6):
        """
        Retrieves elements based on the filter, finds ChaTime profiles,
        and assigns them using fuzzy matching.
        
        Args:
            element_filter (str): e.g., "*.ElmLod", "*.ElmGenstat", "*.ElmSym", "*.ElmPvsys"
            oplib_folder_name (str): The folder name inside the Operational Library.
            profile_prefix (str): Prefix for the ChaTime files (e.g., "P_*").
            threshold (float): Fuzzy matching sensitivity (0.0 to 1.0).
        """
        # --- Determine Target Parameter ---
        # If the element is a Load, use 'plini'. Otherwise (Gen/PV), use 'pgini'.
        if "ElmLod" in element_filter:
            target_param = "plini"
        else:
            target_param = "pgini"

        print(f"\n[*] Starting profile assignment for: {element_filter}")
        print(f"[*] Target parameter determined as: '{target_param}'")
        
        # ==========================================
        # 1. GET TARGET ELEMENTS
        # ==========================================
        elements = self.app.GetCalcRelevantObjects(element_filter)
        if not elements:
            print(f"[ERROR] No elements found matching the filter '{element_filter}'.")
            return False

        # ==========================================
        # 2. GET 'ChaTime' PROFILES FROM OPLIB
        # ==========================================
        oplib = self.app.GetProjectFolder("oplib")
        if not oplib:
            print("[ERROR] Operational Library folder not found.")
            return False

        oplib_folders = oplib.GetContents(f"{oplib_folder_name}.IntFolder")
        if not oplib_folders:
            print(f"[ERROR] Folder '{oplib_folder_name}' not found in Operational Library.")
            return False

        target_folder = oplib_folders[0]

        cha_times = target_folder.GetContents(f"{profile_prefix}.ChaTime")
        if not cha_times:
            print(f"[ERROR] No ChaTime files found with prefix '{profile_prefix}' in folder '{oplib_folder_name}'.")
            return False

        # ==========================================
        # 3. LOOPING & FUZZY MATCHING
        # ==========================================
        print("-" * 80)
        match_count = 0

        for elm in elements:
            # Normalize element name
            elm_name_clean = elm.loc_name.lower().replace("-", " ").replace("_", " ")
            
            best_match = None
            highest_ratio = 0.0
            
            for cha in cha_times:
                cha_name_clean = cha.loc_name.lower().replace("-", " ").replace("_", " ")
                ratio = difflib.SequenceMatcher(None, elm_name_clean, cha_name_clean).ratio()
                
                if ratio > highest_ratio:
                    highest_ratio = ratio
                    best_match = cha
                    
            if best_match and highest_ratio >= threshold:
                try:
                    # --- NEW LOGIC FOR ChaRef ---
                    # Search for the ChaRef object (e.g., "plini(1)" or "pgini(1)")
                    ref_search_string = f"{target_param}*.ChaRef"
                    ref_list = elm.GetContents(ref_search_string)
                    
                    param_ref = None
                    if ref_list:
                        param_ref = ref_list[0] # Use existing ChaRef
                    else:
                        # Create a new ChaRef object if it doesn't exist
                        ref_name = f"{target_param}(1)"
                        param_ref = elm.CreateObject("ChaRef", ref_name)
                    
                    # Inject the matched ChaTime file into the 'typ_id' attribute of the ChaRef
                    param_ref.typ_id = best_match
                    
                    print(f"[OK] {elm.loc_name:<20} -> {best_match.loc_name:<20} | Match: {highest_ratio*100:.0f}%")
                    match_count += 1
                    
                except Exception as e:
                    print(f"[ERROR] Failed to assign ChaTime to {elm.loc_name}: {e}")
            else:
                print(f"[WARN] {elm.loc_name:<20} -> NO MATCH FOUND (Max similarity only {highest_ratio*100:.0f}%)")

        print("-" * 80)
        print(f"[FINISHED] {match_count} out of {len(elements)} elements successfully assigned profiles!")
        return True


# ==========================================
# MAIN EXECUTION (EXAMPLE USAGE)
# ==========================================
if __name__ == "__main__":
    try:
        # 1. Initialize Application & Activate Project
        app = pf.GetApplicationExt()
        if not app: 
            raise Exception("Connection to PowerFactory Failed!")

        project_name = "YOUR PROJECT"
        err = app.ActivateProject(project_name)
        if err:
            raise Exception(f"Failed to activate project: {project_name}")

        print(f"\n[INITIALIZED] Project '{project_name}' activated successfully.")

        # 2. Instantiate the Utility Class
        assigner = ProfileAssigner(app)

        # 3. Assign Profiles to LOADS (Automatically targets 'plini')
        assigner.assign_profiles(
            element_filter="*.ElmLod", 
            oplib_folder_name="Operasi", 
            profile_prefix="P_*", 
            threshold=0.6
        )

        # 4. Assign Profiles to STATIC GENERATORS (Automatically targets 'pgini')
        assigner.assign_profiles(
            element_filter="*.ElmGenstat", 
            oplib_folder_name="Operasi", 
            profile_prefix="P_*", 
            threshold=0.6
        )
        
        # You can add more like "*.ElmPvsys" or "*.ElmSym" here as needed...

        # 5. Save all changes to the database
        app.WriteChangesToDb()
        print("\n[SUCCESS] Database changes saved successfully!")
        
    except Exception as e:
        print(f"\n[ABORTED] Process failed: {e}")
