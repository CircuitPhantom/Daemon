from types import SimpleNamespace as N
import time
class ResponseError(Exception): pass
SEEN = []
OPTS = []
DELAY = [0]
def _msg(content="", thinking="", tool_calls=None):
    return N(message=N(content=content, thinking=thinking, tool_calls=tool_calls, role="assistant"))
class Client:
    def list(self): return N(models=[N(model="qwen3:1.7b")])
    def chat(self, model, messages, tools=None, think=None, stream=False, options=None):
        OPTS.append(options)
        SEEN.append({"system": messages[0]["content"], "tools": [t.__name__ for t in (tools or [])], "n": len(messages), "think": think, "last": dict(messages[-1]) if isinstance(messages[-1], dict) else messages[-1], "all": [dict(m) if isinstance(m, dict) else m for m in messages]})
        last = messages[-1]
        role = last["role"] if isinstance(last, dict) else last.role
        content = last["content"] if isinstance(last, dict) else last.content
        if role == "user" and content.startswith("remember:"):
            call = N(function=N(name="remember", arguments={"fact": content[9:].strip()}))
            parts = [_msg("Let me save that. "), _msg(tool_calls=[call])]
        elif role == "user" and content.startswith("sendfile:"):
            parts = [_msg("Sending. "), _msg(tool_calls=[N(function=N(name="send_file", arguments={k: v for k, v in (kv.split("=", 1) for kv in content[9:].split(";") if "=" in kv)}))])]
        elif role == "user" and content.startswith("shot:"):
            parts = [_msg(tool_calls=[N(function=N(name="screenshot", arguments={}))])]
        elif role == "user" and content.startswith("runcmd:"):
            parts = [_msg(tool_calls=[N(function=N(name="execute_command", arguments={"cmnd": content[7:].strip()}))])]
        elif role == "user" and content.startswith("inboxadd:"):
            parts = [_msg(tool_calls=[N(function=N(name="inbox_add", arguments={"text": content[9:].strip()}))])]
        elif role == "user" and content.startswith("inboxfind:"):
            parts = [_msg(tool_calls=[N(function=N(name="inbox_search", arguments={"query": content[10:].strip()}))])]
        elif role == "tool":
            parts = [_msg("Got it.")]
        elif content == "nothink" and think:
            raise ResponseError("model does not support thinking")
        elif content.startswith("long"):
            parts = [_msg(thinking="hmm ")] + [_msg(w + " ") for w in ("First sentence is here. Second one follows now! And a third, with a code block: ```x = 1. y = 2.``` then the end.").split(" ")]
        elif content.startswith("verylong"):
            parts = [_msg(f"This is sentence number {i} of a very long answer that keeps on going for a while. ") for i in range(1, 17)]
        elif content.startswith("tagend"):
            parts = [_msg(x) for x in ("That is honestly the funniest thing I heard today. ", "[laughing]")]
        elif content.startswith("tagtest"):
            parts = [_msg(x) for x in ("Ha ha. [lau", "ghing] That was funny. Now the second sentence follows here. ", "And a third one comes after it. [sighing] The end.")]
        else:
            parts = [_msg("reply "), _msg("to: " + content[:40])]
        if not stream:
            return _msg("".join(p.message.content for p in parts), "", next((p.message.tool_calls for p in parts if p.message.tool_calls), None))
        def gen():
            for p in parts:
                if DELAY[0]: time.sleep(DELAY[0])
                yield p
        return gen()

# The tests use this fake as the cloud model: llm.Client sends everything to llm.CLOUD.
import llm as _llm
_llm.CLOUD = Client()
_llm.configured = lambda: True
_llm._sees_images = lambda: True
