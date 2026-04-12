import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# 1. Setup Gemini (Enterprise Configuration)
# We use 'models/gemini-1.5-flash' to ensure stable routing in 2026
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('models/gemini-1.5-flash')

def analyze_lead(url):
    try:
        # Advanced Stealth Headers to bypass bot detection (403 errors)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Use a session to handle cookies automatically
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=20)
        
        if response.status_code != 200:
            return f"Sentinel Error: Could not access {url} (Status: {response.status_code})"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove junk elements to clean the data for the AI
        for element in soup(["script", "style", "nav", "footer"]):
            element.decompose()
        
        # Extract the first 7,000 characters for context
        text = soup.get_text(separator=' ').strip()[:7000]

        # Professional Prompt Logic
        prompt = (
            f"Act as a RevOps Strategy Consultant. Analyze this raw website data:\n\n{text}\n\n"
            "Provide a high-impact audit in this format:\n"
            "1. BUSINESS OVERVIEW: (What do they actually do?)\n"
            "2. REVENUE LEAKS: (Identify 3 manual processes that AI could automate to save time/money)\n"
            "3. SENTINEL SCORE: (Rate 1-10 based on automation readiness)"
        )
        
        # Call Gemini
        ai_response = model.generate_content(prompt)
        
        if not ai_response.text:
            return "Sentinel Error: AI failed to generate analysis."
            
        return ai_response.text
        
    except Exception as e:
        return f"System Error: {str(e)}"

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    if not data or "website" not in data:
        return jsonify({"error": "Missing 'website' key in JSON payload"}), 400
        
    website_url = data.get("website")

    # Step 1: Execute AI Analysis
    analysis = analyze_lead(website_url)
    
    # Step 2: Push to Airtable
    sync_status = send_to_airtable(website_url, analysis)
    
    return jsonify({
        "status": "Success",
        "analysis": analysis,
        "airtable": sync_status
    }), 200

def send_to_airtable(url, analysis):
    base_id = os.environ.get("BASE_ID")
    table_name = os.environ.get("TABLE_NAME")
    at_token = os.environ.get("AIRTABLE_TOKEN")
    
    at_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {
        "Authorization": f"Bearer {at_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "fields": {
            "Website URL": url,
            "Sentinel Analysis": analysis,
            "Status": "Processed"
        }
    }
    
    r = requests.post(at_url, headers=headers, json=payload)
    
    if r.status_code == 200:
        return "Database Updated"
    else:
        return f"Airtable Error: {r.text}"

if __name__ == "__main__":
    # Render dynamic port binding
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
