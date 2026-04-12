import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# 1. Setup Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('models/gemini-1.5-flash')

def analyze_lead(url):
    try:
        # Advanced Stealth Headers to bypass 403 blocks
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
        # We use a session to handle cookies, which helps with 403s
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=20)
        
        if response.status_code == 403:
            return f"Error: 403 Forbidden. {url} is blocking our bot. Try another URL like 'https://www.apple.com' or 'https://www.hubspot.com'."
        
        if response.status_code != 200:
            return f"Error: Status {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text()[:7000]

        prompt = (
            f"Analyze this business data:\n\n{text}\n\n"
            "Provide:\n"
            "1. Business Summary\n"
            "2. Three AI automation opportunities to recover revenue.\n"
            "3. Lead Score (1-10)."
        )
        
        ai_response = model.generate_content(prompt)
        return ai_response.text if ai_response.text else "AI returned empty response."
        
    except Exception as e:
        return f"Sentinel Error: {str(e)}"

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website_url = data.get("website")
    if not website_url:
        return jsonify({"error": "No URL"}), 400

    analysis = analyze_lead(website_url)
    sync_status = send_to_airtable(website_url, analysis)
    
    return jsonify({"status": "Complete", "analysis": analysis, "sync": sync_status}), 200

def send_to_airtable(url, analysis):
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {at_token}", "Content-Type": "application/json"}
    
    payload = {"fields": {"Website URL": url, "Sentinel Analysis": analysis, "Status": "Success"}}
    r = requests.post(at_url, headers=headers, json=payload)
    return "Synced" if r.status_code == 200 else f"Error: {r.text}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
