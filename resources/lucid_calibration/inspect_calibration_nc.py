import xarray as xr
import os

# Path to one of your newly created .nc files
project_root = "/media/USamsung/hyperspec/calibration"
assets_lucid_calibration_folder = os.path.join(project_root, "assets", "lucid_calibration")
nc_file_path = os.path.join(assets_lucid_calibration_folder, "OpenHSI-06_calibration_Mono12_bin2.nc") # Example

# --- Open the NetCDF file as an xarray Dataset ---
try:
    ds = xr.open_dataset(nc_file_path)

    # --- Print the Dataset summary ---
    # This is the most comprehensive overview
    print("--- Dataset Summary ---")
    print(ds)
    print("\n" + "="*30 + "\n")

    # --- Inspect Attributes (global metadata) ---
    print("--- Global Attributes ---")
    if ds.attrs:
        for attr_name, attr_value in ds.attrs.items():
            print(f"{attr_name}: {attr_value}")
    else:
        print("No global attributes.")
    print("\n" + "="*30 + "\n")

    # --- Inspect Data Variables ---
    print("--- Data Variables ---")
    for var_name in ds.data_vars:
        print(f"Variable: {var_name}")
        variable = ds[var_name]
        print(f"  Shape: {variable.shape}")
        print(f"  Dimensions: {variable.dims}")
        print(f"  Coordinates associated: {list(variable.coords.keys())}")
        print(f"  Attributes: {variable.attrs}")
        # print(f"  First few values:\n{variable.values[:5]}" if variable.ndim == 1 else f"  Sample (top-left corner of 2D array):\n{variable.values[:3, :3]}")
        print("-" * 20)
    print("\n" + "="*30 + "\n")

    # --- Inspect Coordinates ---
    # Coordinates are like special data variables that label the axes
    print("--- Coordinates ---")
    for coord_name in ds.coords:
        print(f"Coordinate: {coord_name}")
        coordinate = ds[coord_name]
        print(f"  Shape: {coordinate.shape}")
        print(f"  Dimensions: {coordinate.dims}") # Usually just itself
        print(f"  Attributes: {coordinate.attrs}")
        # print(f"  First few values:\n{coordinate.values[:5]}")
        print("-" * 20)
    print("\n" + "="*30 + "\n")

    # --- Accessing specific data ---
    # Example: Access the 'wavelengths' array (if it exists as a data variable or coordinate)
    if "wavelengths" in ds:
        wavelengths_data = ds["wavelengths"].values
        print(f"Wavelengths data (first 10): {wavelengths_data[:10]}")

    if "sfit_x" in ds and "sfit_y" in ds:
        sfit_x_data = ds["sfit_x"].values
        sfit_y_data = ds["sfit_y"].values
        # You could reconstruct the interp1d object if needed:
        # from scipy.interpolate import interp1d
        # sfit_kind = ds.attrs.get("sfit_kind", "cubic") # Assuming kind was stored as an attribute
        # reconstructed_sfit = interp1d(sfit_x_data, sfit_y_data, kind=sfit_kind)
        print("sfit_x and sfit_y data are present.")


except FileNotFoundError:
    print(f"File not found: {nc_file_path}")
except Exception as e:
    print(f"An error occurred: {e}")
finally:
    if 'ds' in locals() and ds is not None:
        ds.close() # Good practice to close the file