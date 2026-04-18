import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# 1. Setup Gemini 3.1 (Stable April 2026 Version)
# System instructions are hard-coded to ensure 'Thinking' mode behavior
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-3.1-flash',
    system_instruction=(
        "You are an Elite AI Systems Architect. Your task is to perform a deep business audit. "
        "Do not provide generic advice. Look for specific revenue recovery opportunities "
        "and operational gaps. You must return your findings in strict JSON format."
    )
)

def analyze_lead(url):
    try:
        # 2. Human-Mimicry Headers to bypass Cloudflare/Security
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Increased timeout for deep scraping
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=25)
        
        if response.status_code != 200:
            return {"error": f"Access Denied (Status {response.status_code}). Site might be protected by Cloudflare."}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Clean the data (Removes 'noise' so AI can focus on 'value')
        for s in soup(["script", "style", "nav", "footer", "header", "aside"]):
            s.decompose()
            
        text = soup.get_text(separator=' ').strip()[:12000]

        # 3. The "No Mediocrity" Prompt
        prompt = (
            f"DEEP RESEARCH TASK for {url}:\n\n"
            f"SCRAPED DATA: {text}\n\n"
            "Analyze the data above. You must return a JSON object with these exact keys:\n"
            "1. 'company_name': The full legal name of the business.\n"
            "2. 'analysis': A detailed 3-paragraph strategy covering their business model and 3 specific AI automation targets.\n"
            "3. 'score': A lead quality number (1 to 5).\n"
            "4. 'pain_points': One clear, hard-hitting sentence about their biggest operational weakness.\n"
            "Return ONLY the JSON. No conversational text."
        )
        
        # Force JSON output mode
        ai_response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        
        return json.loads(ai_response.text)
        
    except Exception as e:
        return {"error": f"Sentinel Engine Error: {str(e)}"}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    
    if not website:
        return jsonify({"error": "No website URL provided"}), 400

    # AI performs the deep audit
    result = analyze_lead(website)
    
    # Internal sync to Airtable
    sync = send_to_airtable(website, result)
    
    return jsonify({"status": "Success", "data": result, "airtable_sync": sync}), 200

def send_to_airtable(url, result):
    if "error" in result:
        return result["error"]

    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {at_token}", "Content-Type": "application/json"}
    
    # Mapped exactly to your 6 Airtable columns
    payload = {
        "fields": {
            "Website URL": url,
            "Company Name": result.get("company_name", "N/A"),
            "Sentinel Analysis": result.get("analysis", "Analysis failed"),
            "Lead Score": int(result.get("score", 0)),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }
    }
    
    r = requests.post(at_url, headers=headers, json=payload)
    return "Synced Successfully" if r.status_code == 200 else f"Airtable Sync Failed: {r.text}"

if __name__ == "__main__":
    # Standard Render/Heroku port logic
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
