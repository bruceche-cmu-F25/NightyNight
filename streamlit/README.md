# Streamlit Frontend (Research Assistant)

This app provides:
- paper upload (domain + language metadata)
- multilingual research queries
- grounded answer view with recommendations

## Run locally

1. Set backend URL:
	- `export MCP_CLIENT_API_URL=http://localhost:8000`
2. Start Streamlit:
	- `cd streamlit`
	- `streamlit run app.py`

The app expects LangGraph API endpoints:
- `POST /upload`
- `POST /query`