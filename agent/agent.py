"""
JARVIS Agent
------------
LangGraph ReAct agent with:
  - Slash command interception (/flashcards, /feynman, /outline, /quiz, /plugin...)
  - Dynamic plugin registry (hot-load at runtime)
  - Memory-augmented context injection
  - Structured logging
"""



import uuid
from typing import Optional

from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from config.settings import settings
from memory.memory_manager import Memory
from tools.tools import ALL_TOOLS
from tools.plugin_registry import PluginRegistry
from agent.slash_commands import handle_slash_command, CommandResult
from logger import get_logger

log = get_logger(__name__)


def _build_llm():
    """Primary LLM — used for normal chat (local, fast, free)."""
    if settings.llm_backend == "ollama":
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.temperature,
            num_ctx=settings.context_window,
        )
    elif settings.llm_backend == "hailo":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=f"{settings.llm_base_url}/v1",
            api_key="none",
            model=settings.llm_model,
            temperature=settings.temperature,
        )
    raise ValueError(f"Unknown LLM backend: {settings.llm_backend}")


def _build_tool_llm():
    """
    Tool-calling LLM — used by the ReAct agent when tools are available.
    Falls back to local LLM if no Anthropic key is set.
    Claude is dramatically more reliable at tool calling than small local models.
    """
    if settings.anthropic_api_key:
        log.info("tool_llm", backend="claude", model="claude-haiku-4-5-20251001")
        return ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=settings.anthropic_api_key,
            temperature=0,
            max_tokens=4096,
        )
    log.warning("tool_llm_fallback", reason="no ANTHROPIC_API_KEY", backend=settings.llm_backend)
    if settings.llm_backend == "hailo":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=f"{settings.llm_base_url}/v1",
            api_key="none",
            model=settings.llm_model,
            temperature=0,
        )
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        temperature=0,
        num_ctx=settings.context_window,
    )

def _bind_memory_tools(memory: Memory, tools: list) -> list:
    """Replace stub remember_fact / ingest_document with real memory-wired versions."""
    from langchain_core.tools import tool as lc_tool
    from typing import Annotated

    @lc_tool
    def remember_fact(
        category: Annotated[str, "Category label, e.g. 'current_projects', 'user_goals'"],
        fact: Annotated[str, "The fact or summary to store"],
    ) -> str:
        """Store a long-term fact about the user that should persist across all future sessions."""
        memory.learn(category, fact)
        return f"Stored under '{category}': {fact[:80]}"

    @lc_tool
    def ingest_document(
        path: Annotated[str, "Absolute or ~ path to a .txt .md .py .json .csv or .pdf file"],
    ) -> str:
        """Ingest a document into the knowledge base so it can be recalled in future conversations."""
        try:
            n = memory.ingest(path)
            return f"Ingested {n} chunks from {path}"
        except Exception as e:
            return f"Ingest failed: {e}"

    real_tools = [t for t in tools if t.name not in {"remember_fact", "ingest_document"}]
    return real_tools + [remember_fact, ingest_document]


class JarvisAgent:
    def __init__(self):
        self.memory = Memory()
        self.llm = _build_llm()           # local — normal chat
        self.tool_llm = _build_tool_llm()  # Claude — tool calling
        self.checkpointer = MemorySaver()

        base_tools = _bind_memory_tools(self.memory, ALL_TOOLS)
        self.plugin_registry = PluginRegistry(base_tools=base_tools)
        self._rebuild_graph()

        stats = self.memory.stats()
        plugin_info = self.plugin_registry.list_plugins()
        log.info(
            "agent_ready",
            model=settings.llm_model,
            knowledge_chunks=stats["knowledge_chunks"],
            plugins_loaded=len(plugin_info["loaded"]),
        )
        print(
            f"✅ JARVIS online — model: {settings.llm_model} | "
            f"chunks: {stats['knowledge_chunks']} | "
            f"plugins: {len(plugin_info['loaded'])}"
        )

    def _rebuild_graph(self):
        """Rebuild the LangGraph agent with the current tool set. Call after plugin approval."""
        from langchain_core.messages import SystemMessage as SM
        # Explicit tool-use directive — prevents Claude from using training knowledge
        # instead of actually calling tools
        tool_system = (
            "You are JARVIS, a personal AI assistant. "
            "Be concise and helpful. "
            "Only use tools when the user explicitly needs real-time data like files, weather, or web search. "
            "For greetings and general questions, just respond naturally."
        )
        self.graph = create_react_agent(
            model=self.tool_llm,
            tools=self.plugin_registry.get_all_tools() if settings.llm_backend != "hailo" else [],
            checkpointer=self.checkpointer,
            prompt=tool_system,
        )

    def chat(self, message: str, session_id: Optional[str] = None) -> str:
        session_id = session_id or str(uuid.uuid4())
        log.debug("chat_start", session_id=session_id, msg=message[:60])

        # ── Slash command interception ─────────────────────────────────────────
        cmd_result: CommandResult | None = handle_slash_command(message, self.memory)
        if cmd_result:
            if cmd_result.bypass_llm:
                return cmd_result.pre_response
            # Slash commands use direct LLM — no tool calling, just plain generation
            prefix = (cmd_result.pre_response + "\n\n") if cmd_result.pre_response else ""
            return prefix + self._llm_direct(cmd_result.prompt)
        else:
            prefix = ""

        # ── /plugin meta-commands ─────────────────────────────────────────────
        plugin_resp = self._handle_plugin_meta(message)
        if plugin_resp is not None:
            return plugin_resp

        # ── Build context-enriched prompt ─────────────────────────────────────
        # Note: system prompt is injected via state_modifier in the graph.
        # We prepend memory context directly into the user message to avoid
        # multiple system messages (which Claude's API rejects).
        memory_context = self.memory.recall(message, session_id)

        history = self.memory.episodic.get_history(session_id, last_n=10)
        messages = []
        for h in history:
            cls = HumanMessage if h["role"] == "user" else AIMessage
            messages.append(cls(content=h["content"]))

        # Prepend memory context to the current message if available
        if memory_context:
            full_message = f"[Context from memory]\n{memory_context}\n\n[User message]\n{message}"
        else:
            full_message = message
        messages.append(HumanMessage(content=full_message))

        config = RunnableConfig(
            configurable={"thread_id": session_id},
            recursion_limit=settings.max_iterations * 2,
        )

        try:
            result = self.graph.invoke({"messages": messages}, config=config)
            response = result["messages"][-1].content
        except Exception as e:
            log.error("agent_error", session_id=session_id, error=str(e))
            response = f"I encountered an error: {e}"

        self.memory.remember(session_id, "user", message)
        self.memory.remember(session_id, "assistant", response)
        log.debug("chat_done", session_id=session_id, resp=response[:80])
        return prefix + response

    def _llm_direct(self, prompt: str) -> str:
        """Call the LLM directly without any tools — for slash command responses."""
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            log.error("llm_direct_error", error=str(e))
            return f"Error generating response: {e}"

    def _handle_plugin_meta(self, message: str) -> Optional[str]:
        """Handle /plugin approve|reject|list|request|code commands."""
        msg = message.strip()
        if not msg.startswith("/plugin"):
            return None

        parts = msg.split(None, 2)
        sub = parts[1].lower() if len(parts) > 1 else ""
        arg = parts[2].strip() if len(parts) > 2 else ""

        if sub == "approve" and arg:
            result = self.plugin_registry.approve_plugin(arg)
            if result.get("status") in ("approved", "already_approved"):
                self._rebuild_graph()
            return result.get("message") or result.get("error") or str(result)

        if sub == "reject" and arg:
            self.plugin_registry.reject_plugin(arg)
            return f"❌ Plugin `{arg}` rejected and discarded."

        if sub == "list":
            info = self.plugin_registry.list_plugins()
            lines = ["**Plugin Status:**"]
            if info["loaded"]:
                lines.append(f"✅ Loaded: {', '.join(info['loaded'])}")
            if info["pending"]:
                lines.append(f"⏳ Pending review: {', '.join(info['pending'])}")
            if not info["loaded"] and not info["pending"]:
                lines.append("No plugins installed yet.")
            return "\n".join(lines)

        if sub == "code" and arg:
            code = self.plugin_registry.get_pending_code(arg)
            return f"```python\n{code}\n```" if code else f"No pending plugin named `{arg}`."

        if sub == "request" and arg:
            try:
                result = self.plugin_registry.request_plugin(arg)
                return f"{result['message']}\n\n```python\n{result['code']}\n```"
            except ValueError as e:
                return f"❌ {e}"
            except Exception as e:
                return f"❌ Plugin generation failed: {e}"

        return None

    def ingest(self, path: str) -> str:
        from pathlib import Path
        p = Path(path).expanduser().resolve()
        supported = {".txt", ".md", ".py", ".rst", ".csv", ".json", ".pdf"}

        if p.is_dir():
            results = []
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in supported:
                    try:
                        n = self.memory.ingest(str(f))
                        results.append(f"✅ {f.name} ({n} chunks)")
                    except Exception as e:
                        results.append(f"❌ {f.name}: {e}")
            log.info("batch_ingest_done", path=str(p), files=len(results))
            return "\n".join(results)

        n = self.memory.ingest(str(p))
        log.info("ingest_done", path=str(p), chunks=n)
        return f"✅ Ingested {p.name} → {n} chunks"

    def stats(self) -> dict:
        return {
            **self.memory.stats(),
            "plugins": self.plugin_registry.list_plugins(),
        }
