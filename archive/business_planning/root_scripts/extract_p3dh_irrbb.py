import sqlite3
import csv
import os

p3dh_path = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\p3dh.sqlite"
dict_path = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\bbirr.db"
out_dir = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\extracted_irrbb"

# 1. Load dictionary from bbirr.db
dict_conn = sqlite3.connect(dict_path)
dict_cur = dict_conn.cursor()
dict_cur.execute("SELECT template_code, row_code, col_code, row_name, col_name, template_name, section, unit FROM p3dh_data_dictionary")
mapping = {}
for r in dict_cur.fetchall():
    mapping[(r[0], r[1], r[2])] = (r[3], r[4], r[5], r[6], r[7])
dict_conn.close()

# 2. Extract from p3dh.sqlite
conn = sqlite3.connect(p3dh_path)
cur = conn.cursor()

# Get the columns from p3dh_facts
cur.execute("PRAGMA table_info(p3dh_facts)")
cols = [r[1] for r in cur.fetchall()]

query = """
SELECT * FROM p3dh_facts 
WHERE template LIKE '%IRRBB%' OR template LIKE 'K_68%' OR template LIKE '%Interest rate risk%'
"""
cur.execute(query)
rows = cur.fetchall()

def clean_code(val):
    try:
        if val is None: return None
        return str(int(float(val))).zfill(4)
    except:
        return str(val)
        
def get_template_code(template_str):
    if not template_str: return None
    return template_str.split(" - ")[0]

# Try to find row and col columns
row_idx = cols.index('row') if 'row' in cols else -1
col_idx = cols.index('column') if 'column' in cols else -1
template_idx = cols.index('template') if 'template' in cols else -1

if row_idx == -1 or col_idx == -1 or template_idx == -1:
    print("Could not find required columns (row, column, template). Columns are:", cols)
    conn.close()
    exit(1)

joined_rows = []
null_count = 0

for r in rows:
    t_code = get_template_code(r[template_idx])
    r_code = clean_code(r[row_idx])
    c_code = clean_code(r[col_idx])
    
    labels = mapping.get((t_code, r_code, c_code), (None, None, None, None, None))
    if labels[0] is None:
        null_count += 1
        
    joined_rows.append(r + labels)

conn.close()

# 3. Export to CSV
out_cols = cols + ["dict_row_name", "dict_col_name", "dict_template_name", "dict_section", "dict_unit"]
out_file = os.path.join(out_dir, "p3dh_facts_irrbb_labeled.csv")

with open(out_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(out_cols)
    writer.writerows(joined_rows)
    
print(f"Exported {len(joined_rows)} labeled rows to {out_file}")
print(f"Rows missing labels: {null_count}")

# Print list of unique banks
unique_banks = set(r[cols.index('entity_name')] for r in rows if 'entity_name' in cols)
print(f"Total unique banks found: {len(unique_banks)}")
