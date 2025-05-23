from flask import Flask, render_template, request, redirect, session, send_file
import mysql.connector
import pandas as pd
import io
import os
import urllib.parse
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ['SECRET_KEY']

def get_connection():
    # Force use of Railway's database URL (no fallback to localhost)
    db_url = os.getenv('DATABASE_URL') or os.getenv('MYSQL_URL')
    
    if not db_url:
        raise ValueError("No database connection URL found in environment variables")
        
    try:
        # Parse the database URL
        parsed = urllib.parse.urlparse(db_url)
        conn = mysql.connector.connect(
            host=parsed.hostname,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:],  # Remove leading slash
            port=parsed.port or 3306
        )
        print("✅ Successfully connected to Railway MySQL")
        return conn
    except Exception as e:
        print(f"❌ Database connection failed to {parsed.hostname}: {str(e)}")
        raise

@app.route('/debug-env')
def debug_env():
    """Route to check environment variables (remove in production)"""
    return {
        'MYSQL_URL': bool(os.getenv('MYSQL_URL')),
        'MYSQLHOST': os.getenv('MYSQLHOST'),
        'MYSQLUSER': os.getenv('MYSQLUSER'),
        'MYSQLDATABASE': os.getenv('MYSQLDATABASE'),
        'PORT': os.getenv('PORT')
    }

@app.route('/init-db')
def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user'
            )
        """)
        conn.commit()
        return "Tabel berhasil dibuat!"
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            conn = get_connection()
            c = conn.cursor(dictionary=True)
            
            c.execute("SELECT username, password, role FROM user WHERE username = %s", (username,))
            user = c.fetchone()
            conn.close()

            if user and check_password_hash(user['password'], password):
                session['username'] = user['username']
                session['role'] = user['role']
                return redirect('/')
            return render_template('login.html', error="Invalid credentials")
                
        except Exception as e:
            print(f"Login error: {str(e)}")
            return render_template('login.html', error="Database error occurred")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect('/login')

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' not in session:
        return redirect('/login')
    
    print('ROLE SAAT INI:', session.get('role'))

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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)