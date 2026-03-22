# Lead-generator-
## Lead-generator Structure
lead_generator/
│
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
└── templates/
    └── index.html

## How to run the lead generator on Windows

Open Command Prompt in your project folder.

Go to your folder:
cd Path:\lead_generator

Create virtual environment:
python -m venv .venv (if this doesnt work try this first-> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate and continue with python -m venv .venv)

Activate it in CMD:
.venv\Scripts\activate.bat

Install dependencies:
pip install -r requirements.txt

Run the app:
python app.py

You should see:
* Running on http://127.0.0.1:5000

Open browser and go to:
http://127.0.0.1:5000
