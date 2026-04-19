import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# --- CONFIGURATION ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction="Analyze business data. Return strict JSON: company_name, analysis, score, pain_points."
)

def check_duplicate(url):
    """Gatekeeper: Checks Airtable for URL to avoid double-billing."""
    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}?filterByFormula={{Website URL}}='{url}'"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        return len(r.json().get("records", [])) > 0
    except: return False

def analyze_lead(url):
    """Scraper with browser-mimicry headers."""
    try:
        # Standardize URL format
        if not url.startswith('http'):
            url = 'https://' + url
            
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style"]): s.decompose()
        text = soup.get_text(separator=' ').strip()[:8000]

        ai_response = model.generate_content(f"Analyze: {text}", generation_config={"response_mime_type": "application/json"})
        return json.loads(ai_response.text)
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    if not website: return jsonify({"error": "No URL"}), 400

    # 1. Deduplication
    if check_duplicate(website):
        sync = send_to_airtable(website, {"status_override": "Skipped"})
        return jsonify({"status": "Skipped", "airtable": sync}), 200

    # 2. Analysis
    result = analyze_lead(website)
    
    # 3. Sync
    sync = send_to_airtable(website, result)
    
    return jsonify({
        "status": "Error" if "error" in result else "Processed",
        "data": result,
        "airtable": sync
    }), 200

def send_to_airtable(url, result):
    """Only sends fields confirmed to exist in your Airtable."""
    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}", "Content-Type": "application/json"}
    
    if "error" in result:
        fields = {"Website URL": url, "Status": "Error"}
    elif result.get("status_override") == "Skipped":
        fields = {"Website URL": url, "Status": "Skipped"}
    else:
        # These are the exact fields that worked for Apple
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "Done"),
            "Lead Score": int(result.get("score", 0)),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }

    r = requests.post(at_url, headers=headers, json={"fields": fields, "typecast": True})
    return "Success" if r.status_code == 200 else f"Airtable Denied: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
