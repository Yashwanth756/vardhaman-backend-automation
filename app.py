# vardhaman_flask_scraper.py
from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_cors import CORS 

app = Flask(__name__)
CORS(app) 


# --- Scraper for one account ---
def scrape_account(rollno, password):
    session = requests.Session()
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "Referer": "https://studentscorner.vardhaman.org/",
            "Origin": "https://studentscorner.vardhaman.org",
        }

        login_url = "https://studentscorner.vardhaman.org/"

        # Step 1: Load login page (get cookies + hidden fields)
        login_page = session.get(login_url, headers=headers)
        login_page.raise_for_status()

        soup = BeautifulSoup(login_page.text, "html.parser")
        hidden_inputs = {
            tag["name"]: tag.get("value", "")
            for tag in soup.find_all("input", type="hidden")
            if tag.get("name")
        }

        # Step 2: Submit login
        login_data = {
            "rollno": rollno,
            "wak": password,
            "ok": "SignIn",
            **hidden_inputs,  # include CSRF tokens if present
        }

        res = session.post(login_url, data=login_data, headers=headers)
        res.raise_for_status()

        # Step 3: Credit Register
        reg_url = "https://studentscorner.vardhaman.org/src_programs/students_corner/CreditRegister/credit_register.php"
        reg_res = session.get(reg_url, headers=headers)
        reg_res.raise_for_status()

        # Step 4: Parse
        data = parse_marks(reg_res.text)
        data["student"]["roll_number"] = rollno
        return {**data, "status": "success"}

    except Exception as e:
        print(f"❌ Failed for {rollno}: {e}")
        return {
            "student": {"roll_number": rollno, "name": None},
            "semesters": [],
            "overall": {},
            "status": "failed",
            "error": str(e),
        }


# --- Parser ---
def parse_marks(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {"student": {}, "semesters": [], "overall": {}}

    # Student info
    fonts = soup.find_all("font", {"color": "blue"})
    name = fonts[1].get_text(strip=True) if len(fonts) > 1 else ""
    roll = None
    for td in soup.find_all("td"):
        txt = td.get_text(strip=True)
        if txt.isdigit() and len(txt) == 10:
            roll = txt
            break

    data["student"]["name"] = " ".join(name.split())
    data["student"]["roll_number"] = roll

    # Semesters
    for th in soup.find_all("th", string=lambda s: s and "Semester -" in s):
        semester_title = th.get_text(strip=True)
        semester = {"semester": semester_title, "subjects": []}

        row = th.find_parent("tr").find_next_sibling("tr")
        while row and not any(x in row.get_text() for x in ["Semester -", "Total Credits"]):
            cols = row.find_all("td")
            if len(cols) >= 7 and cols[0].get_text(strip=True).isdigit():
                semester["subjects"].append({
                    "code": cols[1].get_text(strip=True),
                    "title": cols[2].get_text(strip=True),
                    "grade_point": try_float(cols[3].get_text(strip=True)),
                    "grade": cols[4].get_text(strip=True),
                    "status": cols[5].get_text(strip=True),
                    "credits": try_float(cols[6].get_text(strip=True), 0),
                })

            if "Semester Grade Point Average" in row.get_text():
                sgpa = extract_number(row.get_text())
                if sgpa is not None:
                    semester["sgpa"] = sgpa

            row = row.find_next_sibling("tr")

        data["semesters"].append(semester)

    # Overall
    def get_text(keyword):
        th = soup.find("th", string=lambda s: s and keyword in s)
        return th.get_text() if th else ""

    data["overall"] = {
        "total_credits": extract_number(get_text("Total Credits")),
        "secured_credits": extract_number(get_text("Total Secured Credits")),
        "cgpa": extract_number(get_text("Cumulative Grade Point Average")),
    }
    return data


def try_float(val, default=None):
    try:
        return float(val)
    except:
        return default


def extract_number(text):
    match = re.search(r"([0-9.]+)", text)
    return float(match.group(1)) if match else None


# --- API endpoint ---
@app.route("/scrape", methods=["POST", "GET"])
def scrape_multiple():
    if request.method == "GET":
        # Simply return a message for GET
        return jsonify({"message": "Send a POST request with JSON body containing accounts."}), 200

    # POST method: expects JSON list of accounts
    accounts = request.get_json()  # safer than request.json
    if not isinstance(accounts, list):
        return jsonify({"error": "Invalid input, must be a list"}), 400

    results = []
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(scrape_account, acc["roll_number"], acc["password"]) for acc in accounts]
        for f in as_completed(futures):
            results.append(f.result())

    return jsonify(results), 200

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Vardhaman Flask Scraper is running. Use the /scrape endpoint to POST accounts."}), 200

if __name__ == "__main__":
    app.run(debug=True)
