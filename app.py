from flask import Flask, render_template, request, redirect, session, send_file
import mysql.connector
import pandas as pd
import io
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'gudang_secret_key')

def get_connection():
    print("Trying to connect to database...")
    
    # Debug: Print available environment variables
    print(f"MYSQLHOST: {os.environ.get('mysql.railway.internal')}")
    print(f"MYSQLPORT: {os.environ.get('3306')}")
    print(f"MYSQLUSER: {os.environ.get('root')}")
    print(f"MYSQLDATABASE: {os.environ.get('railway')}")
    
    # Check if Railway MySQL variables exist
    if os.environ.get('MYSQLHOST'):
        return mysql.connector.connect(
            host=os.environ.get('mysql.railway.internal'),
            port=int(os.environ.get('3306', '3306')),
            user=os.environ.get('root'),
            password=os.environ.get('QALkfRgKFSekNYqRixIeDTxxcVgUdKut'),
            database=os.environ.get('railway')
        )
    
    # Fallback to old format or local development
    else:
        print("Railway MySQL variables not found, trying fallback...")
        return mysql.connector.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=int(os.environ.get('DB_PORT', '3306')),
            user=os.environ.get('DB_USER', 'root'),
            password=os.environ.get('DB_PASSWORD', ''),
            database=os.environ.get('DB_NAME', 'railway')
        )

def init_database():
    """Initialize database tables if they don't exist"""
    conn = None
    cursor = None
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create user table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                status VARCHAR(20) DEFAULT 'tersedia',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert default users
        cursor.execute("""
            INSERT IGNORE INTO user (username, password, role) VALUES 
            ('admin', 'admin123', 'admin'),
            ('user', 'user123', 'user')
        """)
        
        conn.commit()
        print("✅ Database initialized successfully!")
        
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        print("Skipping database initialization - will try again on first request")
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT username, role FROM user WHERE username=%s AND password=%s", (username, password))
            user = c.fetchone()
            conn.close()

            if user:
                session['username'] = user[0]
                session['role'] = user[1]
                return redirect('/')
            else:
                return render_template('login.html', error="Username atau password salah.")
        except Exception as e:
            return f"Database error: {e}"
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect('/login')

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' not in session:
        return redirect('/login')

    conn = get_connection()
    c = conn.cursor()
    error = None

    if request.method == 'POST' and session.get('role') != 'admin':
        error = "Role Anda tidak diizinkan untuk input data."
    elif request.method == 'POST':
        tanggal = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        barang = request.form['barang']
        jumlah = int(request.form['jumlah'])
        tipe = request.form['tipe']

        if tipe == 'masuk':
            gudang = int(request.form['gudang'])
            c.execute('''INSERT INTO transaksi (tanggal, barang, jumlah, tipe, gudang, status)
                         VALUES (%s, %s, %s, %s, %s, %s)''',
                      (tanggal, barang, jumlah, tipe, gudang, 'tersedia'))
        else:
            sisa = jumlah
            c.execute('''SELECT * FROM transaksi 
                         WHERE barang=%s AND tipe='masuk' AND status='tersedia'
                         ORDER BY tanggal ASC''', (barang,))
            stok_tersedia = c.fetchall()
            for stok in stok_tersedia:
                id_trans, _, _, jumlah_stok, _, gudang_stok, _ = stok
                if jumlah_stok <= sisa:
                    c.execute("UPDATE transaksi SET status='keluar' WHERE id=%s", (id_trans,))
                    c.execute('''INSERT INTO transaksi (tanggal, barang, jumlah, tipe, gudang, status)
                                 VALUES (%s, %s, %s, %s, %s, %s)''',
                              (tanggal, barang, jumlah_stok, 'keluar', gudang_stok, 'keluar'))
                    sisa -= jumlah_stok
                else:
                    c.execute("UPDATE transaksi SET jumlah=%s WHERE id=%s", (jumlah_stok - sisa, id_trans))
                    c.execute('''INSERT INTO transaksi (tanggal, barang, jumlah, tipe, gudang, status)
                                 VALUES (%s, %s, %s, %s, %s, %s)''',
                              (tanggal, barang, sisa, 'keluar', gudang_stok, 'keluar'))
                    sisa = 0
                if sisa == 0:
                    break
            if sisa > 0:
                c.execute("SELECT * FROM transaksi ORDER BY id DESC")
                data = c.fetchall()
                conn.close()
                return render_template('index.html', data=data, error=f"Stok tidak mencukupi untuk barang: {barang}")

        conn.commit()
        conn.close()
        return redirect('/')

    c.execute("SELECT * FROM transaksi ORDER BY id DESC")
    data = c.fetchall()
    conn.close()
    return render_template('index.html', data=data, error=error)

@app.route('/cari', methods=['GET', 'POST'])
def cari():
    if 'username' not in session:
        return redirect('/login')

    hasil = []
    barang = ""
    if request.method == 'POST':
        barang = request.form['barang']
        conn = get_connection()
        c = conn.cursor()
        c.execute('''SELECT gudang, jumlah, tanggal FROM transaksi
                     WHERE barang=%s AND tipe='masuk' AND status='tersedia'
                     ORDER BY tanggal ASC''', (barang,))
        hasil = c.fetchall()
        conn.close()
    return render_template('cari.html', hasil=hasil, barang=barang)

@app.route('/export')
def export_excel():
    if 'username' not in session:
        return redirect('/login')

    conn = get_connection()
    df = pd.read_sql("SELECT * FROM transaksi ORDER BY id DESC", conn)
    conn.close()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Riwayat')

    output.seek(0)
    return send_file(output, download_name='riwayat_gudang.xlsx', as_attachment=True)

@app.route('/gudang/<nama_gudang>')
def lihat_gudang(nama_gudang):
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        SELECT barang, 
               SUM(CASE WHEN tipe = 'masuk' THEN jumlah ELSE 0 END) -
               SUM(CASE WHEN tipe = 'keluar' THEN jumlah ELSE 0 END) AS stok
        FROM transaksi
        WHERE gudang = %s
        GROUP BY barang
        HAVING stok > 0
    ''', (nama_gudang,))

    barang_list = c.fetchall()
    conn.close()
    return render_template('gudang.html', gudang=nama_gudang, barang_list=barang_list)

if __name__ == '__main__':
    # Initialize database on startup
    init_database()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)