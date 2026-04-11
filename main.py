import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# 1. Setup Gemini (Pulling from Environment Variables)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

def analyze_lead(url):
    try:
        # Advanced Data Retrieval
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Clean text for Gemini
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text()[:6000] # High context window

        # Agentic Reasoning Prompt
        prompt = (
            f"You are an Enterprise Systems Architect. Analyze this company's website data:\n\n{text}\n\n"
            "Provide the following in professional bullet points:\n"
            "1. Business Model Summary\n"
            "2. Three specific operational friction points where AI automation could recover revenue.\n"
            "3. A Lead Score from 1-10 based on automation potential."
        )
        
        ai_response = model.generate_content(prompt)
        return ai_response.text
    except Exception as e:
        return f"Sentinel Data Retrieval Error: {str(e)}"

@app.route('/webhook', methods=['POST'])
def handle_lead():
    data = request.json
    website_url = data.get("website")
    
    if not website_url:
        return jsonify({"error": "No URL provided"}), 400

    # Execute Sentinel Logic
    analysis = analyze_lead(website_url)
    
    # Sync to Airtable
    sync_status = send_to_airtable(website_url, analysis)
    
    return jsonify({
        "status": "Sentinel Audit Complete",
        "analysis": analysis,
        "airtable_sync": sync_status
    }), 200

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
    return "Synced" if r.status_code == 200 else f"Sync Error: {r.text}"

if __name__ == "__main__":
    # Render uses the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
