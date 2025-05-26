from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
from flask_mysqldb import MySQL
from dotenv import load_dotenv
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from email.message import EmailMessage
from preprocess import VoiceBot
import MySQLdb.cursors
import smtplib
import re
import os 
import uuid
import numpy as np
import soundfile as sf

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
voicebot = VoiceBot(api_key=os.getenv("GEMINI_API_KEY"))
sc = URLSafeTimedSerializer(app.secret_key)

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')

mysql = MySQL(app)

@app.route('/verify/<token>')
def verify_email(token):
    try:
        email = sc.loads(token, salt='email-confirm', max_age=3600)  # 1 hour validity
        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE users SET verified = 1 WHERE emailID = %s', (email,))
        mysql.connection.commit()
        return 'Email verified successfully! You can now log in.'
    except Exception as e:
        return 'Verification link is invalid or has expired.'

@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'email' in request.form:
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        userAcc = cursor.fetchone()
        cursor.execute('SELECT * FROM users WHERE emailID = %s', (email,))
        emailAcc = cursor.fetchone()
        if emailAcc:
            msg = 'Email is already registered! <a href="/login">login instead</a>'
        elif userAcc:
            msg = 'Account already exists!'
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            msg = 'Invalid email address!'
        elif not re.match(r'^[A-Za-z0-9@._-]+$', username):
            msg = 'Username should only contain letters, numbers and symbols like "._-@!"'
        elif not username or not password or not email:
            msg = 'Please fill out the form!'
        else:
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            cursor.execute('INSERT INTO users (username, password, emailID, displayname, verified) VALUES (%s, %s, %s, %s, %s)', (username, hashed_password, email, '', 0))            
            mysql.connection.commit()
            msg = 'You have successfully registered!'
            token = sc.dumps(email, salt='email-confirm')
            def send_verification_email(to_email, token):
                link = url_for('verify_email', token=token, _external=True)
                subject = "Verify Your Email"
                body = f'Click the link to verify your email: {link}'
                msg = EmailMessage()
                msg['Subject'] = subject
                msg['From'] = os.getenv('EMAIL_USER')
                msg['To'] = to_email
                msg.set_content(body)
                with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                    smtp.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASS'))
                    smtp.send_message(msg)
                    try:
                        send_verification_email(email, token)
                    except Exception as e:
                        print("Email failed:", e)
            msg = 'Registration successful! Please check your email to verify your account.'
    return render_template('register.html', msg=msg)
    
@app.route('/')
@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()
        if account and check_password_hash(account['password'], password):
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']
            return render_template('index.html', msg='Logged in successfully!')
        else:
            msg = 'Incorrect username/password!'
    return render_template('login.html', msg=msg) 
@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    msg = ''
    if request.method == 'POST':
        email = request.form['email']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE emailID = %s', (email,))
        user = cursor.fetchone()
        if user:
            token = sc.dumps(email, salt='password-reset')
            reset_link = url_for('reset_password', token=token, _external=True)
            subject = "Reset Your Password"
            body = f"Click the link to reset your password: {reset_link}"
            msg_email = EmailMessage()
            msg_email['Subject'] = subject
            msg_email['From'] = os.getenv('EMAIL_USER')
            msg_email['To'] = email
            msg_email.set_content(body)
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASS'))
                smtp.send_message(msg_email)
            msg = 'Password reset email sent. Check your inbox.'
        else:
            msg = 'Email not found!'
    return render_template('forgot_password.html', msg=msg)
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    msg = ''
    try:
        email = sc.loads(token, salt='password-reset', max_age=3600)
    except:
        return 'The reset link is invalid or has expired.'
    
    if request.method == 'POST':
        new_password = request.form['password']
        hashed_pw = generate_password_hash(new_password, method='pbkdf2:sha256')
        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE users SET password = %s WHERE emailID = %s', (hashed_pw, email))
        mysql.connection.commit()
        msg = 'Your password has been reset successfully!'
        return redirect(url_for('login'))

    return render_template('reset_password.html', msg=msg)
@app.route('/debate')
def debate_page():
    if 'loggedin' in session:
        return render_template('debate.html')
    return redirect(url_for('login'))
@app.route('/submit-audio', methods=['POST'])
def submit_audio():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio uploaded"}), 400

    audio_file = request.files['audio']
    filename = str(uuid.uuid4()) + ".wav"
    audio_path = os.path.join("uploads", filename)
    os.makedirs("uploads", exist_ok=True)
    audio_file.save(audio_path)

    # Convert audio to text
    user_text = voicebot.generate_text(audio_path)

    # Generate AI response from text
    ai_response = voicebot.generate_response(user_text)

    # Save AI-generated audio to Downloads folder
    from pathlib import Path
    downloads_path = str(Path.home() / "Downloads")
    os.makedirs(downloads_path, exist_ok=True)
    output_filename = f"{uuid.uuid4()}.wav"
    output_path = os.path.join(downloads_path, output_filename)

    voicebot.generate_audio(ai_response, output_path)

    return jsonify({
        "ai_text": ai_response,
        "audio_url": f"Saved to Downloads as: {output_filename}"
    })
if __name__ == '__main__':
    app.run(debug=True)
