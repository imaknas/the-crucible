# Features in detail

| Feature | What it does |
|---|---|
| **🌳 Conversation trees** | Every message is a checkpoint. Branch from any node, edit a question and re-ask it, and navigate the whole tree on a React Flow canvas. |
| **⚔️ Arena** | Send one prompt to several models. Each answers in parallel on its own branch of the tree, for side-by-side comparison. Models get no system prompt from the app, so you compare them as they ship; set your own in **Control Panel → System prompt** and every model (and debate participant) gets it. |
| **🗣️ Debate** | An argument explorer: two or more models argue over several rounds so you can see the strongest arguments and where they disagree. Round 1 is each model's independent answer; from then on each reads the others' previous answers, labelled *Participant A, B…* rather than by model name (so no model defers to a brand). The synthesis is an argument map — positions, their best arguments and evidence, who changed position and why, what is unresolved — not a verdict. Agreement reached by debating isn't evidence: for an answer to rely on, use Arena's independent answers and Synthesis. Stop early once answers stop changing or a judge finds the models now agree, pause between rounds, add a note mid-debate, or change the topic. |
| **⚖️ Deliberation** | Ask a model to critically review the thread so far, with every earlier message attributed to the model that wrote it. |
| **🤝 Synthesis** | Combine divergent answers into one, stating where the models agree and where they don't. |
| **📎 Documents & RAG** | Attach PDF, TXT, Markdown or CSV files (up to 10 MB). With *Search my documents* on, relevant passages are retrieved and graded before the model answers, with citations. |
| **🌐 Web search** | Let models that support it use their provider's native web-search tool. |
| **🧠 Context management** | When a thread outgrows a model's budget, older history is summarized (keeping who said what) instead of being cut off — and the summary is never the only copy: for each new question a small model picks which original messages it is about and shows them again. Choose the summarizer in **Control Panel → Summarizer**, or leave it on Automatic. |
| **🔬 Compaction research tools** | Measure what summarization loses on your own models (`crucible compaction-eval`), and re-check that every piece of context machinery still beats going without it whenever models change (`crucible scaffold-audit`). See [Research](../README.md#-research-what-survives-compaction). |
| **📐 LaTeX** | `$inline$` and `$$block$$` math rendered with KaTeX. |
| **⌨️ CLI & 🤖 MCP** | Everything the web UI does to a conversation — arenas, debates, syntheses, branching, search, uploads — from the terminal or from another agent, against the same database as the web UI. |
