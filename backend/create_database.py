
import sqlite3
from backend.config import Config
from backend.database import init_db

def create_database():
    print("Creating CampusAI database...")

    # Create all tables using your existing database schema
    init_db()

    # Display database location
    db_path = Config.DATABASE_PATH
    print("\nDatabase created successfully!")
    print("Database location:", db_path)

    # Verify all tables
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)

    tables = cursor.fetchall()

    print("\nTables created:")

    for (table_name,) in tables:
        print(f"\n{table_name.upper()}")

        cursor.execute(f"PRAGMA table_info({table_name})")

        for column in cursor.fetchall():
            print("  -", column[1])

    conn.close()

    print("\nCampusAI database setup completed!")


if __name__ == "__main__":
    create_database()
