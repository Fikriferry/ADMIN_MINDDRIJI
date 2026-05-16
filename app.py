import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from dotenv import load_dotenv
from supabase import create_client, Client

# ── Load environment variables ──────────────────────
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback-secret-key')

# ── Supabase client ──────────────────────────────────
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Data dummy (pengguna, notifikasi, artikel tetap dummy) ──
PENGGUNA = [
    {"id": 1,  "nama": "Andi Pratama",     "email": "andi@email.com",   "status": "Aktif",    "role": "Pasien",  "bergabung": "12 Jan 2024", "avatar": "A"},
    {"id": 2,  "nama": "Sari Dewi",        "email": "sari@email.com",   "status": "Aktif",    "role": "Pasien",  "bergabung": "18 Jan 2024", "avatar": "S"},
    {"id": 3,  "nama": "dr. Budi Santoso", "email": "budi@email.com",   "status": "Aktif",    "role": "Dokter",  "bergabung": "05 Feb 2024", "avatar": "B"},
    {"id": 4,  "nama": "Rina Kusuma",      "email": "rina@email.com",   "status": "Nonaktif", "role": "Pasien",  "bergabung": "20 Feb 2024", "avatar": "R"},
    {"id": 5,  "nama": "dr. Hendra W.",    "email": "hendra@email.com", "status": "Aktif",    "role": "Dokter",  "bergabung": "03 Mar 2024", "avatar": "H"},
    {"id": 6,  "nama": "Mega Putri",       "email": "mega@email.com",   "status": "Aktif",    "role": "Pasien",  "bergabung": "14 Mar 2024", "avatar": "M"},
    {"id": 7,  "nama": "Fajar Rahman",     "email": "fajar@email.com",  "status": "Pending",  "role": "Pasien",  "bergabung": "28 Mar 2024", "avatar": "F"},
    {"id": 8,  "nama": "Admin Sistem",     "email": "admin@email.com",  "status": "Aktif",    "role": "Admin",   "bergabung": "01 Jan 2024", "avatar": "A"},
]

NOTIFIKASI = [
    {"id": 1, "judul": "Pengguna baru terdaftar",      "isi": "Fajar Rahman baru saja mendaftar dan menunggu verifikasi akun.",     "waktu": "2 menit lalu",   "tipe": "info",    "dibaca": False},
    {"id": 2, "judul": "AI Insight selesai diproses",  "isi": "Laporan insight kesehatan mental untuk 45 pengguna telah selesai.",  "waktu": "15 menit lalu",  "tipe": "success", "dibaca": False},
    {"id": 3, "judul": "Peringatan penggunaan sistem", "isi": "Penggunaan memori server mencapai 78%. Pertimbangkan optimasi.",     "waktu": "1 jam lalu",     "tipe": "warning", "dibaca": False},
    {"id": 4, "judul": "Artikel baru dipublikasi",     "isi": "Artikel 'Mengelola Stres di Era Digital' telah dipublikasi.",        "waktu": "3 jam lalu",     "tipe": "info",    "dibaca": True},
    {"id": 5, "judul": "Pembaruan keamanan berhasil",  "isi": "Patch keamanan v2.3.1 berhasil diterapkan tanpa downtime.",          "waktu": "Kemarin, 22:04", "tipe": "success", "dibaca": True},
    {"id": 6, "judul": "Laporan mingguan siap",        "isi": "Ringkasan aktivitas platform minggu ini telah tersedia.",            "waktu": "2 hari lalu",    "tipe": "info",    "dibaca": True},
]

ARTIKEL = [
    {"id": 1, "judul": "Mengelola Stres di Era Digital",      "kategori": "Kesehatan Mental", "penulis": "dr. Budi Santoso", "tanggal": "14 Mei 2024", "status": "Publikasi", "views": 1240},
    {"id": 2, "judul": "Mindfulness untuk Produktivitas",     "kategori": "Mindfulness",      "penulis": "dr. Hendra W.",    "tanggal": "10 Mei 2024", "status": "Publikasi", "views": 876},
    {"id": 3, "judul": "Tanda-tanda Burnout dan Cara Atasi",  "kategori": "Kesehatan Mental", "penulis": "Admin Sistem",     "tanggal": "07 Mei 2024", "status": "Draft",     "views": 0},
    {"id": 4, "judul": "Peran AI dalam Kesehatan Mental",     "kategori": "Teknologi AI",     "penulis": "Admin Sistem",     "tanggal": "03 Mei 2024", "status": "Publikasi", "views": 2105},
    {"id": 5, "judul": "Teknik Pernapasan untuk Relaksasi",   "kategori": "Mindfulness",      "penulis": "dr. Budi Santoso", "tanggal": "28 Apr 2024", "status": "Review",    "views": 0},
    {"id": 6, "judul": "Hubungan Tidur dan Kesehatan Mental", "kategori": "Gaya Hidup",       "penulis": "dr. Hendra W.",    "tanggal": "22 Apr 2024", "status": "Publikasi", "views": 654},
]


# ════════════════════════════════════════════════════
#  AUTH HELPER
# ════════════════════════════════════════════════════

def login_required(f):
    """Decorator: redirect ke login jika belum ada sesi."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_email' not in session:
            flash('Silakan login terlebih dahulu.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def do_supabase_login(email: str, password: str) -> dict:
    """
    Login via Supabase Auth (sign_in_with_password).
    Return: {'ok': True, 'user': {...}} atau {'ok': False, 'error': '...'}
    """
    try:
        resp = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        user = resp.user
        if user is None:
            return {'ok': False, 'error': 'Email atau password salah.'}

        # Coba ambil data profil dari tabel admin_users (opsional)
        nama   = email.split('@')[0].title()
        role   = 'Admin'
        avatar = nama[0].upper()

        try:
            profil = (
                supabase.table('admin_users')
                .select('nama, role, avatar')
                .eq('email', email)
                .single()
                .execute()
            )
            if profil.data:
                nama   = profil.data.get('nama',   nama)
                role   = profil.data.get('role',   role)
                avatar = profil.data.get('avatar', avatar)
        except Exception:
            pass  # tabel admin_users belum ada → pakai default

        return {
            'ok':     True,
            'email':  email,
            'nama':   nama,
            'role':   role,
            'avatar': avatar,
            'uid':    str(user.id),
        }

    except Exception as e:
        msg = str(e)
        # Terjemahkan pesan error Supabase → Bahasa Indonesia
        if 'Invalid login credentials' in msg or 'invalid_credentials' in msg:
            return {'ok': False, 'error': 'Email atau password salah.'}
        if 'Email not confirmed' in msg:
            return {'ok': False, 'error': 'Email belum dikonfirmasi. Cek inbox Anda.'}
        if 'User not found' in msg:
            return {'ok': False, 'error': 'Akun tidak ditemukan.'}
        if 'too many requests' in msg.lower() or 'rate limit' in msg.lower():
            return {'ok': False, 'error': 'Terlalu banyak percobaan. Tunggu beberapa menit.'}
        # Error tak terduga → tampilkan pesan generik
        return {'ok': False, 'error': 'Terjadi kesalahan. Silakan coba lagi.'}


# ════════════════════════════════════════════════════
#  AUTH ROUTES
# ════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'admin_email' in session:
        return redirect(url_for('dashboard'))

    error = None
    prefill_email = ''

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        prefill_email = email

        if not email or not password:
            error = 'Email dan password wajib diisi.'
        else:
            result = do_supabase_login(email, password)
            if result['ok']:
                session.permanent = bool(remember)
                session['admin_email']  = result['email']
                session['admin_nama']   = result['nama']
                session['admin_role']   = result['role']
                session['admin_avatar'] = result['avatar']
                session['admin_uid']    = result['uid']
                flash(f"Selamat datang, {result['nama']}! 👋", 'success')
                return redirect(url_for('dashboard'))
            else:
                error = result['error']

    return render_template('login.html', error=error, prefill_email=prefill_email)


@app.route('/logout')
@login_required
def logout():
    nama = session.get('admin_nama', 'Admin')
    try:
        supabase.auth.sign_out()
    except Exception:
        pass  # tetap lanjut logout lokal
    session.clear()
    flash(f'Sampai jumpa, {nama}! Anda telah berhasil logout.', 'info')
    return redirect(url_for('login'))


# ════════════════════════════════════════════════════
#  PROTECTED ROUTES
# ════════════════════════════════════════════════════

@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', active_page='dashboard')

@app.route('/pengguna')
@login_required
def pengguna():
    return render_template('pengguna.html', pengguna=PENGGUNA, active_page='pengguna')

@app.route('/monitoring')
@login_required
def monitoring():
    return render_template('monitoring.html', active_page='monitoring')

@app.route('/insight')
@login_required
def insight():
    return render_template('insight.html', active_page='insight')

@app.route('/notifikasi')
@login_required
def notifikasi():
    unread = sum(1 for n in NOTIFIKASI if not n['dibaca'])
    return render_template('notifikasi.html', notifikasi=NOTIFIKASI,
                           unread=unread, active_page='notifikasi')

@app.route('/artikel')
@login_required
def artikel():
    return render_template('artikel.html', artikel=ARTIKEL, active_page='artikel')


if __name__ == '__main__':
    app.run(debug=True)