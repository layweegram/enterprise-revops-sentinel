
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
        "You are the Sentinel Systems Architect. Analyze business data. "
        "Return strict JSON only: company_name, analysis, score, pain_points. "
        "IMPORTANT: The 'score' MUST be an integer from 1 to 5."
    )
)

def check_duplicate(url):
    """Prevents double rows and credit waste."""
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    formula = f"{{Website URL}}='{url}'"
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}?filterByFormula={formula}"
    
    headers = {"Authorization": f"Bearer {at_token}"}
    try:
        r = requests.get(at_url, headers=headers, timeout=10)
        return len(r.json().get("records", [])) > 0
    except:
        return False

def analyze_lead(url):
    """Scrapes site and forces a 1-5 integer score."""
    try:
        if not url.startswith('http'): url = 'https://' + url
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=25)
        
        if response.status_code != 200:
            return {"error": f"Scrape Blocked: HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer"]): s.decompose()
        text = soup.get_text(separator=' ').strip()[:10000]

        ai_response = model.generate_content(f"Analyze: {text}", generation_config={"response_mime_type": "application/json"})
        data = json.loads(ai_response.text)
        
        # --- SCORE NORMALIZATION LOGIC ---
        raw_score = float(data.get("score", 0))
        # If AI gave us a score out of 10, halve it. 
        if raw_score > 5:
            raw_score = raw_score / 2
        # Round to nearest integer (Airtable Ratings hate decimals)
        data["score"] = int(round(raw_score))
        
        return data
    except Exception as e:
        return {"error": str(e)}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    if not website: return jsonify({"error": "No URL"}), 400

    if check_duplicate(website):
        return jsonify({"status": "Skipped", "reason": "Already in Airtable"}), 200

    result = analyze_lead(website)
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
            "Lead Score": result.get("score", 0), # Now a guaranteed integer 1-5
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }

    r = requests.post(at_url, headers=headers, json={"fields": fields, "typecast": True})
    return "Success" if r.status_code == 200 else f"Airtable Denied: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
