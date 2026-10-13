import os
import sqlite3
import shutil
from datetime import datetime

database = os.path.join("instance", "shop.db")

if not os.path.exists(database):
    print("ERROR: Database not found:", database)
    raise SystemExit(1)

backup = database + "." + datetime.now().strftime("%Y%m%d_%H%M%S") + ".bak"
shutil.copy2(database, backup)
print("Database backup created:", backup)

connection = sqlite3.connect(database)

try:
    columns = [
        row[1]
        for row in connection.execute(
            'PRAGMA table_info("order")'
        ).fetchall()
    ]

    print("Current order columns:", columns)

    if not columns:
        print("ERROR: The order table was not found.")
    elif "items" in columns:
        print("SUCCESS: The items column already exists.")
    else:
        connection.execute(
            'ALTER TABLE "order" ADD COLUMN items TEXT NOT NULL DEFAULT "{}"'
        )
        connection.commit()
        print("SUCCESS: Added the items column.")

    updated_columns = [
        row[1]
        for row in connection.execute(
            'PRAGMA table_info("order")'
        ).fetchall()
    ]

    print("Updated order columns:", updated_columns)

finally:
    connection.close()
