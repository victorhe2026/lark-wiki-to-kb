"""Dev helper: serve the GUI backend for the demo wiki (no pywebview window)."""
import sys
from pathlib import Path
import uvicorn
sys.path.insert(0, str(Path(__file__).parent))
from llm_wiki.api import create_app
from llm_wiki.store import WikiProject

app = create_app(WikiProject(Path(__file__).parent / "demo"))
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
