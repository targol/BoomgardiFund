import sqlite3
from datetime import datetime
import os
from flask import Flask, request, render_template_string, redirect, url_for, session, flash, get_flashed_messages
import secrets
from jdatetime import date as jdate  # برای تبدیل شمسی به میلادی

# تنظیم دیتابیس
DB_FILE = 'fund.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS members
                 (id INTEGER PRIMARY KEY, name TEXT UNIQUE, join_date TEXT, 
                  initial_capital INTEGER DEFAULT 0, current_balance INTEGER DEFAULT 0, points INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY, member_id INTEGER, date TEXT, amount INTEGER, type TEXT, description TEXT)''')
    conn.commit()
    conn.close()

init_db()

class Member:
    def __init__(self, id, name, join_date, initial_capital, current_balance, points):
        self.id = id
        self.name = name
        self.join_date = join_date
        self.initial_capital = initial_capital
        self.current_balance = current_balance
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
        c.execute("UPDATE members SET initial_capital=?, current_balance=?, points=? WHERE id=?", 
                  (self.initial_capital, self.current_balance, self.points, self.id))
        conn.commit()
        conn.close()

    def calculate_points(self, current_date_str):
        current_date = datetime.strptime(current_date_str, "%Y-%m-%d")
        days_passed = (current_date - datetime.strptime(self.join_date, "%Y-%m-%d")).days
        daily_points = self.current_balance // 50000
        self.points = daily_points * days_passed
        self.save()
        return self.points

def add_member(name, join_date_gregorian):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO members (name, join_date) VALUES (?, ?)",
                  (name, join_date_gregorian))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def add_transaction(member_id, date_gregorian, amount, trans_type, description):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO transactions (member_id, date, amount, type, description) VALUES (?, ?, ?, ?, ?)",
              (member_id, date_gregorian, amount, trans_type, description))
    conn.commit()
    conn.close()

def update_balance(member_id, amount, trans_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if trans_type == 'initial':
        c.execute("UPDATE members SET initial_capital = initial_capital + ?, current_balance = current_balance + ? WHERE id=?", (amount, amount, member_id))
    elif trans_type == 'membership':
        c.execute("UPDATE members SET current_balance = current_balance + ? WHERE id=?", (amount, member_id))
    elif trans_type == 'installment':
        c.execute("UPDATE members SET current_balance = current_balance - ? WHERE id=?", (amount, member_id))
    conn.commit()
    conn.close()

# تبدیل تاریخ شمسی به میلادی
def shamsi_to_gregorian(shamsi_date):
    year, month, day = map(int, shamsi_date.split('-'))
    jd = jdate(year, month, day)
    return jd.togregorian().strftime("%Y-%m-%d")

# اپ Flask
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# تمپلیت‌ها با استایل جدید
BASE_HTML = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/persian-datepicker@1.2.0/dist/css/persian-datepicker.min.css">
    <script src="https://cdn.jsdelivr.net/npm/jquery@3.6.0/dist/jquery.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/persian-datepicker@1.2.0/dist/js/persian-datepicker.min.js"></script>
    <style>
        body { font-family: 'Vazirmatn', sans-serif; font-size: 18px; text-align: center; margin: 0; padding: 0; }
        header { background-color: #f0f0f0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px; background: #fff; }
        footer { background-color: #f0f0f0; padding: 10px; position: fixed; bottom: 0; width: 100%; }
        form { margin-bottom: 20px; }
        .message { color: green; font-weight: bold; }
        .error { color: red; font-weight: bold; }
    </style>
</head>
<body>
    <header>
        <img src="logo.png" alt="لوگو صندوق" width="200">
    </header>
    <div class="container">
        %s
    </div>
    <footer>
        اطلاعات فوتر: تماس با ما - نسخه 1.0
    </footer>
</body>
</html>
'''

LOGIN_HTML = BASE_HTML % '''
<h1>لاگین</h1>
<form method="post">
    نام کاربری: <input type="text" name="username"><br>
    پسورد: <input type="password" name="password"><br>
    <input type="submit" value="ورود">
</form>
'''

STATUS_HTML = BASE_HTML % '''
<h1>وضعیت برای {{ name }}</h1>
<p>موجودی صندوق کلی: {{ fund_balance }} تومان</p>
<p>موجودی شما: {{ balance }} تومان</p>
<p>امتیاز شما: {{ points }}</p>
<a href="/logout">خروج</a>
'''

ADMIN_HTML = '''
{% for message in get_flashed_messages(with_categories=true) %}
    {% if message[0] == 'error' %}
        <p class="error">{{ message[1] }}</p>
    {% else %}
        <p class="message">{{ message[1] }}</p>
    {% endif %}
{% endfor %}
<h1>پنل مدیر</h1>
<h2>ثبت کاربر جدید</h2>
<form action="/admin/add_member" method="post">
    نام: <input type="text" name="name"><br>
    تاریخ عضویت (شمسی): <input type="text" id="join_date" name="join_date"><br>
    <script>
        $(document).ready(function() {
            $("#join_date").persianDatepicker({format: 'YYYY-MM-DD', maxDate: new Date()});
        });
    </script>
    <input type="submit" value="اضافه کن">
</form>

<h2>ثبت تراکنش</h2>
<form action="/admin/add_transaction" method="post">
    انتخاب کاربر: <select name="member_name">
        {% for member in members %}
            <option value="{{ member.name }}">{{ member.name }}</option>
        {% endfor %}
    </select><br>
    نوع تراکنش: <select name="trans_type">
        <option value="initial">سرمایه اولیه</option>
        <option value="membership">عضویت ماهانه</option>
        <option value="installment">قسط وام</option>
    </select><br>
    مبلغ (تومان): <input type="number" name="amount"><br>
    تاریخ (شمسی): <input type="text" id="trans_date" name="date"><br>
    توضیح: <input type="text" name="description"><br>
    <script>
        $(document).ready(function() {
            $("#trans_date").persianDatepicker({format: 'YYYY-MM-DD', maxDate: new Date()});
        });
    </script>
    <input type="submit" value="ثبت">
</form>
<a href="/logout">خروج</a>
'''

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'admin':
            session['role'] = 'admin'
            return redirect(url_for('admin_panel'))
        member = Member.load_by_name(username)
        if member and password == 'user':
            session['role'] = 'member'
            session['username'] = username
            return redirect(url_for('status'))
        flash('لاگین ناموفق!', 'error')
    return render_template_string(LOGIN_HTML)

@app.route('/status')
def status():
    if session.get('role') != 'member':
        return redirect(url_for('login'))
    member = Member.load_by_name(session['username'])
    if member:
        current_date = datetime.now().strftime("%Y-%m-%d")
        points = member.calculate_points(current_date)
        fund_balance = sum(m.current_balance for m in Member.load_all())
        return render_template_string(STATUS_HTML, name=member.name, balance=member.current_balance, points=points, fund_balance=fund_balance)
    return "عضو یافت نشد!"

@app.route('/admin')
def admin_panel():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    members = Member.load_all()
    return render_template_string(BASE_HTML % ADMIN_HTML, members=members)

@app.route('/admin/add_member', methods=['POST'])
def admin_add_member():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    name = request.form['name']
    join_date_shamsi = request.form['join_date']
    try:
        join_date_gregorian = shamsi_to_gregorian(join_date_shamsi)
        if add_member(name, join_date_gregorian):
            flash('عضو اضافه شد!')
        else:
            flash('نام تکراری است!', 'error')
    except ValueError:
        flash('تاریخ شمسی نامعتبر!', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_transaction', methods=['POST'])
def admin_add_transaction():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    member_name = request.form['member_name']
    member = Member.load_by_name(member_name)
    if not member:
        flash('عضو یافت نشد!', 'error')
        return redirect(url_for('admin_panel'))
    trans_type = request.form['trans_type']
    try:
        amount = int(request.form['amount'])
    except ValueError:
        flash('مبلغ نامعتبر!', 'error')
        return redirect(url_for('admin_panel'))
    date_shamsi = request.form['date']
    description = request.form['description']

    # اعتبارسنجی مبلغ
    if trans_type == 'initial':
        if amount < 5000000 or amount % 5000000 != 0:
            flash('سرمایه اولیه باید حداقل ۵ میلیون و مضرب ۵ میلیون باشد!', 'error')
            return redirect(url_for('admin_panel'))
    elif trans_type == 'membership':
        if amount % 250000 != 0:
            flash('عضویت ماهانه باید مضرب ۲۵۰ هزار تومان باشد!', 'error')
            return redirect(url_for('admin_panel'))

    try:
        date_gregorian = shamsi_to_gregorian(date_shamsi)
        add_transaction(member.id, date_gregorian, amount, trans_type, description)
        update_balance(member.id, amount, trans_type)
        flash('تراکنش ثبت شد!')
    except ValueError:
        flash('تاریخ شمسی نامعتبر!', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
