import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# --- 1. ADMIN CONFIGURATION ---
# Using the stable April 2026 target to ensure 100% uptime
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=(
        "You are the Sentinel Systems Architect. Perform deep-dive revenue audits. "
        "Analyze the scraped data for operational gaps and AI scaling opportunities. "
        "You MUST return a valid JSON object with the following keys: "
        "company_name, analysis, score, pain_points. No conversational filler."
    )
)

def check_duplicate(url):
    """Gatekeeper logic: Scans Airtable for existing URL before burning AI credits."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    # We use a formula to check if the URL exists in the primary field
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}?filterByFormula={formula}"
    
    headers = {"Authorization": f"Bearer {at_token}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        if r.status_code == 200:
            records = r.json().get("records", [])
            return len(records) > 0
    except Exception as e:
        print(f"Deduplication system bypass error: {e}")
    return False

def analyze_lead(url):
    """Deep Scraping + Gemini Audit Logic."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        
        response = requests.get(url, headers=headers, timeout=25)
        if response.status_code != 200:
            return {"error": f"Scrape Failed: HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        # Removing DOM noise to maximize token efficiency
        for s in soup(["script", "style", "nav", "footer", "header", "aside"]):
            s.decompose()
        text = soup.get_text(separator=' ').strip()[:12000]

        prompt = (
            f"AUDIT TARGET: {url}\n\nDATA SOURCE:\n{text}\n\n"
            "Return a strategic JSON report: company_name, analysis, score (1-5), pain_points."
        )
        
        ai_response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(ai_response.text)
        
    except Exception as e:
        return {"error": f"Sentinel Reasoning Break: {str(e)}"}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    
    if not website:
        return jsonify({"error": "Missing 'website' field in request"}), 400

    # STEP 1: Admin Gatekeeper (Deduplication)
    if check_duplicate(website):
        # We still sync to Airtable as 'Skipped' to let the user know it was blocked
        sync_report = send_to_airtable(website, {"status": "Skipped"})
        return jsonify({"status": "Skipped", "reason": "Lead already exists in CRM"}), 200

    # STEP 2: Intelligent Audit
    result = analyze_lead(website)
    
    # STEP 3: Automated CRM Sync
    sync_report = send_to_airtable(website, result)
    
    return jsonify({
        "status": "Success",
        "data_extracted": result,
        "airtable_sync": sync_report
    }), 200

def send_to_airtable(url, result):
    """Final Output Logic with Typecast enabled to prevent 422 errors."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {
        "Authorization": f"Bearer {at_token}",
        "Content-Type": "application/json"
    }
    
    # Determine the payload based on script outcome
    if "error" in result:
        fields = {"Website URL": url, "Status": "Error", "Technical Logs": result["error"]}
    elif result.get("status") == "Skipped":
        fields = {"Website URL": url, "Status": "Skipped"}
    else:
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "No analysis produced"),
            "Lead Score": int(result.get("score", 0)),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }

    # 'typecast': True allows Airtable to automatically map text to Single Select options
    payload = {
        "fields": fields,
        "typecast": True 
    }
    
    r = requests.post(at_url, headers=headers, json=payload)
    
    if r.status_code == 200:
        return "Sync Success"
    else:
        return f"Airtable Denied (HTTP {r.status_code}): {r.text}"

if __name__ == "__main__":
    # Port 8080 is standard for Render web services
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
