import json
import sqlite3
import sys
conn = sqlite3.connect('local_data/user_data/data/documents/a3c9e1f7b284/doc.db')
cursor = conn.cursor()
cursor.execute('SELECT start_page, end_page, title FROM fnm_chapters ORDER BY start_page')
print(cursor.fetchall())
