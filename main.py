import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# --- 1. CORE CONFIGURATION ---
# Using the IDs you provided directly to ensure zero mapping errors
BASE_ID = "appz2Ed4lo9XvZ3Hp"
TABLE_NAME = "Leads"
AIRTABLE_TOKEN = "patOY4BJlkcqh1ODu.73bdbde7868fd97e04ca0e2be764c2a08cd8461acdd584af837e77903501cef8"

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=(
        "You are the Sentinel Systems Architect. Perform high-stakes revenue audits. "
        "Every analysis MUST include: 1. AI Targets (3 actionable steps), "
        "2. Quantified Revenue Impact (est. %), and 3. Competitive Urgency. "
        "Format Pain Points as a clean, bulleted string. "
        "Return strict JSON: company_name, analysis, score (1-5), pain_points."
    )
)

def check_duplicate(url):
    """Checks Airtable directly to prevent the race condition/double-row issue."""
    # We use the formula to find if this URL already exists
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}?filterByFormula={formula}"
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        records = r.json().get("records", [])
        return len(records) > 0
    except Exception as e:
        print(f"Duplicate check error: {e}")
        return False

def analyze_lead(url):
    """Audits the website and prepares the data payload."""
    try:
        if not url.startswith('http'): url = 'https://' + url
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=25)
        
        if response.status_code != 200:
            return {"error": f"Scrape Blocked (HTTP {response.status_code})"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
        text = soup.get_text(separator=' ').strip()[:10000]

        ai_response = model.generate_content(f"AUDIT TARGET: {url}\n\nDATA:\n{text}", generation_config={"response_mime_type": "application/json"})
        data = json.loads(ai_response.text)
        
        # --- DATA SANITIZATION ---
        raw_score = float(data.get("score", 0))
        if raw_score > 5: raw_score = raw_score / 2
        data["score"] = int(round(raw_score))

        pains = data.get("pain_points", "N/A")
        if isinstance(pains, list):
            data["pain_points"] = " • ".join(pains)
        
        return data
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    if not website: return jsonify({"error": "No URL provided"}), 400

    # 1. ATOMIC CHECK: If it exists, kill the process.
    if check_duplicate(website):
        return jsonify({"status": "Skipped", "reason": "Record already exists"}), 200

    # 2. ANALYSIS ENGINE
    result = analyze_lead(website)
    
    # 3. ATOMIC CREATION: One POST, all fields.
    sync = create_airtable_record(website, result)
    
    return jsonify({
        "status": "Processed" if "error" not in result else "Error",
        "airtable": sync
    }), 200

def create_airtable_record(url, result):
    """Creates a complete record in Airtable."""
    at_url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    if "error" in result:
        fields = {"Website URL": url, "Status": "Error"}
    else:
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "Audit Complete"),
            "Lead Score": result.get("score", 0),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }

    r = requests.post(at_url, headers=headers, json={"fields": fields, "typecast": True})
    
    # Logs for Render console
    print(f"Airtable Sync Result: {r.status_code} - {r.text}")
    
    return "Success" if r.status_code == 200 else f"Failed: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
