import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction="Analyze business data. Return strict JSON: company_name, analysis, score, pain_points."
)

def check_duplicate(url):
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}?filterByFormula={formula}"
    headers = {"Authorization": f"Bearer {at_token}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        return len(r.json().get("records", [])) > 0
    except: return False

def analyze_lead(url):
    try:
        # High-level Browser Mimicry
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        }
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            return {"error": f"Site Blocked: HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text(separator=' ').strip()[:8000]
        
        ai_response = model.generate_content(f"Data: {text}", generation_config={"response_mime_type": "application/json"})
        return json.loads(ai_response.text)
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    if not website: return jsonify({"error": "No URL"}), 400

    if check_duplicate(website):
        sync = send_to_airtable(website, {"status_override": "Skipped"})
        return jsonify({"status": "Skipped", "airtable": sync}), 200

    result = analyze_lead(website)
    sync = send_to_airtable(website, result)
    
    return jsonify({
        "status": "Error" if "error" in result else "Processed",
        "data": result,
        "airtable": sync
    }), 200

def send_to_airtable(url, result):
    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}"
    headers = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}", "Content-Type": "application/json"}
    
    if "error" in result:
        # Error Payload
        fields = {"Website URL": url, "Status": "Error"}
    elif result.get("status_override") == "Skipped":
        fields = {"Website URL": url, "Status": "Skipped"}
    else:
        # Success Payload
        fields = {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "Complete"),
            "Lead Score": int(result.get("score", 0)),
            "Status": "Processed"
        }

    r = requests.post(at_url, headers=headers, json={"fields": fields, "typecast": True})
    return "Success" if r.status_code == 200 else f"Fail: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
