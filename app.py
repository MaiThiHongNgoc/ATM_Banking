from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from config import get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = 'b\xd5\xecG\x88^\x89\xcad\xd2^\x86\xfaT^\xdd>\x82\xf9\x12\xc0\xa5\xaa\xab@'

# Trang chủ
@app.route('/')
def home():
    if 'user_id' in session:
        return render_template('index.html')
    return redirect(url_for('login'))

# Đăng ký người dùng
# Đăng ký người dùng
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']  # No hashing
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, password))  # Store plain text
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')


# Đăng nhập người dùng
# Đăng nhập người dùng
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            print("User found:", user)

            # Compare plain-text password
            if user['password'] == password:
                session['user_id'] = user['id']
                print("Login successful, user_id:", user['id'])
                return redirect(url_for('home'))
            else:
                print("Invalid password")
                return 'Invalid email or password'
        else:
            print("User not found")
            return 'Invalid email or password'

    return render_template('login.html')


# Đăng xuất người dùng
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Thay đổi mật khẩu
# Thay đổi mật khẩu
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()

        if user and user['password'] == old_password:  # Compare plain-text password
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_password, session['user_id']))  # Store plain text
            conn.commit()
            cursor.close()
            conn.close()
            return 'Password updated successfully'
        else:
            return 'Old password is incorrect'
    return render_template('change_password.html')


# Lấy số dư tài khoản
@app.route('/balance/<int:account_id>', methods=['GET'])
def get_balance(account_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT balance FROM accounts WHERE account_id=%s", (account_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if account:
        return jsonify(account)
    return jsonify({"error":"Account not found"}),404

# Nạp tiền
@app.route('/deposit', methods=['POST'])
def deposit():
    data = request.json
    account_id = data['account_id']
    amount = data['amount']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT u.email FROM users u JOIN accounts a ON u.id = a.user_id WHERE a.account_id = %s", (account_id,))
    user = cursor.fetchone()

    cursor.execute("UPDATE accounts SET balance = balance + %s WHERE account_id = %s", (amount, account_id))
    cursor.execute("INSERT INTO transactions (account_id, transaction_type, amount) VALUES (%s, %s, %s)", (account_id, 'deposit', amount))
    conn.commit()
    cursor.close()
    conn.close()

    if user:
        send_email(user['email'], "Deposit Successful", f"You have deposited {amount}.")
    
    return jsonify({"message": "Deposit successful"})

# Rút tiền
@app.route('/withdraw', methods=['POST'])
def withdraw():
    data = request.get_json()
    account_id = data['account_id']
    amount = data['amount']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT balance FROM accounts WHERE account_id = %s", (account_id,))
    account = cursor.fetchone()
    if account and account['balance'] >= amount:
        new_balance = account['balance'] - amount
        cursor.execute("UPDATE accounts SET balance = %s WHERE account_id = %s", (new_balance, account_id))
        cursor.execute("INSERT INTO transactions (account_id, transaction_type, amount) VALUES (%s, %s, %s)", (account_id, 'withdraw', amount))
        conn.commit()
        cursor.close()
        conn.close()
        
        send_email(user['email'], "Withdrawal Successful", f"You have withdrawn {amount}.")
        
        return jsonify({"message": "Withdraw successful", "new_balance": new_balance})

    cursor.close()
    conn.close()
    return jsonify({"message": "Insufficient funds"}), 400

# Chuyển tiền
@app.route('/transfer', methods=['POST'])
def transfer():
    data = request.get_json()
    from_account_id = data['from_account_id']
    to_account_id = data['to_account_id']
    amount = data['amount']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT balance FROM accounts WHERE account_id = %s", (from_account_id,))
    from_account = cursor.fetchone()

    if from_account and from_account['balance'] >= amount:
        cursor.execute("UPDATE accounts SET balance = balance - %s WHERE account_id = %s", (amount, from_account_id))
        cursor.execute("UPDATE accounts SET balance = balance + %s WHERE account_id = %s", (amount, to_account_id))
        cursor.execute("INSERT INTO transactions (account_id, transaction_type, amount) VALUES (%s, %s, %s)", (from_account_id, 'transfer', -amount))
        cursor.execute("INSERT INTO transactions (account_id, transaction_type, amount) VALUES (%s, %s, %s)", (to_account_id, 'transfer', amount))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Transfer successful"})

    cursor.close()
    conn.close()
    return jsonify({"message": "Insufficient funds"}), 400

# Lịch sử giao dịch
@app.route('/transaction_history/<int:account_id>', methods=['GET'])
def transaction_history(account_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT transaction_type, amount, date FROM transactions WHERE account_id = %s ORDER BY date DESC", (account_id,))
    transactions = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return jsonify(transactions)

# Hàm gửi email thông báo
def send_email(recipient, subject, body):
    sender = "your_email@gmail.com"
    password = "your_email_password"
    
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    app.run(debug=True)
