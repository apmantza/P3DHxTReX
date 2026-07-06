import sqlite3
import csv
import os

db_paths = [r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\bbirr.db",
            r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\bbirr_v2.db"]

out_dir = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\extracted_irrbb"
os.makedirs(out_dir, exist_ok=True)

for path in db_paths:
    db_name = os.path.basename(path).replace(".db", "")
    print(f"\nExporting from {db_name}...")
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        
        # Check if table exists
        cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='p3dh_data_dictionary'")
        if cur.fetchone()[0] == 0:
            print("  p3dh_data_dictionary table not found.")
            conn.close()
            continue
            
        # Load dictionary into memory for Python-side join
        cur.execute("SELECT template_code, row_code, col_code, row_name, col_name, template_name, section, unit FROM p3dh_data_dictionary")
        dict_rows = cur.fetchall()
        
        # key: (template_code, row_code, col_code)
        # value: (row_name, col_name, template_name, section, unit)
        mapping = {}
        for r in dict_rows:
            mapping[(r[0], r[1], r[2])] = (r[3], r[4], r[5], r[6], r[7])
            
        # Get peer_data IRRBB records
        cur.execute("SELECT id, bank_name, bank_lei, period, template, item, column, amount, source FROM peer_data WHERE template LIKE '%IRRBB%' OR template LIKE '%EU IRRBB%' OR template LIKE '%EU IRB%'")
        
        peer_rows = cur.fetchall()
        if not peer_rows:
            print("  No IRRBB rows found in peer_data.")
            conn.close()
            continue
            
        def clean_code(val):
            try:
                # '10.0' -> '0010', '20' -> '0020'
                return str(int(float(val))).zfill(4)
            except:
                return val
                
        def get_template_code(template_str):
            # 'K_68.00 - EU IRRBB1...' -> 'K_68.00'
            return template_str.split(" - ")[0]
            
        joined_rows = []
        null_count = 0
        for r in peer_rows:
            t_code = get_template_code(r[4])
            r_code = clean_code(r[5])
            c_code = clean_code(r[6])
            
            labels = mapping.get((t_code, r_code, c_code), (None, None, None, None, None))
            if labels[0] is None:
                null_count += 1
                
            joined_rows.append(r + labels)
            
        cols = ["id", "bank_name", "bank_lei", "period", "template", "item", "column", "amount", "source", 
                "row_name", "col_name", "template_name", "section", "unit"]
                
        out_file = os.path.join(out_dir, f"{db_name}_peer_data_irrbb_labeled.csv")
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(joined_rows)
            
        print(f"  Exported {len(joined_rows)} labeled rows to {out_file}")
        print(f"  Rows missing labels: {null_count}")
        
    except Exception as e:
        print(f"Error on {db_name}: {e}")
        
print("\nExtraction complete.")
