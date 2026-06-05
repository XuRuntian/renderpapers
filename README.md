# 🔬 renderpapers

![renderpapers demo](readme.png)

Search real papers from your terminal and get beautiful HTML results you can read or copy-paste into ChatGPT/Claude.

Semantic Scholar is the default source, with arXiv kept as a compatibility source for arXiv-specific searches and direct arXiv IDs/URLs.

---

## 📥 Install

```bash
pip install git+https://github.com/XuRuntian/renderarxiv.git
```

That's it! This installs both `renderpapers` and the legacy `renderarxiv` command.

---

## 🚀 Use

```bash
renderpapers "transformer attention mechanism"
```

By default this searches Semantic Scholar. If you have an API key, set it first:

```bash
export SEMANTIC_SCHOLAR_API_KEY="your-key"
```

You can also put the same value in a local `.env` file. Opens a beautiful HTML page in your browser with:
- 👤 **Human view** — clean paper cards with abstracts, authors, PDF links
- 🤖 **LLM view** — formatted text ready to copy into AI assistants

---

## ⚙️ Options

**Choose a source:**
```bash
renderpapers "diffusion policy"                         # Semantic Scholar by default
renderpapers "diffusion policy" --source semantic-scholar
renderpapers "diffusion policy" --source arxiv
```

**Get more/fewer results:**
```bash
renderpapers "quantum computing" --max-results 15
```
**Filter by time**
```
renderpapers "machine learning" --days 30  # Only papers from the last 30 days
```
**Ranking modes:**
```bash
renderpapers "deep learning" --mode recent      # Newest papers
renderpapers "neural networks" --mode relevant  # Best text match
renderpapers "language models" --mode semantic  # Smart semantic matching
```

Default is `balanced` (mix of relevance + recency).

**Filter by category:**
```bash
renderpapers "object detection" --source arxiv --category cs.CV  # Exact arXiv category
renderpapers "optimization" --source arxiv --category math.OC    # Exact arXiv category
```

Common categories: `cs.LG` (ML), `cs.AI` (AI), `cs.CL` (NLP), `cs.CV` (Vision), `cs.RO` (Robotics)

**Save to file:**
```bash
renderpapers "diffusion models" -o papers.html --no-open
```

**Render a known arXiv paper directly:**
```bash
renderpapers 1706.03762
renderpapers https://arxiv.org/abs/1706.03762
```

**Cache and rate-limit handling:**
```bash
renderpapers "world model"                         # Uses a 24-hour local cache by default
renderpapers "world model" --no-cache              # Force a fresh source API request
renderpapers "world model" --retry-on-rate-limit   # Retry once after HTTP 429
renderpapers "world model" --cache-ttl-hours 6     # Keep cache entries fresh for 6 hours
```

---

## 💡 Examples

```bash
# Latest ML research
renderpapers "large language models" --source arxiv --category cs.LG --mode recent

# Find a specific paper
renderpapers "attention is all you need" --mode relevant

# Explore robotics
renderpapers "robot manipulation" --max-results 20

# Render by arXiv URL when search is rate-limited
renderpapers https://arxiv.org/abs/1706.03762 --no-open

# Deep semantic search
renderpapers "few-shot learning" --mode semantic

# Get the latest Computer Vision papers from the past 7 days
renderpapers "object detection" --source arxiv --category cs.CV --days 7 --mode recent
```

---

## 🎯 Pro Tip

1. Search for papers: `renderpapers "your topic" --max-results 10`
2. Click the **🤖 LLM** button in your browser
3. Copy the text (Ctrl+A, Ctrl+C)
4. Paste into ChatGPT/Claude: *"Summarize these papers and identify key trends"*

Now your AI has real citations, not hallucinations!

---

## 📚 Full Category List

**Computer Science:**
- `cs.AI` — Artificial Intelligence
- `cs.CL` — Natural Language Processing
- `cs.CV` — Computer Vision
- `cs.LG` — Machine Learning
- `cs.RO` — Robotics
- `cs.CR` — Security
- `cs.SE` — Software Engineering

**Math/Stats:**
- `math.OC` — Optimization
- `stat.ML` — Statistics/ML

**Physics:**
- `quant-ph` — Quantum Physics

Full list: https://arxiv.org/category_taxonomy

---

## 🤔 Why use this?

- ✅ No hallucinated papers
- ✅ Direct PDF download links
- ✅ Beautiful, readable output
- ✅ LLM-ready formatted text
- ✅ Fast Semantic Scholar search with arXiv compatibility
- ✅ Filter by research area when using arXiv categories
- ✅ Multiple ranking modes

---

## 🛠️ Development

```bash
git clone https://github.com/peterdunson/renderarxiv.git
cd renderarxiv
pip install -e .
# Both commands are installed; renderpapers is the preferred name.
renderpapers "diffusion policy"
```

---

## 📄 License

MIT © 2025

---

## 🙏 Inspired by

- [rendergit](https://github.com/karpathy/rendergit) by Andrej Karpathy
- [renderscholar](https://github.com/peterdunson/renderscholar)
- [renderstack](https://github.com/peterdunson/renderstack)
