"""Chat + tool-calling loop shared by the voice server and the scheduled tasks."""
import contextvars
import threading
import time


import tools
import toolguard

NUDGE = "Briefly tell me the result in one or two short sentences."
TOOL_TIMEOUT = 90       # seconds; a tool that takes longer is abandoned so the model can still answer


def call_tool(fn, args):
    """Runs a tool in a helper thread. Never raises, never blocks longer than TOOL_TIMEOUT.

    The thread gets a copy of the caller's context (contextvars), so a tool knows which turn it belongs to
    (where it came from, whether it may ask for approval...).
    """
    box = {}
    ctx = contextvars.copy_context()

    def work():
        try:
            box["out"] = ctx.run(fn, **(args if isinstance(args, dict) else {}))
        except Exception as e:
            box["out"] = f"Error: {e}"

    t = threading.Thread(target=work, daemon=True, name=f"tool-{getattr(fn, '__name__', 'fn')}")
    t.start()
    t.join(TOOL_TIMEOUT)
    if t.is_alive():
        return f"Error: the tool did not finish within {TOOL_TIMEOUT} s and was abandoned"
    return box["out"]


def _show_shots(messages, shots):
    """Pictures a tool made (screenshots) go to the model as a user message right after the tool results."""
    if shots:
        messages.append({"role": "user", "content": "(The screenshot from the tool above.)", "images": list(shots)})
        shots.clear()


def summarize(client, model, messages):
    """Asks for a short summary when the model finished with an empty reply."""
    try:
        res = client.chat(model=model, messages=messages + [{"role": "user", "content": NUDGE}])
        text = (res.message.content or "").strip()
    except Exception as e:
        text = f"Error: {e}"
    if text:
        messages.append({"role": "assistant", "content": text})
    return text


def _computer_turn():
    try:
        ctx = toolguard.current.get()
    except Exception:
        return False
    return bool(ctx and (ctx.get("computer_seen") or "computer" in ctx.get("grants", ())))


def _limit(max_turns):
    """Model rounds for this turn: more while the model is working the mouse and keyboard (one round per action)."""
    if _computer_turn():
        cfg = tools._hook("computer_cfg")() if tools._hook("computer_cfg") else {"max_actions": 30}
        return max(max_turns, int(cfg.get("max_actions", 30)) + 8)
    return max_turns


def _out_cap(name):
    return 10000 if name == "computer" else 4000          # the computer tool's key binding list is long


def run(client, model, think, tool_fns, messages, max_turns=6, timeout=None, extra_tools=()):
    """Runs the model until it stops calling tools. Mutates `messages`.

    Only functions listed in `tool_fns` can be executed, even if the model asks for another one.
    `extra_tools`: additional functions (e.g. the memory tools) that are offered to the model and allowed too.
    `timeout` (seconds) is checked between model calls. Returns (reply, thinking, used).
    """
    allowed = {n: fn for n, fn in tools.available_functions.items() if fn in tool_fns}
    for fn in extra_tools:
        allowed[fn.__name__] = fn
    offered = list(tool_fns) + list(extra_tools)
    deadline = time.monotonic() + timeout if timeout else None
    used, thinking_all = [], ""
    shots = []
    tools.shots.set(shots)

    rounds = 0
    while rounds < _limit(max_turns):
        rounds += 1
        if deadline and time.monotonic() > deadline:
            raise TimeoutError(f"exceeded the {timeout} s limit")
        res = client.chat(model=model, messages=messages, tools=offered or None, think=think)
        msg = res.message
        messages.append(msg)
        thinking_all = (msg.thinking or thinking_all).strip()

        if not msg.tool_calls:
            reply = (msg.content or "").strip()
            if not reply:
                print("[warn] empty reply, asking for a summary")
                reply = summarize(client, model, messages)
            return reply, thinking_all, used

        for call in msg.tool_calls:
            name = call.function.name
            args = call.function.arguments
            fn = allowed.get(name)
            if fn is None:
                out = f"Tool '{name}' is not enabled."
                toolguard.record(name, args, out, "not enabled", 0)
            else:
                out = toolguard.run(name, fn, args, call_tool)
            print(f"[tool] {name}({args}) -> {str(out)[:200]}")
            used.append({"name": name, "args": args, "output": str(out)[:1500]})
            messages.append({"role": "tool", "content": str(out)[:_out_cap(name)], "tool_name": name})
        _show_shots(messages, shots)

    print("[warn] tool loop limit reached")
    return summarize(client, model, messages), thinking_all, used


def run_stream(client, model, think, tool_fns, messages, on_event, cancel=None,
               max_turns=6, extra_tools=()):
    """Streaming version of run(): calls on_event(kind, data) while the model writes.

    kinds: "thinking" (text piece), "delta" (reply text piece), "tool" (dict with name/args/output),
           "reset" (the text streamed so far was a preamble before tool calls; the reply starts again).
    Stops early when `cancel` (threading.Event) is set. Mutates `messages`. Returns (reply, thinking, used).
    """
    allowed = {n: fn for n, fn in tools.available_functions.items() if fn in tool_fns}
    for fn in extra_tools:
        allowed[fn.__name__] = fn
    offered = list(tool_fns) + list(extra_tools)
    used, thinking_all = [], ""
    shots = []
    tools.shots.set(shots)

    rounds = 0
    while rounds < _limit(max_turns):
        rounds += 1
        content, thinking, calls = "", "", []
        stream = client.chat(model=model, messages=messages, tools=offered or None, stream=True, think=think)
        for chunk in stream:
            if cancel is not None and cancel.is_set():
                break
            m = chunk.message
            if getattr(m, "thinking", None):
                thinking += m.thinking
                on_event("thinking", m.thinking)
            if m.content:
                content += m.content
                on_event("delta", m.content)
            if m.tool_calls:
                calls.extend(m.tool_calls)
        thinking_all = (thinking or thinking_all).strip()
        stopped = cancel is not None and cancel.is_set()
        msg = {"role": "assistant", "content": content}
        if calls and not stopped:                       # a call that will never run must not stay in the history
            msg["tool_calls"] = calls
        messages.append(msg)

        if stopped:
            return content.strip(), thinking_all, used

        if not calls:
            reply = content.strip()
            if not reply:
                print("[warn] empty reply, asking for a summary")
                reply = summarize(client, model, messages)
                if reply:
                    on_event("delta", reply)
            return reply, thinking_all, used

        if content.strip():
            on_event("reset", None)                     # text before tool calls is not the answer
        for call in calls:
            name = call.function.name
            args = call.function.arguments
            fn = allowed.get(name)
            if fn is None:
                out = f"Tool '{name}' is not enabled."
                toolguard.record(name, args, out, "not enabled", 0)
            else:
                out = toolguard.run(name, fn, args, call_tool, cancel)
            print(f"[tool] {name}({args}) -> {str(out)[:200]}")
            item = {"name": name, "args": args, "output": str(out)[:1500]}
            used.append(item)
            on_event("tool", item)
            messages.append({"role": "tool", "content": str(out)[:_out_cap(name)], "tool_name": name})
            if cancel is not None and cancel.is_set():
                for rest in calls[calls.index(call) + 1:]:     # every call needs a result, or cloud APIs refuse the history
                    messages.append({"role": "tool", "content": "Not run: the user stopped the reply.",
                                     "tool_name": rest.function.name})
                return "", thinking_all, used
        _show_shots(messages, shots)

    print("[warn] tool loop limit reached")
    reply = summarize(client, model, messages)
    if reply:
        on_event("delta", reply)
    return reply, thinking_all, used
