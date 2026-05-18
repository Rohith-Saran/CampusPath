# CampusPath

Demo Flask app illustrating two CS concepts:

- Topological Sort (DFS-based) for course prerequisite ordering
- Mutex Locks (threading.Lock) to prevent race conditions during registration

Setup & run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000/ in your browser. Endpoints:

- `/` : demo UI
- `/demo` : run registration simulation WITHOUT mutex (JSON)
- `/demo-safe` : run simulation WITH mutex (JSON)
- `/courses` : returns topological course order and cycle flag (JSON)

All data is in-memory; no database required.
