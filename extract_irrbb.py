import sqlite3
import csv
import os

db_paths = [r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\bbirr.db",
            r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\bbirr_v2.db"]

out_dir = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\extracted_irrbb"
os.makedirs(out_dir, exist_ok=True)

for path in db_paths:
    db_name = os.path.basename(path).replace(".db", "")
    print(f"Exporting from {db_name}...")
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        
        # peer_data
        cur.execute("SELECT * FROM peer_data WHERE template LIKE '%IRRBB%' OR template LIKE '%EU IRRBB%' OR template LIKE '%EU IRB%'")
        rows = cur.fetchall()
        if rows:
            cols = [desc[0] for desc in cur.description]
            out_file = os.path.join(out_dir, f"{db_name}_peer_data_irrbb.csv")
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(cols)
                writer.writerows(rows)
            print(f"  Exported {len(rows)} rows to {out_file}")
            
        # canonical_facts
        cur.execute("SELECT * FROM canonical_facts WHERE template LIKE '%IRRBB%' OR template LIKE '%EU IRRBB%' OR template LIKE '%EU IRB%'")
        rows = cur.fetchall()
        if rows:
            cols = [desc[0] for desc in cur.description]
            out_file = os.path.join(out_dir, f"{db_name}_canonical_facts_irrbb.csv")
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(cols)
                writer.writerows(rows)
            print(f"  Exported {len(rows)} rows to {out_file}")
            
        conn.close()
    except Exception as e:
        print(f"Error on {db_name}: {e}")

print("Extraction complete.")
