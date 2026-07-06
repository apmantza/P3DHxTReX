import sqlite3

path = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\p3dh.sqlite"
conn = sqlite3.connect(path)
cur = conn.cursor()

try:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    print("Tables in p3dh.sqlite:", tables)
    
    for t in tables:
        try:
            cur.execute(f"SELECT count(*) FROM {t}")
            print(f"  {t}: {cur.fetchone()[0]} rows")
            
            # Print sample columns
            cur.execute(f"PRAGMA table_info({t})")
            cols = [r[1] for r in cur.fetchall()]
            print(f"    Columns: {cols[:8]}...")
            
            # Look for IRRBB templates
            if 'template' in cols or 'template_code' in cols:
                col_name = 'template' if 'template' in cols else 'template_code'
                cur.execute(f"SELECT DISTINCT {col_name} FROM {t} WHERE {col_name} LIKE '%IRRBB%' OR {col_name} LIKE 'K_68%'")
                print(f"    IRRBB templates found: {cur.fetchall()}")
                
        except Exception as e:
            print(f"  Error inspecting {t}: {e}")
            
except Exception as e:
    print(f"Error accessing p3dh.sqlite: {e}")
    
conn.close()
