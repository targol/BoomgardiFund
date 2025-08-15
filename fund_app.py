import sqlite3
from datetime import datetime, timedelta
import os
from flask import Flask, request, render_template, redirect, url_for, session, flash, get_flashed_messages
import secrets
from jdatetime import date as jdate

# تنظیم دیتابیس
DB_FILE = os.path.join(os.path.dirname(__file__), 'fund.db')

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS members
                     (id INTEGER PRIMARY KEY, name TEXT UNIQUE, join_date TEXT, 
                      initial_capital INTEGER DEFAULT 0, current_balance INTEGER DEFAULT 0, points INTEGER DEFAULT 0, 
                      username TEXT UNIQUE, password TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions
                     (id INTEGER PRIMARY KEY, member_id INTEGER, date TEXT, amount INTEGER, type TEXT, description TEXT, tracking_code INTEGER UNIQUE,
                      FOREIGN KEY (member_id) REFERENCES members(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS daily_balances
                     (id INTEGER PRIMARY KEY, member_id INTEGER, date TEXT, balance INTEGER, daily_points INTEGER, total_points INTEGER,
                      FOREIGN KEY (member_id) REFERENCES members(id), UNIQUE (member_id, date))''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"خطا در ساخت دیتابیس: {e}")
        conn.rollback()
    finally:
        conn.close()

init_db()

class Member:
    def __init__(self, id, name, join_date, initial_capital, current_balance, points, username, password):
        self.id = id
        self.name = name
        self.join_date = join_date
        self.initial_capital = initial_capital
        self.current_balance = current_balance
        self.points = points
        self.username = username
        self.password = password

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
    def load_by_username(cls, username):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM members WHERE username=?", (username,))
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
        c.execute("UPDATE members SET initial_capital=?, current_balance=?, points=?, username=?, password=? WHERE id=?", 
                  (self.initial_capital, self.current_balance, self.points, self.username, self.password, self.id))
        conn.commit()
        conn.close()

    def update_daily_balance(self, date_str):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT SUM(amount) FROM transactions WHERE member_id = ? AND date <= ? AND type IN ('initial', 'membership')",
                  (self.id, date_str))
        total_in = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM transactions WHERE member_id = ? AND date <= ? AND type = 'installment'",
                  (self.id, date_str))
        total_out = c.fetchone()[0] or 0
        balance = total_in - total_out
        daily_points = balance // 50000
        c.execute("SELECT COALESCE(SUM(daily_points), 0) FROM daily_balances WHERE member_id = ? AND date < ?", (self.id, date_str))
        prev_points = c.fetchone()[0]
        total_points = prev_points + daily_points
        try:
            c.execute("INSERT OR REPLACE INTO daily_balances (member_id, date, balance, daily_points, total_points) VALUES (?, ?, ?, ?, ?)",
                      (self.id, date_str, balance, daily_points, total_points))
            conn.commit()
            self.points = total_points
            self.save()
        except sqlite3.Error as e:
            print(f"خطا در آپدیت تاریخچه: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_daily_balances(self):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT MIN(date) FROM transactions WHERE member_id = ?", (self.id,))
        first_transaction_date = c.fetchone()[0]
        start_date = max(datetime.strptime(self.join_date, "%Y-%m-%d"), 
                        datetime.strptime(first_transaction_date or self.join_date, "%Y-%m-%d") if first_transaction_date else datetime.strptime(self.join_date, "%Y-%m-%d"))
        current_date = start_date
        end_date = datetime.now()
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            self.update_daily_balance(date_str)
            current_date += timedelta(days=1)
        c.execute("SELECT date, balance, daily_points, total_points FROM daily_balances WHERE member_id = ? ORDER BY date DESC", (self.id,))
        rows = c.fetchall()
        conn.close()
        return [(gregorian_to_shamsi(row[0]), row[1], row[2], row[3]) for row in rows]

    def calculate_totals(self):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT SUM(amount) FROM transactions WHERE member_id = ? AND type = 'initial'", (self.id,))
        total_initial = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM transactions WHERE member_id = ? AND type = 'membership'", (self.id,))
        total_membership = c.fetchone()[0] or 0
        conn.close()
        return total_initial, total_membership

def add_member(name, join_date_gregorian, username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO members (name, join_date, username, password) VALUES (?, ?, ?, ?)",
                  (name, join_date_gregorian, username, password))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def add_transaction(member_id, date_gregorian, amount, trans_type, description, tracking_code):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO transactions (member_id, date, amount, type, description, tracking_code) VALUES (?, ?, ?, ?, ?, ?)",
                  (member_id, date_gregorian, amount, trans_type, description, tracking_code))
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("کد رهگیری تکراری است!")
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
    c.execute("SELECT t.id, m.name, t.date, t.amount, t.type, t.description, t.tracking_code FROM transactions t JOIN members m ON t.member_id = m.id ORDER BY t.date ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_transactions_by_member(member_name):
    member = Member.load_by_name(member_name)
    if not member:
        return []
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT t.id, t.date, t.amount, t.type, t.description, t.tracking_code FROM transactions t WHERE t.member_id = ? ORDER BY t.date ASC", (member.id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_total_balance():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT SUM(initial_capital) + SUM(current_balance) FROM members")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def shamsi_to_gregorian(shamsi_date):
    year, month, day = map(int, shamsi_date.split('-'))
    jd = jdate(year, month, day)
    return jd.togregorian().strftime("%Y-%m-%d")

def gregorian_to_shamsi(date_str):
    if date_str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        jd = jdate.fromgregorian(date=dt)
        return jd.strftime("%Y-%m-%d")
    return ""

def format_number(number):
    return "{:,.0f}".format(number).replace(",", ".")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = secrets.token_hex(16)
app.jinja_env.filters['format_number'] = format_number
app.jinja_env.filters['gregorian_to_shamsi'] = gregorian_to_shamsi

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'admin':
            session['role'] = 'admin'
            return redirect(url_for('admin_panel'))
        member = Member.load_by_username(username)
        if member and member.password == password:
            session['role'] = 'member'
            session['username'] = username
            return redirect(url_for('user_dashboard', username=username))
        flash('لاگین ناموفق!', 'error')
    return render_template('login.html')

@app.route('/admin')
def admin_panel():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    total_balance = get_total_balance()
    return render_template('admin.html', total_balance=total_balance)

@app.route('/admin/add_member', methods=['POST'])
def admin_add_member():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    name = request.form['name']
    join_date_shamsi = request.form['join_date']
    username = request.form['username']
    password = request.form['password']
    try:
        join_date_gregorian = shamsi_to_gregorian(join_date_shamsi)
        if add_member(name, join_date_gregorian, username, password):
            flash('عضو اضافه شد!', 'message')
        else:
            flash('نام یا یوزرنیم تکراری است!', 'error')
    except ValueError:
        flash('تاریخ شمسی نامعتبر!', 'error')
    return redirect(url_for('members'))  # ماندن توی صفحه members

@app.route('/admin/add_transaction', methods=['POST'])
def admin_add_transaction():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    member_name = request.form['member_name']
    member = Member.load_by_name(member_name)
    if not member:
        flash('عضو یافت نشد!', 'error')
        return redirect(url_for('transactions'))
    trans_type = request.form['trans_type']
    try:
        amount = int(request.form['amount'])
        tracking_code = int(request.form['tracking_code'])
    except ValueError:
        flash('مبلغ یا کد رهگیری نامعتبر است!', 'error')
        return redirect(url_for('transactions'))
    date_shamsi = request.form['date']
    description = request.form['description']

    if trans_type == 'initial':
        if amount < 5000000 or amount % 5000000 != 0:
            flash('سرمایه اولیه باید حداقل ۵ میلیون و مضرب ۵ میلیون باشد!', 'error')
            return redirect(url_for('transactions'))
    elif trans_type == 'membership':
        if amount % 250000 != 0:
            flash('عضویت ماهانه باید مضرب ۲۵۰ هزار تومان باشد!', 'error')
            return redirect(url_for('transactions'))

    try:
        date_gregorian = shamsi_to_gregorian(date_shamsi)
        add_transaction(member.id, date_gregorian, amount, trans_type, description, tracking_code)
        update_balance(member.id, amount, trans_type)
        start_date = datetime.strptime(date_gregorian, "%Y-%m-%d")
        current_date = start_date
        end_date = datetime.now()
        while current_date <= end_date:
            member.update_daily_balance(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)
        flash('تراکنش با کد رهگیری ثبت شد!', 'message')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('transactions'))  # ماندن توی صفحه transactions

@app.route('/transactions')
def transactions():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    transactions = get_all_transactions()
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

@app.route('/user/<username>')
def user_dashboard(username):
    if session.get('role') != 'member' or session.get('username') != username:
        return redirect(url_for('login'))
    member = Member.load_by_username(username)
    if member:
        current_date = datetime.now().strftime("%Y-%m-%d")
        member.update_daily_balance(current_date)
        total_initial, total_membership = member.calculate_totals()
        details = member.get_daily_balances()
        return render_template('user_dashboard.html', member=member, total_initial=total_initial, total_membership=total_membership, details=details)
    return "کاربر یافت نشد!"

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
