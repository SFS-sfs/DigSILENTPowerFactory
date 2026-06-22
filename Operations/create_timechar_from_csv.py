import sys
import csv

# ==========================================
# 0. PATH CONFIGURATION & INITIALIZATION
# ==========================================
PF_PATH = r"C:\Program Files\DIgSILENT\PowerFactory 2021 SP2\Python\3.9"
if PF_PATH not in sys.path:
    sys.path.append(PF_PATH)

import powerfactory as pf

class TimeCharacteristicImporter:
    def __init__(self, app):
        """Initializes with the PowerFactory application instance."""
        self.app = app

    def import_profiles_from_csv(self, oplib_folder_name, csv_file_path, start_col_pf, end_col_pf, time_format="DD.MM.YYYY hh:mm"):
        """
        Reads headers from a CSV file and creates ChaTime (Time Characteristic) 
        objects in the specified Operational Library folder.
        """
        # 1. Get the Operational Library folder
        oplib = self.app.GetProjectFolder("oplib")
        if not oplib:
            print("[ERROR] Operational Library folder not found.")
            return False

        # Find or create the target folder inside the Operational Library
        char_folder_list = oplib.GetContents(f"{oplib_folder_name}.IntFolder")
        if char_folder_list:
            char_folder = char_folder_list[0]
        else:
            char_folder = oplib.CreateObject("IntFolder", oplib_folder_name)
            print(f"[*] New folder '{oplib_folder_name}' created in Operational Library.")

        # 2. Read CSV headers for object names
        headers = []
        try:
            # Using ',' delimiter (adjust to ';' if your regional settings use semicolons)
            with open(csv_file_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.reader(f, delimiter=',') 
                headers = next(reader)
        except Exception as e:
            print(f"[ERROR] Failed to read CSV: {e}")
            return False

        # 3. Loop through columns to create ChaTime objects
        print("\n[*] Starting ChaTime object processing...")
        print("-" * 60)

        count = 0
        for col_pf in range(start_col_pf, end_col_pf + 1):
            python_idx = col_pf - 1 # Python array index starts at 0
            
            # Get column header from CSV for the object name. Use default if empty.
            if python_idx < len(headers) and headers[python_idx].strip():
                obj_name = headers[python_idx].strip()
            else:
                obj_name = f"Profile_Column_{col_pf}"
                
            # Create a new ChaTime object in the target folder
            cha_obj = char_folder.CreateObject("ChaTime", obj_name)
            
            # Inject Attributes as requested
            cha_obj.source = 1                        # Source: 1 = File
            cha_obj.iopt_stamp = 1                    # Time stamp option: 1 = Use Timestamp
            
            # --- UPDATED: Using the dynamic time_format parameter ---
            cha_obj.timeformat = time_format          
            
            cha_obj.f_name = csv_file_path            # File path (f_name)
            cha_obj.timecol = 1                       # Time Column (Column A)
            cha_obj.datacol = col_pf                  # Data Column
            cha_obj.iopt_file = 0                     # File Type: 0 = CSV
            cha_obj.usage = 2                         # Usage: 2 = Scaling
            
            print(f"    -> [OK] Created: '{obj_name}' (Reading Column {col_pf})")
            count += 1

        return count


# ==========================================
# MAIN EXECUTION (EXAMPLE USAGE)
# ==========================================
if __name__ == "__main__":
    try:
        # 1. Initialize Application & Activate Project
        app = pf.GetApplicationExt()
        if not app: 
            raise Exception("Connection to PowerFactory Failed!")

        project_name = "Merauke Geographical"
        err = app.ActivateProject(project_name)
        if err:
            raise Exception(f"Failed to activate project: {project_name}")

        print(f"\n[INITIALIZED] Project '{project_name}' activated successfully.")

        # 2. Instantiate the Utility Class
        importer = TimeCharacteristicImporter(app)

        # 3. Define Configurations
        TARGET_CSV_PATH = r"C:\Users\ASUS\Documents\SF\LAPI\Merauke\operasi_merauke2.csv"
        TARGET_FOLDER = "Operasi"
        
        # Define your time format here
        TARGET_TIME_FORMAT = "DD.MM.YYYY hh:mm" 
        
        START_COL = 2
        END_COL = 33

        # 4. Execute the Import Process
        objects_created = importer.import_profiles_from_csv(
            oplib_folder_name=TARGET_FOLDER,
            csv_file_path=TARGET_CSV_PATH,
            start_col_pf=START_COL,
            end_col_pf=END_COL,
            time_format=TARGET_TIME_FORMAT  # Passing the format input here
        )

        # 5. Save all changes to the database
        if objects_created:
            app.WriteChangesToDb()
            print("-" * 60)
            print(f"\n[FINISHED] Total of {objects_created} ChaTime objects successfully imported and saved!")
        
    except Exception as e:
        print(f"\n[ABORTED] Process failed: {e}")
