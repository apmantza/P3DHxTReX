import sqlite3

path = r"c:\Users\apman\OneDrive\Desktop\BBIRR\data\processed\bbirr.db"
conn = sqlite3.connect(path)
cur = conn.cursor()

cur.execute("SELECT template_code, row_code, col_code, row_name, col_name FROM p3dh_data_dictionary WHERE template_code = 'K_68.00' LIMIT 5")
print("\nDict for K_68.00:")
rows = cur.fetchall()
if not rows:
    print("None found!")
else:
    for r in rows:
        print(r)

# Check how row codes and col codes look
cur.execute("SELECT DISTINCT template_code FROM p3dh_data_dictionary WHERE template_name LIKE '%IRRBB%' OR template_name LIKE '%Interest rate risk%'")
print("\nIRRBB template_codes in dict by name lookup:")
print(cur.fetchall())

conn.close()
