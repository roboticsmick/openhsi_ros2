# convert_old_pkl.py (simpler version for older Python env)
import os
import sys
import warnings

# --- Path Setup (to find your local openhsi) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Assuming convert_old_pkl.py is in /media/USamsung/hyperspec/calibration/scripts/
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

OPENHSI_LOCAL_PATH = os.path.join(PROJECT_ROOT, "openhsi_headwall")
if OPENHSI_LOCAL_PATH not in sys.path:
    sys.path.insert(0, OPENHSI_LOCAL_PATH)
    print(f"Added to sys.path: {OPENHSI_LOCAL_PATH}")

# We might not need Arena SDK for this if CameraProperties loads independently
# --- End Path Setup ---

try:
    # CameraProperties is in openhsi.data
    from openhsi.data import CameraProperties
    print("Successfully imported CameraProperties from local openhsi.")
except ImportError as e:
    print(f"Error importing CameraProperties from local openhsi: {e}")
    print("Make sure openhsi_headwall and its openhsi subfolder are correctly structured and accessible.")
    sys.exit(1)

ASSETS_LUCID_CALIBRATION_FOLDER = os.path.join(PROJECT_ROOT, "assets", "lucid_calibration")

# List of your pkl files
# The CameraProperties class doesn't strictly need the .json settings for just loading a .pkl
# and then dumping it (as it directly loads self.calibration from the pickle).
# It might use self.json_path to name the output .nc file if json_path is also provided,
# but the core load/save for calibration data is independent of json_path content here.
pkl_files_to_convert = [
    "OpenHSI-06_calibration_Mono12_bin1.pkl",
    "OpenHSI-06_calibration_Mono12_bin1_window.pkl",
    "OpenHSI-06_calibration_Mono12_bin2.pkl",
    "OpenHSI-06_calibration_Mono12_bin2_window.pkl",
    "OpenHSI-06_calibration_Mono8_bin1.pkl",
    "OpenHSI-06_calibration_Mono8_bin1_window.pkl",
    "OpenHSI-06_calibration_Mono8_bin2.pkl",
    "OpenHSI-06_calibration_Mono8_bin2_window.pkl",
]

def trigger_pkl_to_nc_conversion(pkl_filename_only):
    pkl_path = os.path.join(ASSETS_LUCID_CALIBRATION_FOLDER, pkl_filename_only)
    # The expected .nc output path, according to CameraProperties logic
    nc_output_path_expected = os.path.join(ASSETS_LUCID_CALIBRATION_FOLDER,
                                           os.path.splitext(pkl_filename_only)[0] + ".nc")

    print(f"Attempting to process {pkl_path}...")
    print(f"  This should load the .pkl and automatically save it as {nc_output_path_expected}")

    if not os.path.exists(pkl_path):
        print(f"  ERROR: PKL file not found: {pkl_path}")
        return

    try:
        # Instantiate CameraProperties. This will trigger the .pkl load and
        # the automatic .nc save if successful.
        # We pass cal_path (which will be our pkl_path).
        # The json_path is not strictly needed for this conversion part but
        # CameraProperties will use it to try and form the output .nc path
        # if not None, so let's provide a dummy or related one.
        # Or, we can let it be None and it will use cal_path to derive the .nc name.
        print(f"  Instantiating CameraProperties with cal_path='{pkl_path}'...")
        
        # Suppress the specific deprecation warning during this conversion
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Pickle calibration files are deprecated.*",
                category=DeprecationWarning,
                module="openhsi.data" # Be specific to avoid silencing other warnings
            )
            # The CameraProperties __init__ will print:
            # "Updated calibration file saved at <...>.nc" if successful.
            props = CameraProperties(cal_path=pkl_path) # json_path=None is fine

        if os.path.exists(nc_output_path_expected):
            print(f"  SUCCESS: Verified that {nc_output_path_expected} was created/updated.")
        else:
            print(f"  WARNING: {nc_output_path_expected} was NOT found after instantiation. Check logs from CameraProperties.")

    except Exception as e:
        # The error message you initially saw is re-raised by CameraProperties
        print(f"  ERROR processing {pkl_filename_only}: {e}")
        # No need for full traceback here as CameraProperties already formats it.
        print(f"  This usually means the Python environment (xarray/pandas versions) is not correct for reading this PKL.")
    print("-" * 30)

if __name__ == "__main__":
    print("Starting PKL to NC conversion process...")
    print("This script relies on the openhsi.data.CameraProperties class")
    print("to load the .pkl and automatically save it as .nc.")
    print("Ensure you are running this in an environment with xarray==2022.3.0 (e.g., Python 3.10).\n")

    for pkl_file in pkl_files_to_convert:
        trigger_pkl_to_nc_conversion(pkl_file)

    print("\nAll conversions attempted.")
    print("Check the 'assets/lucid_calibration/' folder for new/updated .nc files.")
    print("If successful, you can now use these .nc files in your main Python 3.12 environment.")