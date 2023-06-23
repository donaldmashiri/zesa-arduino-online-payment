from flask import Flask, jsonify, request, redirect, render_template, url_for, flash, session
from flask_session import Session
from flask_login import LoginManager, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
from models import *
import random
import serial
from apscheduler.schedulers.background import BackgroundScheduler
import vonage



# You can change this to any folder on your system
ALLOWED_EXTENSIONS = {'jpeg'}

# serial_port = 'COM5'
# arduino = serial.Serial(serial_port, 9600, timeout=1)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ProfessorSecret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:''@localhost/zesa_db'

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

scheduler = BackgroundScheduler(daemon=True)



with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    
    return User.query.filter_by(id=user_id).first()

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    return render_template('index.html', meter=meter)



@app.route('/usage', methods=['GET', 'POST'])
@login_required
def usage():
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    return render_template('usage.html', meter=meter)


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Check if a valid image file was uploaded
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if email == '' or password == '':
            flash('error some fields are empty.')
            return redirect(url_for('login'))

        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash('error Invalid login details.')
            return redirect(url_for('login'))
        if check_password_hash(user.password, password):
            login_user(user)
            session['userid'] = user.id
            return redirect(url_for('index'))

        flash('error Invalid login details.')
        return redirect(url_for('login'))
    
    start_scheduler()
    my_task()

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == "POST":
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        password2 = request.form.get('password_confirmation')

        if password != password2:
            flash('error Password confirmation should match!')
            return redirect(url_for('register'))

        if len(password) <= 7:
            flash('error Password should be 8 characters or greater!')
            return redirect(url_for('register'))

        user = User.query.filter_by(email=email).first()
        if user:
            flash('error Email already exists!')
            return redirect(url_for('register'))
        new_user = User(email=email, password=generate_password_hash(password, method='sha256'), name=name, role=1)
        db.session.add(new_user)
        db.session.commit()

        mnum = random.randint(10000000, 99999999)
        new_meter = Meter(user_id=new_user.id, num=mnum, units=0.0, balance=0.00)
        db.session.add(new_meter)
        db.session.commit()

        flash('Successfully register new user!')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/transfer', methods=['GET','POST'])
@login_required
def transfer():
    if request.method == "POST":
        from decimal import Decimal
        accnum = request.form.get('mnum')
        try:
            units = Decimal(request.form.get('units'))
        except:
            flash('error units must be numeric')
            return redirect(url_for('transfer'))

        if not accnum or not units:
            flash('error some fields are empty!')
            return redirect(url_for('transfer'))

        destination = Meter.query.filter_by(num=accnum).first()
        src = Meter.query.filter_by(user_id=session['userid']).first()
        if not destination:
            flash('error meter number does not exist')
            return redirect(url_for('transfer'))


        if src.units < units:
            flash('error you have insufficient units to transfer!')
            return redirect(url_for('transfer'))
        
        destination.units = destination.units + units
        db.session.commit()

        src.units = src.units - units
        db.session.commit()
        flash('Successfully transfered units!')
        return redirect(url_for('transfer'))
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    return render_template('transfer.html', meter=meter)


@app.route('/set_units', methods=['GET','POST'])
@login_required
def set_units():
    if request.method == "POST":
        
        from decimal import Decimal
        newunits = Decimal(request.form.get('units'))
        try:
            newunits = Decimal(request.form.get('units'))
        except:
            flash('error units must be numeric')
            return redirect(url_for('transfer'))
        
        # destination = Meter.query.filter_by(num=accnum).first()
        # src = Meter.query.filter_by(user_id=session['userid']).first()
        
        # destination.units = destination.units + units
        # db.session.commit()

        # src.units = src.units - units

        newunits = Decimal(request.form.get('units'))
        client = vonage.Client(key="c544c82f", secret="6KlMO8PayzTj86ms")
        sms = vonage.Sms(client)
        responseData = sms.send_message(
            {
                "from": "ZETDC",
                "to": "263775117982",  # Replace with the recipient's phone number
                "text": "ZESA PREPAID - You have set your ZESA Units to " + str(newunits),
            }
        )

        if responseData["messages"][0]["status"] == "0":
            print("Message sent successfully.")
        else:
            print(f"Message failed with error: {responseData['messages'][0]['error-text']}")

        
        meter = Meter.query.filter_by(user_id=session['userid']).first()
        meter.units = newunits * 10
        db.session.commit()

        start_scheduler()
        my_task()
      
        db.session.commit()
        flash('Message sent & Successfully Set units!')
        return redirect(url_for('set_units'))
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    return render_template('set_units.html', meter=meter)

def is_valid_zimbabwean_number(phone_number):
    import re
    phone_number = phone_number.strip()

    pattern = r"^(07\d{8}|7\d{8})$"

    if re.match(pattern, phone_number):
        return True
    else:
        return False

@app.route('/topup', methods=['GET','POST'])
@login_required
def topup():
    if request.method == "POST":
        from decimal import Decimal
        from topup import Topup
        email = request.form.get('email')
        phone = request.form.get('phone')
        try:
            amount = Decimal(request.form.get('amount'))
        except:
            flash('error amount must be numeric')
            return redirect(url_for('topup'))

        # if is_valid_zimbabwean_number(phone):
        #     flash('error phone must be a valid zimbabwean number!')
        #     return redirect(url_for('topup'))
        meter = Meter.query.filter_by(user_id=session['userid']).first()
        if not meter:
            flash('error this account has no meter specified')
            return redirect(url_for('topup'))

        paynow = Topup.pay_now(amount=amount, phone=phone, email=email)
        if not paynow:
            flash('error could not complete transaction, try again later!')
            return redirect(url_for('topup'))
        
        meter.balance = meter.balance + amount
        meter.units = meter.units + (amount*1000)
        db.session.commit()

        flash('successfully toped up meter balance')
        return redirect(url_for('topup'))
        
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    return render_template('topup.html', meter=meter)


@app.route('/emergency', methods=['GET','POST'])
@login_required
def emergency():
    if request.method == "POST":
        option = request.form.get('option')

        if not option:
            flash('error the option field is empty')
            return redirect(url_for('emergency'))
        
        meter = Meter.query.filter_by(user_id=session['userid']).first()
        if not meter:
            flash('error this account has no meter specified')
            return redirect(url_for('emergency'))
        
        eme = Emergency.query.filter_by(id=option).first()
        if not eme:
            flash('error emegency units not found!')
            return redirect(url_for('emergency'))

        if meter.units > 1:
            flash('error its not an emergency situation yet')
            return redirect(url_for('emergency'))
        
        meter.units = meter.units + eme.units
        meter.balance = meter.balance - eme.price
        db.session.commit()

        new_log = Log(used_units=0, remaining_units=meter.balance, activity="emegency topup")
        db.session.add(new_log)
        db.session.commit()

        flash('successfully added emergency units')
        return redirect(url_for('emergency'))
        
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    emes = Emergency.query.all()
    return render_template('emergency.html', meter=meter, emes=emes)


@app.route('/report', methods=['GET','POST'])
@login_required
def report():
    if request.method == "POST":
        f_rom = request.form.get('from')
        to = request.form.get('to')

        if not f_rom or not to:
            flash('error the option field is empty')
            return redirect(url_for('emergency'))
        
        meter = Meter.query.filter_by(user_id=session['userid']).first()
        if not meter:
            flash('error this account has no meter specified')
            return redirect(url_for('emergency'))
        
        eme = Emergency.query.filter_by(id=f_rom).first()
        if not eme:
            flash('error emegency units not found!')
            return redirect(url_for('emergency'))

        if meter.units > 1:
            flash('error its not an emergency situation yet')
            return redirect(url_for('emergency'))
        
        meter.units = meter.units + eme.units
        meter.balance = meter.balance - eme.price
        db.session.commit()

        new_log = Log(used_units=0, remaining_units=meter.balance, activity="emegency topup")
        db.session.add(new_log)
        db.session.commit()

        flash('successfully added emergency units')
        return redirect(url_for('emergency'))
        
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    emes = Emergency.query.all()
    return render_template('emergency.html', meter=meter, emes=emes)


@app.route('/activate', methods=['GET'])
@login_required
def activate():
    data = "1"
    arduino.write(data.encode())
    return redirect(url_for('index'))

@app.route('/deactivate', methods=['GET'])
@login_required
def deactivate():
    data = "0"
    arduino.write(data.encode())
    return redirect(url_for('index'))


def my_task():
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    meter.units = meter.units - 200
    db.session.commit()
    
    data = str(meter.units)
    arduino.write(data.encode())
    print(data)

# Define the endpoint that starts the scheduler
@app.route('/start_scheduler')
def start_scheduler():
    meter = Meter.query.filter_by(user_id=session['userid']).first()
    meter.units = meter.units - 200
    db.session.commit()
    my_task()
    # scheduler.add_job(my_task, 'interval', minutes=1)
    # scheduler.start()
    return render_template('magic.html')



@app.route('/logout', methods=['GET'])
@login_required
def logout():
    logout_user()
    g=None
    return redirect(url_for('index'))



if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)