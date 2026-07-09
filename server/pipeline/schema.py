CATEGORIES = [
    "CRM", "Helpdesk", "Chat/Comms", "Ads/Marketing", "E-commerce",
    "Data/Scraping", "Dev Infra", "PM/Productivity", "Fintech", "Other",
]

AUTH_METHODS = ["OAuth2", "API key", "Basic", "token", "other"]

ACCESS_MODELS = [
    "self_serve_free", "self_serve_trial", "paid_plan_required",
    "partnership_gated", "unclear",
]

VERDICTS = ["ready_today", "possible_with_workaround", "blocked"]

CONFIDENCE = ["low", "medium", "high"]

RESEARCH_SCHEMA = {
    "name": "app_toolkit_research",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "category": {"type": "string", "enum": CATEGORIES},
            "one_line_description": {"type": "string"},
            "auth_methods": {
                "type": "array",
                "items": {"type": "string", "enum": AUTH_METHODS},
            },
            "access_model": {"type": "string", "enum": ACCESS_MODELS},
            "api_surface": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "api_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["REST", "GraphQL", "SOAP", "gRPC", "other", "none_public"]},
                    },
                    "breadth": {"type": "string", "enum": ["narrow", "moderate", "broad", "unknown"]},
                    "notes": {"type": "string"},
                },
                "required": ["api_types", "breadth", "notes"],
            },
            "has_existing_mcp": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "exists": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["exists", "note"],
            },
            "buildability_verdict": {"type": "string", "enum": VERDICTS},
            "blocker_if_any": {"type": ["string", "null"]},
            "evidence_url": {"type": "string"},
            "confidence": {"type": "string", "enum": CONFIDENCE},
            "raw_notes": {"type": "string"},
        },
        "required": [
            "category", "one_line_description", "auth_methods", "access_model",
            "api_surface", "has_existing_mcp", "buildability_verdict",
            "blocker_if_any", "evidence_url", "confidence", "raw_notes",
        ],
    },
}
