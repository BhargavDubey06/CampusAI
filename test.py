
import sqlite3
import os

DB_NAME = "campusai.db"

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

try:
    # Get uploaded PDF filenames
    cursor.execute("SELECT stored_name FROM documents")
    files = cursor.fetchall()

    # Delete related chunks
    cursor.execute("""
        DELETE FROM chunks
        WHERE document_id IN (
            SELECT id FROM documents
        )
    """)

    # Delete document records
    cursor.execute("DELETE FROM documents")

    conn.commit()

    print("All document records and chunks deleted.")

    # Remove physical PDF files
    for file in files:
        filename = file[0]

        for folder in ["uploads", "static/uploads", "media"]:
            filepath = os.path.join(folder, filename)

            if os.path.isfile(filepath):
                os.remove(filepath)
                print("Deleted file:", filepath)
                break

    print("PDF cleanup completed successfully!")

except Exception as e:
    conn.rollback()
    print("Error:", e)

finally:
    conn.close()
