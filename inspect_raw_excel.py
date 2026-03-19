import pandas as pd

raw_file = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\raw\P3DH\p3dh_data.xlsx"
try:
    print(f"Reading {raw_file}...")
    df = pd.read_excel(raw_file)
    print(f"Loaded {len(df)} rows.")
    
    # Check for IRRBB
    if 'Template' in df.columns:
        irrbb_df = df[df['Template'].str.contains('IRRBB', na=False, case=False) | df['Template'].str.startswith('K_68', na=False)]
        print(f"Found {len(irrbb_df)} IRRBB rows in raw Excel.")
        
        if len(irrbb_df) > 0:
            banks = irrbb_df['Entity Name'].nunique() if 'Entity Name' in irrbb_df.columns else "Unknown"
            print(f"Unique banks in IRRBB data: {banks}")
            
    else:
        print("Template column not found. Columns are:", df.columns.tolist())
except Exception as e:
    print(f"Error reading excel: {e}")
