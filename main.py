import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# --- ADMIN CONFIGURATION ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=(
        "You are the Sentinel Systems Architect. Perform deep-dive revenue audits. "
        "Analyze data for operational gaps and AI scaling. Return strict JSON only. "
        "Keys: company_name, analysis, score, pain_points."
    )
)

def check_duplicate(url):
    """Gatekeeper: Checks Airtable for the URL. Returns True if it already exists."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    # Formula searches for exact URL match to prevent double rows
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}?filterByFormula={formula}"
    
    headers = {"Authorization": f"Bearer {at_token}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        if r.status_code == 200:
            records = r.json().get("records", [])
            return len(records) > 0
    except Exception as e:
        print(f"Duplicate Check Error: {e}")
    return False

def analyze_lead(url):
    """Scrapes and analyzes using Gemini."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(url, headers=headers, timeout=25)
        if response.status_code != 200:
            return {"error": f"Scrape Blocked (HTTP {response.status_code})"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer", "header"]):
            s.decompose()
        text = soup.get_text(separator=' ').strip()[:10000]

        prompt = f"AUDIT TARGET: {url}\n\nDATA:\n{text}\n\nReturn JSON: company_name, analysis, score, pain_points."
        ai_response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(ai_response.text)
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    
    if not website:
        return jsonify({"error": "No website URL provided"}), 400

    # STEP 1: STRICT DEDUPLICATION - Save credits
    if check_duplicate(website):
        # We update Status to 'Skipped' for existing record
        sync = send_to_airtable(website, {"status_override": "Skipped"})
        return jsonify({"status": "Skipped", "reason": "Lead already exists"}), 200

    # STEP 2: RUN ANALYSIS - Only for new rows
    result = analyze_lead(website)
    
    # STEP 3: SYNC TO AIRTABLE - Using exact Single Select labels
    sync = send_to_airtable(website, result)
    
    return jsonify({"status": "Success", "data": result, "airtable": sync}), 200

def send_to_airtable(url, result):
    """Airtable Sync using exact Single Select options: In progress, Error, Skipped, Queued, Processed."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {at_token}", "Content-Type": "application/json"}
    
    if "error" in result:
        status_label = "Error"
        fields = {"Website URL": url, "Status": status_label, "Technical Logs": result["error"]}
    elif result.get("status_override") == "Skipped":
        status_label = "Skipped"
        fields = {"Website URL": url, "Status": status_label}
    else:
        status_label = "Processed"
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "No Data"),
            "Lead Score": int(result.get("score", 0)),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": status_label
        }

    # typecast: True is mandatory for Single Select mapping
    payload = {"fields": fields, "typecast": True}
    
    r = requests.post(at_url, headers=headers, json=payload)
    return "Synced" if r.status_code == 200 else f"Airtable Denied: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
