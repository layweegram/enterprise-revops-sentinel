import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# 1. Setup Gemini 2.5 (Current 2026 Stable Standard)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# Using the stable 2.5 version to avoid legacy 404 errors
model = genai.GenerativeModel('gemini-2.5-flash')

def analyze_lead(url):
    try:
        # High-Authority Headers to bypass 2026 bot detection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        }
        
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return f"Access Denied: Status {response.status_code}. Site may be blocked."
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style", "nav", "footer"]):
            s.decompose()
            
        text = soup.get_text(separator=' ').strip()[:8000] # 2026 models handle more context

        # The "Architect" Prompt
        prompt = (
            f"Business Audit for: {url}\n\nContent:\n{text}\n\n"
            "Analyze as an AI Systems Architect:\n"
            "1. Core Business Model\n"
            "2. Three high-value AI automation targets\n"
            "3. Scaling Score (1-10)"
        )
        
        ai_response = model.generate_content(prompt)
        return ai_response.text
        
    except Exception as e:
        return f"Sentinel Engine Error: {str(e)}"

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    
    if not website:
        return jsonify({"error": "No website URL provided"}), 400

    # 1. Run Analysis
    result = analyze_lead(website)
    
    # 2. Push to Airtable
    sync = send_to_airtable(website, result)
    
    return jsonify({"status": "Success", "analysis": result, "airtable": sync}), 200

def send_to_airtable(url, analysis):
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {at_token}", "Content-Type": "application/json"}
    
    payload = {
        "fields": {
            "Website URL": url,
            "Sentinel Analysis": analysis,
            "Status": "Success"
        }
    }
    r = requests.post(at_url, headers=headers, json=payload)
    return "Synced" if r.status_code == 200 else f"Airtable Error: {r.text}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
