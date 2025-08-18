
# nlp_model.py - Lightweight ML intent classifier (scikit-learn)
from typing import List, Tuple
import json
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

SEED_DATA = [
    ("where should i run today", "where_today"),
    ("where do i run tonight", "where_today"),
    ("what running location do i go to today", "which_location_today"),
    ("which location should i go today", "which_location_today"),
    ("where should i run tomorrow", "where_tomorrow"),
    ("recommend a run tomorrow morning", "where_tomorrow"),
    ("i am going to markham tomorrow where should i run", "where_tomorrow"),
    ("i will be in scarborough tomorrow evening where to run", "where_tomorrow"),
    ("what trail should i pick today", "where_today"),
    ("i need a running spot today afternoon", "where_today"),
]

def load_training_data(extra_path: str = "training_data.jsonl") -> List[Tuple[str,str]]:
    data = list(SEED_DATA)
    p = Path(extra_path)
    if p.exists():
        with p.open("r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if "text" in obj and "label" in obj:
                        data.append((obj["text"], obj["label"]))
                except Exception:
                    continue
    return data

def train_model(extra_path: str = "training_data.jsonl") -> Pipeline:
    data = load_training_data(extra_path)
    X = [t for (t, y) in data]
    y = [y for (t, y) in data]
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1,2), min_df=1)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipe.fit(X, y)
    return pipe

try:
    MODEL = train_model()
except Exception:
    MODEL = None

def predict_label(text: str) -> str:
    if MODEL is None:
        return "free_form"
    return MODEL.predict([text])[0]
