import os
import mysql.connector
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv('MYSQLHOST'),  # Pastikan ini sesuai dengan Railway Variables
            user=os.getenv('MYSQLUSER'),
            password=os.getenv('MYSQLPASSWORD'),
            database=os.getenv('MYSQLDATABASE', 'railway'),
            port=int(os.getenv('MYSQLPORT', 3306))
        )
    except Exception as e:
        print(f"❌ Failed to connect to database: {str(e)}")
        print("Please check your Railway Variables:")
        print(f"- MYSQLHOST: {os.getenv('MYSQLHOST')}")
        print(f"- MYSQLUSER: {os.getenv('MYSQLUSER')}")
        print(f"- MYSQLDATABASE: {os.getenv('MYSQLDATABASE')}")
        return None

def initialize_database():
    conn = None
    try:
        conn = get_connection()
        if conn is None:
            return
            
        cursor = conn.cursor()
        
        # Create user table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user'
            )
        """)
        
        # Create transaksi table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaksi (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tanggal DATETIME NOT NULL,
                barang VARCHAR(100) NOT NULL,
                jumlah INT NOT NULL,
                tipe ENUM('masuk', 'keluar') NOT NULL,
                gudang INT NOT NULL,
                status VARCHAR(20) NOT NULL
            )
        """)
        
        # Insert default admin user
        cursor.execute("""
            INSERT IGNORE INTO user (username, password, role)
            VALUES (%s, %s, %s)
        """, (
            'admin',
            '$2b$12$WU8UfJoJwN5p0bBzQhLJQOcJ9XZ9xkT7r9VlDd6hL0aNf2sKjQWYm', # password: admin123
            'admin'
        ))
        
        conn.commit()
        print("✅ Database initialized successfully!")
        
    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    initialize_database()