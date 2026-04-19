import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# 1. ADMIN CONFIG: Gemini 2.5 Stable
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=(
        "You are the Sentinel Systems Architect. Perform deep-dive revenue audits. "
        "Analyze data for operational gaps and AI scaling. Return strict JSON only."
    )
)

def check_duplicate(url):
    """Admin Gatekeeper: Prevents mediocre duplicates in Airtable."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    # Formula finds exact URL match. Note: uses curly brackets for field with space.
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}?filterByFormula={formula}"
    
    headers = {"Authorization": f"Bearer {at_token}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        if r.status_code == 200:
            records = r.json().get("records", [])
            return len(records) > 0
    except Exception as e:
        print(f"Deduplication Check Failed: {e}")
    return False

def analyze_lead(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(url, headers=headers, timeout=25)
        if response.status_code != 200:
            return {"error": f"Scrape Blocked: {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer", "header"]):
            s.decompose()
        text = soup.get_text(separator=' ').strip()[:12000]

        prompt = (
            f"AUDIT TARGET: {url}\n\nDATA:\n{text}\n\n"
            "Return JSON: company_name, analysis (3 paragraphs), score (1-5), pain_points."
        )
        
        ai_response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(ai_response.text)
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    
    if not website:
        return jsonify({"error": "No website URL provided"}), 400

    # --- STEP 1: DEDUPLICATION ---
    if check_duplicate(website):
        return jsonify({"status": "Skipped", "reason": "Lead already exists"}), 200

    # --- STEP 2: ANALYSIS ---
    result = analyze_lead(website)
    
    # --- STEP 3: AIRTABLE SYNC ---
    sync = send_to_airtable(website, result)
    
    return jsonify({"status": "Success", "data": result, "airtable": sync}), 200

def send_to_airtable(url, result):
    if "error" in result:
        # Log technical error to Airtable even if AI fails
        payload = {"fields": {"Website URL": url, "Status": "Error", "Technical Logs": result["error"]}}
    else:
        payload = {
            "fields": {
                "Website URL": url,
                "Company Name": result.get("company_name"),
                "Sentinel Analysis": result.get("analysis"),
                "Lead Score": int(result.get("score", 0)),
                "Operational Pain Points": result.get("pain_points"),
                "Status": "Processed"
            }
        }

    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}", "Content-Type": "application/json"}
    
    r = requests.post(at_url, headers=headers, json=payload)
    return "Synced" if r.status_code == 200 else f"Airtable Denied: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
