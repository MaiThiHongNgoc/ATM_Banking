from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from config import get_db_connection
import smtplib
from email.mime.text import MIMEText
import jwt
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Change this in production

load_dotenv()  # Load environment variables from .env file

JWT_SECRET = os.getenv("JWT_SECRET")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Home page
@app.route('/')
def home():
    token = session.get('jwt_token')
    if token:
        try:
            user_data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            user_id = user_data['user_id']
            
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Fetch the account details for the logged-in user
            cursor.execute("SELECT a.account_id, a.balance, u.name FROM accounts a JOIN users u ON a.user_id = u.id WHERE u.id = %s", (user_id,))
            account = cursor.fetchone()

            cursor.close()
            conn.close()

            return render_template('index.html', account=account)  # Pass account details to the template
        except jwt.ExpiredSignatureError:
            return redirect(url_for('login'))  # Token expired, redirect to login
        except jwt.InvalidTokenError:
            return redirect(url_for('login'))  # Invalid token, redirect to login
    return redirect(url_for('login'))  # No token, redirect to login


# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, password))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

# Login route using JWT
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s AND password = %s", (email, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            token = jwt.encode({
                'user_id': user['id'],  # Embed the user's ID in the token payload
                'exp': datetime.now(timezone.utc) + timedelta(hours=24)  # Token expires in 24 hours
            }, JWT_SECRET, algorithm="HS256")  # Use the secret key to sign the token

            session['jwt_token'] = token  # Save the generated token in the session
            return redirect(url_for('home'))  # Redirect to the home page after login
        else:
            return 'Invalid email or password'  # Handle invalid login


    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('jwt_token', None)
    return redirect(url_for('login'))

# Middleware to protect routes with JWT
def jwt_required(func):
    def wrapper(*args, **kwargs):
        token = session.get('jwt_token')
        if not token:
            return redirect(url_for('login'))
        try:
            jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return redirect(url_for('login'))
        except jwt.InvalidTokenError:
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# Change password
@app.route('/change_password', methods=['GET', 'POST'])
@jwt_required
def change_password():
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        token = session.get('jwt_token')
        user_data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        user_id = user_data['user_id']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password FROM users WHERE id = %s AND password = %s", (user_id, old_password))
        user = cursor.fetchone()

        if user:
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_password, user_id))
            conn.commit()
            cursor.close()
            conn.close()
            return 'Password updated successfully'
        else:
            return 'Old password is incorrect'
    return render_template('change_password.html')

# Get account balance
@app.route('/balance/<int:account_id>', methods=['GET'])
@jwt_required
def get_balance(account_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT balance FROM accounts WHERE account_id=%s", (account_id,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()

    if account:
        return jsonify(account)
    return jsonify({"error": "Account not found"}), 404

# Deposit route
@app.route('/deposit', methods=['GET', 'POST'])
@jwt_required
def deposit():
    if request.method == 'POST':
        account_id = request.form['account_id']
        amount = float(request.form['amount'])

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
    return render_template('deposit.html')

# Withdraw route
@app.route('/withdraw', methods=['GET', 'POST'])
@jwt_required
def withdraw():
    if request.method == 'POST':
        account_id = request.form['account_id']
        amount = Decimal(request.form['amount'])  # Convert to Decimal

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch the account details
        cursor.execute("SELECT balance FROM accounts WHERE account_id = %s", (account_id,))
        account = cursor.fetchone()

        if account:
            # Check if sufficient balance is available
            if account['balance'] >= amount:
                new_balance = account['balance'] - amount  # Perform subtraction
                cursor.execute("UPDATE accounts SET balance = %s WHERE account_id = %s", (new_balance, account_id))
                cursor.execute("INSERT INTO transactions (account_id, transaction_type, amount) VALUES (%s, %s, %s)", (account_id, 'withdraw', amount))
                conn.commit()
                message = "Withdrawal successful"
            else:
                message = "Insufficient balance"
        else:
            message = "Account not found"

        cursor.close()
        conn.close()
        return jsonify({"message": message})

    return render_template('withdraw.html')

# Transfer route
@app.route('/transfer', methods=['GET', 'POST'])
@jwt_required
def transfer():
    if request.method == 'POST':
        from_account_id = request.form['from_account_id']
        to_account_id = request.form['to_account_id']
        amount = float(request.form['amount'])

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
    return render_template('transfer.html')

# Transaction history route
@app.route('/transaction_history/<int:account_id>', methods=['GET'])
@jwt_required
def transaction_history(account_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT transaction_type, amount, date FROM transactions WHERE account_id = %s ORDER BY date DESC", (account_id,))
    transactions = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(transactions)

# Send email function
def send_email(recipient, subject, body):
    sender = EMAIL_SENDER
    password = EMAIL_PASSWORD

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
    except Exception as e:
        print(f"Error sending email: {e}")

if __name__ == '__main__':
    app.run(debug=True)
