import json
from typing import List
from .models import GeminiPlayerResult, GeminiRoundEvaluation

def parse_gemini_response(payload: str) -> GeminiRoundEvaluation:
    data = json.loads(payload)
    results_data = data.get("results", [])
    
    results = []
    for item in results_data:
        results.append(GeminiPlayerResult(
            user=item.get("user"),
            input=item.get("input"),
            score=item.get("score"),
            hint=item.get("hint"),
        ))
        
    return GeminiRoundEvaluation(results=results)
