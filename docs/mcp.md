# MCP server

The Crucible can act as a tool for other agents over the [Model Context Protocol](https://modelcontextprotocol.io). Add it to your client's MCP settings (for Claude Desktop, `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "the-crucible": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/the-crucible/backend", "run", "python", "app/mcp_server.py"],
      "env": {
        "OPENAI_API_KEY": "your-key",
        "ANTHROPIC_API_KEY": "your-key",
        "GOOGLE_API_KEY": "your-key"
      }
    }
  }
}
```

Everything the web UI does to a conversation is a tool, except writing API keys (a key passed to a tool would go through the calling model's context; use `crucible keys` or the environment). All tools return structured JSON and raise an MCP error on failure. An answer always has the same shape (`model`, `model_name`, `content`, `checkpoint_id`, `error`), and every checkpoint id is a node of the conversation tree, so an id from any tool works with every other.

| Tool | Purpose |
|---|---|
| **Turns & synthesis** | |
| `invoke_arena` | Ask one or more models the same message in parallel: a chat turn (one model, `synthesize=false`), an arena turn with a synthesis, or a Deliberation (`deliberation=true`). Continues a thread (`thread_id`), branches from a node (`parent_checkpoint_id`) or from a finished debate (`after_debate_session_id`); takes `attachments` (local files), `use_rag`, `use_web_search`, `system_prompt` and `summarizer` |
| `synthesize_answers` | Combine answers already on a thread into one: by default every model's answer to the latest question, or exactly the `checkpoint_ids` given |
| **Debates** | |
| `run_debate` | Multi-round debate between two or more models (anonymous to each other unless `peer_labels="named"`), with optional early stopping (stability or a judge's agreement) and a final argument map. Can start from a node of an existing thread (`parent_checkpoint_id`); takes `attachments`, `use_rag`, `use_web_search`, `system_prompt` and `summarizer` |
| `continue_debate` | More rounds of a stopped debate, optionally injecting messages into the next round |
| `redirect_debate` | Put a new question to a debate; each model keeps what it said |
| `synthesize_debate` | Write (or rewrite) a debate's argument map from every round |
| `list_debates`, `get_debate` | Find debates, and read one aligned by round (`rounds_from` and `max_chars` keep it short) |
| `delete_debate` | Delete a debate and its lanes |
| **Threads & history** | |
| `list_threads`, `rename_thread`, `delete_thread` | Find, rename or delete threads |
| `get_thread_tree` | The conversation tree: every node with its checkpoint id, parent, model, kind and turn |
| `get_thread_messages` | Read one path of a thread; pass a `checkpoint_id` to read one model's branch |
| `search_thread` | Find messages on every branch of a thread |
| `delete_branch` | Delete a node and everything below it |
| `get_branch_answers` | The latest answer on every branch of a thread |
| `get_thread_status`, `get_thread_summary` | A thread's title, latest model and message count, latest answer and context summary |
| **Documents** | |
| `upload_document` | Upload a local file to a thread for `use_rag` searches |
| **Models** | |
| `list_models` | Model IDs, whether each has an API key, web-search support, context window and today's price |

The conversation tree's topology (checkpoints and their parent links) is also available over REST: `GET /graph/{thread_id}/topology`.
