import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# --- 1. ADMIN CONFIGURATION ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=(
        "You are the Sentinel Systems Architect. Perform high-stakes revenue audits. "
        "Every analysis MUST include: 1. AI Targets (3 actionable steps), "
        "2. Quantified Revenue Impact (est. %), and 3. Competitive Urgency. "
        "Format Pain Points as a clean, bulleted string, NOT a JSON array. "
        "Return strict JSON: company_name, analysis, score (1-5), pain_points."
    )
)

def check_duplicate(url):
    """The Ultimate Gatekeeper: Checks Airtable to prevent the 'Double Row' race condition."""
    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}?filterByFormula={{Website URL}}='{url}'"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        records = r.json().get("records", [])
        return len(records) > 0
    except:
        return False

def analyze_lead(url):
    """Enhanced Scraper + Standardized Audit Engine."""
    try:
        if not url.startswith('http'): url = 'https://' + url
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=25)
        
        if response.status_code != 200:
            return {"error": f"Scrape Blocked (HTTP {response.status_code})"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
        text = soup.get_text(separator=' ').strip()[:10000]

        ai_response = model.generate_content(f"AUDIT TARGET: {url}\n\nDATA:\n{text}", generation_config={"response_mime_type": "application/json"})
        data = json.loads(ai_response.text)
        
        # --- CLEANING & NORMALIZATION ---
        # Ensure score is 1-5 integer
        raw_score = float(data.get("score", 0))
        if raw_score > 5: raw_score = raw_score / 2
        data["score"] = int(round(raw_score))

        # Clean Pain Points (Convert list to clean string if AI failed to follow string instruction)
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
    if not website: return jsonify({"error": "No URL"}), 400

    # PRE-FLIGHT CHECK: Stop duplicates BEFORE they hit the board
    if check_duplicate(website):
        return jsonify({"status": "Skipped", "reason": "Already exists"}), 200

    # ENGINE: Run the heavy lifting
    result = analyze_lead(website)
    
    # FINAL SYNC: Atomic record creation
    sync = send_to_airtable(website, result)
    
    return jsonify({
        "status": "Processed" if "error" not in result else "Error",
        "airtable": sync
    }), 200

def send_to_airtable(url, result):
    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}", "Content-Type": "application/json"}
    
    if "error" in result:
        fields = {"Website URL": url, "Status": "Error"}
    else:
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "Audit Done"),
            "Lead Score": result.get("score", 0),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }

    r = requests.post(at_url, headers=headers, json={"fields": fields, "typecast": True})
    return "Synced" if r.status_code == 200 else f"Failed: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
