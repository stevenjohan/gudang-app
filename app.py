from flask import Flask, render_template, request, redirect, session, send_file
import mysql.connector
import pandas as pd
import io
from datetime import datetime
import os
from dotenv import load_dotenv  # Add this import

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'gudang_secret_key')  # Use environment variable for secret key

def get_connection():
    return mysql.connector.connect(
        host=os.getenv('MYSQLHOST'),  # Jangan hardcode!
        user=os.getenv('MYSQLUSER'),
        password=os.getenv('MYSQLPASSWORD'),
        database=os.getenv('MYSQLDATABASE'),
        port=int(os.getenv('MYSQLPORT', '3306'))
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

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
    port = int(os.getenv('PORT', 5000))  # Gunakan PORT dari Railway
    app.run(host='0.0.0.0', port=port)