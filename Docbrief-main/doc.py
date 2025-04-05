def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            upload_date TIMESTAMP NOT NULL,
            summary TEXT,
            important_clauses TEXT,
            language TEXT DEFAULT 'English'
        )
    ''')
    conn.commit()
    conn.close()