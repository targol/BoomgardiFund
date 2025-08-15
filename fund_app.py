import sqlite3
from datetime import datetime
from flask import Flask, request, render_template_string, redirect, url_for, session
import secrets

# تنظیم دیتابیس
DB_FILE = 'fund.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS members
                 (id INTEGER PRIMARY KEY, name TEXT UNIQUE, initial_capital INTEGER, start_date TEXT, 
                  current_balance INTEGER, points INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY, member_id INTEGER, date TEXT, amount INTEGER, description TEXT)''')
    conn.commit()
    conn.close()

init_db()

class Member:
    def __init__(self, id, name, initial_capital, start_date, current_balance, points):
        self.id = id
        self.name = name
        self.initial_capital = initial_capital
        self.current_balance = current_balance
        self.membership_fee = initial_capital // 20
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d")
        self.points = points

    @classmethod
    def load_by_name(cls, name):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM members WHERE name=?", (name,))
        row = c.fetchone()
        conn.close()
        if row:
            return cls(*row)
        return None

    @classmethod
    def load_all(cls):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM members")
        rows = c.fetchall()
        conn.close()
        return [cls(*row) for row in rows]

    def save(self):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE members SET current_balance=?, points=? WHERE id=?", 
                  (self.current_balance, self.points, self.id))
        conn.commit()
        conn.close()

    def calculate_points(self, current_date_str):
        current_date = datetime.strptime(current_date_str, "%Y-%m-%d")
        days_passed = (current_date - self.start_date).days
        daily_points = self.current_balance // 50000
        self.points = daily_points * days_passed
        self.save()
        return self.points

def add_member(name, initial_capital, start_date):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        current_balance = initial_capital
        points = 0
        c.execute("INSERT INTO members (name, initial_capital, start_date, current_balance, points) VALUES (?, ?, ?, ?, ?)",
                  (name, initial_capital, start_date, current_balance, points))
        member_id = c.lastrowid
        conn.commit()
        return member_id
    except sqlite3.IntegrityError:
        return None  # نام تکراری
    finally:
        conn.close()

def update_balance(member_id, date, amount, description):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE members SET current_balance = current_balance + ? WHERE id=?", (amount, member_id))
    c.execute("INSERT INTO transactions (member_id, date, amount, description) VALUES (?, ?, ?, ?)",
              (member_id, date, amount, description))
    conn.commit()
    conn.close()

def get_fund_balance():
    members = Member.load_all()
    return sum(m.current_balance for m in members)

# اپ Flask
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # برای سشن‌ها

# تمپلیت‌های HTML ساده
LOGIN_HTML = '''
<h1>لاگین</h1>
<form method="post">
    نام کاربری: <input type="text" name="username"><br>
    پسورد: <input type="password" name="password"><br>
    <input type="submit" value="ورود">
</form>
'''

STATUS_HTML = '''
<h1>وضعیت برای {{ name }}</h1>
<p>موجودی صندوق کلی: {{ fund_balance }} تومان</p>
<p>موجودی شما: {{ balance }} تومان</p>
<p>امتیاز شما: {{ points }}</p>
<a href="/logout">خروج</a>
'''

ADMIN_HTML = '''
<h1>پنل مدیر</h1>
<h2>ثبت مبلغ برای عضو</h2>
<form action="/admin/update" method="post">
    نام عضو: <input type="text" name="member_name"><br>
    تاریخ (YYYY-MM-DD): <input type="text" name="date"><br>
    مبلغ (مثبت برای افزایش، منفی برای کاهش): <input type="number" name="amount"><br>
    توضیح: <input type="text" name="description"><br>
    <input type="submit" value="ثبت">
</form>
<h2>اضافه کردن عضو جدید</h2>
<form action="/admin/add_member" method="post">
    نام: <input type="text" name="name"><br>
    سرمایه اولیه: <input type="number" name="initial_capital"><br>
    تاریخ شروع (YYYY-MM-DD): <input type="text" name="start_date"><br>
    <input type="submit" value="اضافه کن">
</form>
<a href="/logout">خروج</a>
'''

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # لاگین ساده: اگر username == 'admin' و password == 'admin'، مدیره
        if username == 'admin' and password == 'admin':
            session['role'] = 'admin'
            return redirect(url_for('admin_panel'))
        #otherwise، چک کن آیا عضو هست
        member = Member.load_by_name(username)
        if member and password == 'user':  # پسورد ساده برای اعضا
            session['role'] = 'member'
            session['username'] = username
            return redirect(url_for('status'))
        return "لاگین ناموفق!"
    return LOGIN_HTML

@app.route('/status')
def status():
    if session.get('role') != 'member':
        return redirect(url_for('login'))
    member = Member.load_by_name(session['username'])
    if member:
        current_date = datetime.now().strftime("%Y-%m-%d")
        points = member.calculate_points(current_date)
        fund_balance = get_fund_balance()
        return render_template_string(STATUS_HTML, name=member.name, balance=member.current_balance, points=points, fund_balance=fund_balance)
    return "عضو یافت نشد!"

@app.route('/admin')
def admin_panel():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return ADMIN_HTML

@app.route('/admin/update', methods=['POST'])
def admin_update():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    member_name = request.form['member_name']
    member = Member.load_by_name(member_name)
    if member:
        date = request.form['date']
        amount = int(request.form['amount'])
        description = request.form['description']
        update_balance(member.id, date, amount, description)
        return "ثبت موفق!"
    return "عضو یافت نشد!"

@app.route('/admin/add_member', methods=['POST'])
def admin_add_member():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    name = request.form['name']
    initial_capital = int(request.form['initial_capital'])
    start_date = request.form['start_date']
    if add_member(name, initial_capital, start_date):
        return "عضو اضافه شد!"
    return "نام تکراری است!"

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    # مثال: اگر دیتابیس خالی باشه، یک عضو اضافه کن
    if len(Member.load_all()) == 0:
        add_member("علی", 1000000, "2025-01-01")
    import os
port = int(os.environ.get("PORT", 5000))  # پورت رو از محیط می‌گیره، پیش‌فرض 5000
app.run(host='0.0.0.0', port=port, debug=True)
