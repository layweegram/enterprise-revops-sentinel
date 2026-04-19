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
    system_instruction="Analyze business data. Return strict JSON: company_name, analysis, score, pain_points."
)

def check_duplicate(url):
    """Checks Airtable for URL to avoid burning credits or creating double rows."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    # Matches your former code's formula logic
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}?filterByFormula={formula}"
    
    headers = {"Authorization": f"Bearer {at_token}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        records = r.json().get("records", [])
        return len(records) > 0
    except:
        return False

def analyze_lead(url):
    """Standardizes URL and performs the AI Audit."""
    try:
        # Standardize URL format as per your former code
        if not url.startswith('http'):
            url = 'https://' + url
            
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=25)
        
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer"]): 
            s.decompose()
        text = soup.get_text(separator=' ').strip()[:10000]

        ai_response = model.generate_content(f"Analyze: {text}", generation_config={"response_mime_type": "application/json"})
        return json.loads(ai_response.text)
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    if not website: 
        return jsonify({"error": "No URL"}), 400

    # STEP 1: DEDUPLICATION
    # We exit IMMEDIATELY if it exists. We do NOT call send_to_airtable here.
    # This prevents the 'Ghost Row' issue.
    if check_duplicate(website):
        return jsonify({"status": "Skipped", "reason": "URL already exists in Airtable"}), 200

    # STEP 2: ANALYSIS
    # Scrape the site and get AI results before touching Airtable.
    result = analyze_lead(website)
    
    # STEP 3: SINGLE SYNC
    # We only create ONE record at the very end.
    sync = send_to_airtable(website, result)
    
    return jsonify({
        "status": "Processed" if "error" not in result else "Error",
        "data": result,
        "airtable": sync
    }), 200

def send_to_airtable(url, result):
    """Updates Airtable using your exact confirmed field names."""
    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}", "Content-Type": "application/json"}
    
    if "error" in result:
        # Standardized Error status
        fields = {"Website URL": url, "Status": "Error"}
    else:
        # EXACT fields from your successful Apple run
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "Complete"),
            "Lead Score": int(result.get("score", 0)),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }

    # Atomic POST request
    r = requests.post(at_url, headers=headers, json={"fields": fields, "typecast": True})
    return "Success" if r.status_code == 200 else f"Airtable Denied: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
