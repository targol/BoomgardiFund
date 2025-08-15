import sqlite3
from datetime import datetime
import os
from flask import Flask, request, render_template, redirect, url_for, session, flash, get_flashed_messages
import secrets
from jdatetime import date as jdate

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
        c.execute("SELECT * FROM members ORDER BY join_date ASC")
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

def get_all_transactions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT t.id, m.name, t.date, t.amount, t.type, t.description FROM transactions t JOIN members m ON t.member_id = m.id ORDER BY t.date ASC")
    rows = c.fetchall()
    conn.close()
    return rows

# تبدیل تاریخ میلادی به شمسی
def gregorian_to_shamsi(date_str):
    if date_str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        jd = jdate.fromgregorian(date=dt)
        return jd.strftime("%Y-%m-%d")
    return ""

# تبدیل اعداد به فرمت هزارتایی
def format_number(number):
    return "{:,.0f}".format(number).replace(",", ".")

# اپ Flask
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = secrets.token_hex(16)
app.jinja_env.filters['format_number'] = format_number

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
    return render_template('login.html')

@app.route('/status')
def status():
    if session.get('role') != 'member':
        return redirect(url_for('login'))
    member = Member.load_by_name(session['username'])
    if member:
        current_date = datetime.now().strftime("%Y-%m-%d")
        points = member.calculate_points(current_date)
        fund_balance = sum(m.current_balance for m in Member.load_all())
        return render_template('status.html', name=member.name, balance=format_number(member.current_balance), points=format_number(points), fund_balance=format_number(fund_balance))
    return "عضو یافت نشد!"

@app.route('/admin')
def admin_panel():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    members = Member.load_all()
    return render_template('admin.html', members=members)

@app.route('/admin/add_member', methods=['POST'])
def admin_add_member():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    name = request.form['name']
    join_date_shamsi = request.form['join_date']
    try:
        join_date_gregorian = shamsi_to_gregorian(join_date_shamsi)
        if add_member(name, join_date_gregorian):
            flash('عضو اضافه شد!', 'message')
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
        flash('تراکنش ثبت شد!', 'message')
    except ValueError:
        flash('تاریخ شمسی نامعتبر!', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/transactions')
def transactions():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    transactions = get_all_transactions()
    # محاسبه جمع کل سرمایه اولیه و عضویت‌های ماهانه
    initial_total = sum(t[3] for t in transactions if t[4] == 'initial')
    membership_total = sum(t[3] for t in transactions if t[4] == 'membership')
    total = initial_total + membership_total
    return render_template('transactions.html', transactions=transactions, initial_total=initial_total, membership_total=membership_total, total=total)

@app.route('/members')
def members():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    members = Member.load_all()
    return render_template('members.html', members=members)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
