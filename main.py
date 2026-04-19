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
    system_instruction="Analyze business data. Return strict JSON: company_name, analysis, score (1-5), pain_points."
)

@app.route('/webhook', methods=['POST'])
def analyze():
    data = request.json
    url = data.get("website")
    if not url: return jsonify({"error": "No URL"}), 400

    try:
        if not url.startswith('http'): url = 'https://' + url
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        for s in soup(["script", "style"]): s.decompose()
        text = soup.get_text(separator=' ').strip()[:8000]

        ai_response = model.generate_content(f"Analyze: {text}", generation_config={"response_mime_type": "application/json"})
        result = json.loads(ai_response.text)
        
        # Simple rounding for the rating field
        raw_score = float(result.get("score", 0))
        result["score"] = int(round(raw_score / 2 if raw_score > 5 else raw_score))
        
        return jsonify(result), 200 # Just return the data to Make
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
