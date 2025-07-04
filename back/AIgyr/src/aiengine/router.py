from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .schemas import TrailDataInput, GearRecommendation, GearAndHikeResponse
from .knowledge_base import retrieve_gear
import openai
import os
from src.database import get_db
from src.posts.models import TrailData

router = APIRouter(prefix="/aiengine", tags=["AIEngine"])

# Create OpenAI client instance
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# @router.post("/gear-recommend", response_model=GearRecommendation)
# def gear_recommend(data: TrailDataInput):
#     # Retrieve context from knowledge base (RAG)
#     context_gear = retrieve_gear(data.trail_conditions, data.elevation_gain_meters, data.distance_meters)
#     context = f"Knowledge base gear: {', '.join(context_gear)}"

#     # OpenAI function calling schema
#     function_schema = {
#         "name": "recommend_gear",
#         "description": "Recommend hiking gear based on trail data.",
#         "parameters": {
#             "type": "object",
#             "properties": {
#                 "trail_conditions": {"type": "array", "items": {"type": "string"}},
#                 "elevation": {"type": "number"},
#                 "distance": {"type": "number"},
#                 "context_gear": {"type": "array", "items": {"type": "string"}},
#             },
#             "required": ["trail_conditions", "elevation", "distance", "context_gear"]
#         }
#     }

#     response = openai_client.chat.completions.create(
#         model="gpt-4-1106-preview",
#         messages=[
#             {"role": "system", "content": "You are a hiking gear expert."},
#             {"role": "user", "content": f"Trail data: {data.trail_conditions}, elevation: {data.elevation_gain_meters}, distance: {data.distance_meters}."},
#             {"role": "system", "content": context}
#         ],
#         tools=[function_schema],
#         tool_calls={"name": "recommend_gear"},
#         tool_choice="auto"
#     )
#     # Parse function call result
#     # In new SDK, function_call result is in response.choices[0].message.tool_calls[0].function.arguments
#     tool_calls = response.choices[0].message.tool_calls
#     if tool_calls and hasattr(tool_calls[0], "function"):
#         import json
#         function_args = json.loads(tool_calls[0].function.arguments)
#         recommendations = function_args.get("context_gear", context_gear)
#     else:
#         recommendations = context_gear
#     return {"recommendations": recommendations}

@router.get("/gear-and-hike-suggest", response_model=GearAndHikeResponse)
def gear_and_hike_suggest(db: Session = Depends(get_db)):
    # Fetch latest trail data
    trail = db.query(TrailData).order_by(TrailData.id.desc()).first()
    if not trail:
        raise HTTPException(status_code=404, detail="No trail data found")
    # Prepare data
    trail_conditions = trail.trail_conditions or []
    elevation = trail.elevation_gain_meters or 0
    distance = trail.distance_meters or 0
    coordinates = trail.coordinates or []
    # Retrieve context from knowledge base (RAG)
    context_gear = retrieve_gear(trail_conditions, elevation, distance)
    context = f"Knowledge base gear: {', '.join(context_gear)}"
    # OpenAI prompt for hike suggestions
    hike_prompt = f"""
    You are an expert hiking assistant. Based on the following trail data, provide 3 short, actionable hike tips or suggestions for a safe and enjoyable hike. Be specific and consider elevation, distance, and trail conditions.
    Trail Data:
    - Distance: {distance/1000:.1f} km
    - Elevation Gain: {elevation:.0f} m
    - Trail Conditions: {', '.join(trail_conditions)}
    - Coordinates: {coordinates[:2]} ... (total {len(coordinates)} points)
    Respond with a bullet-point list of tips only.
    """
    function_schema = {
        "name": "recommend_gear",
        "description": "Recommend hiking gear based on trail data.",
        "parameters": {
            "type": "object",
            "properties": {
                "trail_conditions": {"type": "array", "items": {"type": "string"}},
                "elevation": {"type": "number"},
                "distance": {"type": "number"},
                "context_gear": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["trail_conditions", "elevation", "distance", "context_gear"]
        }
    }
    gear_response = openai_client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": "You are a hiking gear expert."},
            {"role": "user", "content": f"Trail data: {trail_conditions}, elevation: {elevation}, distance: {distance}."},
            {"role": "system", "content": context}
        ],
        tools=[{"type": "function", "function": function_schema}],
        tool_choice={"type": "function", "function": {"name": "recommend_gear"}}
    )
    tool_calls = gear_response.choices[0].message.tool_calls
    if tool_calls and hasattr(tool_calls[0], "function"):
        import json
        gear_args = json.loads(tool_calls[0].function.arguments)
        gear = gear_args.get("context_gear", context_gear)
    else:
        gear = context_gear
    # Hike suggestion (prompt)
    hike_response = openai_client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": "You are a hiking assistant."},
            {"role": "user", "content": hike_prompt}
        ]
    )
    hike_text = hike_response.choices[0].message.content
    hike = [line.strip("-• ") for line in hike_text.split("\n") if line.strip("-• ")]
    return {"gear": gear, "hike": hike} 