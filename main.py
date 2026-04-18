import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai
import json

app = Flask(__name__)

# 1. ARCHITECT CONFIG: Stable 2026 Engine
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash', # Stable April 2026 Target
    system_instruction=(
        "You are the Sentinel Systems Architect. Perform deep-dive revenue audits. "
        "Analyze the scraped data for operational gaps and AI scaling opportunities. "
        "You MUST return a valid JSON object. No prose. No conversational filler."
    )
)

def analyze_lead(url):
    try:
        # 2. Bypassing "The Wall" (Cloudflare/Bot protection)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=25)
        
        if response.status_code != 200:
            return {"error": f"Scrape Failed: HTTP {response.status_code}"}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        # Removing noise to maximize Gemini's context window
        for s in soup(["script", "style", "nav", "footer", "header", "aside"]):
            s.decompose()
        text = soup.get_text(separator=' ').strip()[:12000]

        # 3. Professional Extraction Logic
        prompt = (
            f"AUDIT TARGET: {url}\n\nDATA SOURCE:\n{text}\n\n"
            "INSTRUCTIONS:\n"
            "Generate a strategic JSON report with these keys:\n"
            "1. 'company_name': Full business name.\n"
            "2. 'analysis': 3-paragraph audit of business model and 3 revenue-recovery AI targets.\n"
            "3. 'score': Lead quality number (1-5).\n"
            "4. 'pain_points': One-sentence operational bottleneck.\n"
            "OUTPUT FORMAT: Strict JSON."
        )
        
        ai_response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        
        return json.loads(ai_response.text)
        
    except Exception as e:
        return {"error": f"Sentinel Logic Break: {str(e)}"}

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website = data.get("website")
    
    if not website:
        return jsonify({"error": "Missing 'website' key"}), 400

    # Execute Analysis
    result = analyze_lead(website)
    
    # Direct Admin-to-CRM Sync
    sync_report = send_to_airtable(website, result)
    
    return jsonify({
        "status": "Sentinel Active",
        "data_extracted": result,
        "airtable_sync": sync_report
    }), 200

def send_to_airtable(url, result):
    if "error" in result:
        return result["error"]

    at_url = f"https://api.airtable.com/v0/{os.environ.get('BASE_ID')}/{os.environ.get('TABLE_NAME')}"
    headers = {
        "Authorization": f"Bearer {os.environ.get('AIRTABLE_TOKEN')}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "fields": {
            "Website URL": url,
            "Company Name": result.get("company_name", "Unknown"),
            "Sentinel Analysis": result.get("analysis", "Check Logs"),
            "Lead Score": int(result.get("score", 0)),
            "Operational Pain Points": result.get("pain_points", "N/A"),
            "Status": "Processed"
        }
    }
    
    r = requests.post(at_url, headers=headers, json=payload)
    return "Sync Success" if r.status_code == 200 else f"Airtable Denied: {r.text}"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
