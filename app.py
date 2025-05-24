from flask import Flask, request, jsonify, session, render_template, redirect, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
import os
import mysql.connector.pooling

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('JWT_SECRET')
CORS(app, supports_credentials=True)

# Setup MySQL connection pool
dbconfig = {
    "host": os.environ.get('MYSQLHOST'),
    "user": os.environ.get('MYSQLUSER'),
    "password": os.environ.get('MYSQLPASSWORD'),
    "database": os.environ.get('MYSQLDATABASE'),
    "port": int(os.environ.get('MYSQLPORT', 3306))
}

connection_pool = mysql.connector.pooling.MySQLConnectionPool(pool_name="mypool", pool_size=5, **dbconfig)

def get_connection():
    return connection_pool.get_connection()

# Root route
@app.route('/')
def index():
    return render_template('login.html')

# Login route
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"error": "Username dan password harus diisi."}), 400

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT username, password, role FROM user WHERE username = %s LIMIT 1", (username,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['username'] = user['username']
            session['role'] = user['role']
            return jsonify({"message": "Login berhasil", "role": user['role']}), 200
        else:
            return jsonify({"error": "Username atau password salah"}), 401

    except Exception as e:
        return jsonify({"error": f"Terjadi kesalahan saat login: {str(e)}"}), 500

# Home route
@app.route('/home')
def home():
    if 'username' in session:
        return f"Selamat datang, {session['username']}! Anda login sebagai {session['role']}."
    return redirect(url_for('index'))

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# Jalankan aplikasi
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)  # Matikan debug untuk performa
