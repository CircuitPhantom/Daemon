"""The conversation: the active chat, one turn of it (typed, spoken, from Signal, the phone or the laptop), and
everything a turn needs around it (attachments, files the model sends you, Signal commands).

server.py and the api_*.py routers call into this module; it never imports them.
"""
import asyncio
import base64
import io
import json
import os
import queue
import re
import threading
import time
import wave
from pathlib import Path

from fastapi.responses import StreamingResponse

import agent
import chats
import inbox
import interrupts
import jobs
import llm
import memstore
import model_config
import phone_bridge
import reminders
import scheduler
import signal_bot
import toolguard
import tools
import twilio_call
import uploads
import satellite
import voice
import wakeword
from interrupts import (RESUME_MAX_AGE, RESUME_TURNS, drop_pending, heard_reports, last_spoken, note_for_model, pending,
                        resume_text, turn_no)
from voice import strip_tags

client = llm.Client()                               # the cloud model (llm.py)
sched = scheduler.Scheduler(client)
jobs.init(client)                                   # background jobs (jobs.py)
rem = reminders.Reminders()

lock = threading.Lock()  # one turn at a time
rev = [0]                # bumped whenever the active chat changes, so open web pages can refresh
cur = None               # the active chat (dict from chats.py); None until the first message of a new chat
messages = []            # model context of the active chat; messages[0] is rebuilt every turn


# ── the active chat ──
def _desktop_hint():
    """One line when the computer tool can reach the laptop: the model then looks up its real key bindings instead of guessing."""
    try:
        if getattr(tools, "computer", None) not in model_config.available_tools or "screen_input" not in satellite.hub.tools:
            return ""
    except Exception:
        return ""
    desk = getattr(satellite.hub, "desktop", "")
    return (f"The user's laptop is connected{' (' + desk + ')' if desk else ''}. For any question about its keyboard shortcuts, "
            "and before doing things on its screen, call computer with action=shortcuts: it lists the real key bindings "
            "(no approval needed). Never answer from general desktop knowledge.")


def system_msg(speak=False):
    """System prompt + saved memory. A fresh dict, so tasks (which use model_config directly) never get memory."""
    content = model_config.system_prompt["content"]
    mem = memstore.prompt_block()
    desk = _desktop_hint()
    return {"role": "system", "content": content + ("\n\n" + desk if desk else "") + ("\n\n" + mem if mem else "") + ("\n\n" + voice.voice_block() if speak else "")}


def activate(chat):
    """Makes `chat` the active one and rebuilds the model context from it."""
    global cur
    cur = chat
    with interrupts.lock:
        pending.clear()
        last_spoken.clear()
    messages[:] = [system_msg()] + (chats.context_messages(chat) if chat else [])
    rev[0] += 1


def new_chat(title="", seed=None, run=None):
    activate(chats.new(title, seed, run))


try:
    activate(chats.latest())      # resume the most recent chat after a restart
except Exception as e:
    print("[chats] could not resume the last chat:", e)
    activate(None)


def role_of(m):
    return m["role"] if isinstance(m, dict) else m.role


def shrink_old_tool_output(keep_turns=2, max_chars=200):
    """Old tool results only eat context; keep the calls (the pattern) but cut their output."""
    seen = 0
    for m in reversed(messages):
        r = role_of(m)
        if r == "user":
            seen += 1
        elif r == "tool" and seen >= keep_turns and isinstance(m, dict):
            c = m.get("content")
            if isinstance(c, str) and len(c) > max_chars:
                m["content"] = c[:max_chars] + " …"


def trim_history(limit=30):
    shrink_old_tool_output()
    # keep the system message, trim the rest; always start from a 'user' message
    while len(messages) > limit + 1:
        del messages[1]
        while len(messages) > 1 and role_of(messages[1]) != "user":
            del messages[1]


def save_turn(user_text, reply, thinking, used, failed, files=None, out_files=None):
    try:
        chats.add_turn(cur, user_text, reply, thinking, used, error=failed, files=files, out_files=out_files)
        chats.save(cur)
    except Exception as e:
        print("[chats] could not save:", e)
    rev[0] += 1


# ── files the model sends you (tools.send_file) ──
INLINE_IMAGES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def _send_roots():
    return [Path(os.path.realpath(tools._files_dir())), Path(os.path.realpath(uploads.base_dir()))]


def resolve_send(file):
    """File name or path -> (real path, its root) inside the Daemon folder or the uploads folder, else (None, None)."""
    f = Path(str(file).strip()).expanduser()
    for root in _send_roots():
        for cand in ([f] if f.is_absolute() else [root / f]):
            real = Path(os.path.realpath(cand))
            if real.is_file() and root in real.parents:
                return real, root
    return None, None


def send_file(file, caption, where):
    """tools.send_file: a download card in the web chat the request came from, else a Signal attachment."""
    p, root = resolve_send(file)
    if p is None:
        return False, f"no such file inside {tools._files_dir()}"
    size = p.stat().st_size
    if size > signal_bot.MAX_SEND:
        return False, f"file is larger than {signal_bot.MAX_SEND // 1048576} MB"
    ctx = toolguard.current.get()
    name = p.name.split("-", 1)[1] if re.match(r"^[0-9a-f]{8,}-", p.name) else p.name
    if ctx and ctx.get("source") == "web" and ctx.get("emit") and where != "phone":
        files_root = Path(os.path.realpath(tools._files_dir()))
        if files_root in p.parents:
            rel, src = str(p.relative_to(files_root)), "files"
        else:
            rel, src = str(p.relative_to(root)), "uploads"
        meta = {"name": name, "kind": "image" if p.suffix.lower().lstrip(".") in INLINE_IMAGES else "other", "rel": rel,
                "size": size, "out": src}
        ctx["out"].append(meta)
        ctx["emit"]({"type": "files", "files": [meta], "caption": caption})
        return True, f"{name} is shown in the chat as a download."
    ok, info = signal_bot.bot.send_file(str(p), caption)
    return (True, f"{name} sent to the user's phone.") if ok else (False, info)


# ── one turn ──
def prepare_files(items):
    """[{"name", "data": base64}] or [(name, bytes)] -> (records, problems). Saves the files and reads what the model can use."""
    recs, problems = [], []
    for it in list(items or [])[: uploads.MAX_FILES]:
        try:
            if isinstance(it, dict):
                name, raw = it.get("name") or "file", base64.b64decode(str(it.get("data") or "").split(",")[-1], validate=False)
            else:
                name, raw = it
            recs.append(uploads.process(name, raw))
        except uploads.UploadError as e:
            problems.append(f"{(it.get('name') if isinstance(it, dict) else it[0]) or 'file'}: {e}")
        except Exception as e:
            problems.append(f"{(it.get('name') if isinstance(it, dict) else it[0]) or 'file'}: {type(e).__name__}")
    if len(items or []) > uploads.MAX_FILES:
        problems.append(f"only the first {uploads.MAX_FILES} files were used")
    return recs, problems


def model_sees():
    """Can the model look at pictures? (auto: by its name, or the uploads.vision switch)"""
    c = model_config.llm
    return uploads.model_sees(c["model"], "googleapis" in c["base_url"])


def turn_job(user_text, speak, emit, cancel, audio=None, lang="", attachments=None, problems=None, source="web"):
    """Runs one turn (optionally transcribing `audio` first) and reports progress through emit().

    source: where it came from (web, signal, phone, voice). It decides where a file the model sends shows up and how
    you are asked to approve a risky tool.
    """
    token = toolguard.current.set(None)
    try:
        _turn(user_text, speak, emit, cancel, audio, lang, attachments, problems, source)
    finally:
        toolguard.current.reset(token)


def _turn(user_text, speak, emit, cancel, audio, lang, attachments, problems, source):
    t_start = time.time()
    first = {}                                        # when the first words and the first audio were ready
    with lock:
        model_config.reload_if_changed()
        if audio is not None:
            user_text = voice.transcribe(audio, lang=lang)
            print("You:", user_text)
        ls = last_spoken
        if ls and ls["log"] and ls["turn"] not in heard_reports and time.time() < ls["log"][-1]["end"] + 1:
            for _ in range(8):                         # the last reply may still be playing: its "cut here" note is on the way
                if ls["turn"] in heard_reports:
                    break
                time.sleep(0.05)
        attachments = attachments or []
        resume = None if (cancel.is_set() or attachments) else resume_text(user_text, audio is not None)
        if (not user_text and not resume and not attachments and not problems) or cancel.is_set():
            emit({"type": "done", "user": "", "reply": "", "thinking": "", "tools": [], "rev": rev[0]})
            return
        shown_user = user_text or (", ".join(a["name"] for a in attachments) if attachments else "(go on)")
        turn_no[0] += 1
        my_turn = turn_no[0]
        files_meta = [uploads.public(a) for a in attachments]
        ctx = {"source": source, "emit": emit, "out": []}       # tools of this turn see it (toolguard.current)
        toolguard.current.set(ctx)                         # this thread runs only this turn
        emit({"type": "user", "text": shown_user, "turn": my_turn, **({"files": files_meta} if files_meta else {})})
        if cur is None:
            new_chat()
        messages[0] = system_msg(speak)
        model_text = shown_user
        if resume:
            old = pending.get("msg")                   # the cut reply now holds only what was actually said
            if isinstance(old, dict) and resume[1]["cut"] is not None:
                said = pending["reply"][: resume[1]["cut"]].rstrip()
                old["content"] = f"{said} —" if said else "—"
            print("[resume] going on from:", strip_tags(resume[1]["rest"])[:80])
            drop_pending()
        elif pending:
            if not pending.get("noted"):
                note = note_for_model(pending)
                if note:
                    model_text = f"({note})\n{shown_user}"
                pending["noted"] = True
            pending["turns"] += 1
            if pending["turns"] > RESUME_TURNS or time.time() - pending["at"] > RESUME_MAX_AGE:
                drop_pending()
        user_msg = {"role": "user", "content": model_text}
        if attachments or problems:
            sees = model_sees()
            parts = [user_text] if user_text else []
            parts += [uploads.block(a, sees) for a in attachments]
            parts += [f"[Could not use an attachment: {x}]" for x in problems or []]
            body = "\n\n".join(parts)
            if model_text != shown_user:                       # a note about an interrupted reply comes first
                body = model_text.split("\n", 1)[0] + "\n" + body
            user_msg["content"] = body
            imgs = [base64.b64encode(a["image"][0]).decode() for a in attachments if a.get("image")] if sees else []
            if imgs:
                user_msg["images"] = imgs
        messages.append(user_msg)
        trim_history()
        start = next(i for i, m in enumerate(messages) if m is user_msg)   # trim_history may have moved it

        speech_log, tagf = [], voice.TagFilter()
        tts_q = queue.Queue()
        tts_thread = None
        if speak:
            def tts_worker():
                synth, seq, carry, last = voice.LazyKokoro(), 0, "", False
                try:
                    while True:
                        piece = tts_q.get()
                        if piece is None and carry and not cancel.is_set():
                            piece, carry, last = carry, "", True        # an effect at the very end of the reply is still played
                            tts_q.put(None)
                        raw = piece
                        if piece is None or cancel.is_set():
                            return
                        speech = voice.clean_for_tts(piece)
                        if carry:
                            speech, carry = f"{carry} {speech}".strip(), ""
                        if not last and not re.search(r"\w", strip_tags(speech)):
                            carry = speech if voice.TAG_RE.search(speech) else ""   # a lone effect joins the next sentence
                            continue
                        if not speech:
                            continue
                        try:
                            data = voice.tts_wav(synth, speech, max_chunks=4)
                        except Exception as e:
                            print("[tts] error:", e)
                            continue
                        if data and not cancel.is_set():
                            first.setdefault("audio", time.time())
                            with wave.open(io.BytesIO(data)) as w:
                                dur = w.getnframes() / float(w.getframerate())
                            t0 = max(time.time(), speech_log[-1]["end"] if speech_log else 0.0)
                            speech_log.append({"seq": seq, "raw": raw, "text": strip_tags(raw), "start": t0, "end": t0 + dur})
                            emit({"type": "audio", "seq": seq, "turn": my_turn, "audio": base64.b64encode(data).decode()})
                            seq += 1
                finally:
                    synth.close()

            tts_thread = threading.Thread(target=tts_worker, daemon=True, name="tts")
            tts_thread.start()

        splitter = voice.SentenceSplitter()
        spoken = [0]

        def on_event(kind, data):
            if kind == "delta":
                first.setdefault("token", time.time())
                shown = tagf.feed(data)
                if shown:
                    emit({"type": "delta", "text": shown})
                if speak:
                    for piece in splitter.feed(data):
                        if spoken[0] < 12:          # do not read out very long answers
                            tts_q.put(piece)
                            spoken[0] += 1
            elif kind == "thinking":
                emit({"type": "thinking", "text": data})
            elif kind == "reset":
                splitter.reset()
                tagf.flush()
                emit({"type": "reset"})
            elif kind == "tool":
                emit({"type": "tool", **data})

        failed = False
        try:
            if resume:                                  # going on with the cut reply: no model call, same voice pipeline
                said = ""
                for chunk in re.findall(r"\S+\s*", resume[0]):
                    if cancel.is_set():
                        break
                    said += chunk
                    on_event("delta", chunk)
                reply, thinking, used = said.strip(), "", []
                messages.append({"role": "assistant", "content": reply})
            else:
                reply, thinking, used = agent.run_stream(
                    client, model_config.llm["model"], bool(model_config.think),
                    list(model_config.available_tools), messages, on_event, cancel,
                    extra_tools=memstore.tool_fns(),
                )
        except Exception as e:
            reply, thinking, used, failed = f"Error: {e}", "", [], True
            del messages[start:]
        complete = not cancel.is_set()
        for m in messages[start:]:                      # photos and screenshots were seen in this turn; they are not sent again with every later message
            if isinstance(m, dict) and m.get("images"):
                m.pop("images", None)
                if m is not user_msg:
                    m["content"] = "(a screenshot was shown here; it is not kept)"
        if cancel.is_set() and not failed:
            reply = (reply + " …").strip() if reply else "(stopped)"
        print("AI:", reply)
        t_llm = time.time()
        if speak:
            if not failed and spoken[0] < 12:
                for piece in splitter.flush():
                    tts_q.put(piece)
            tts_q.put(None)
            tts_thread.join(timeout=300)
        now = time.time()
        rel = lambda k: f"{first[k] - t_start:.1f} s" if k in first else "-"
        last_msg = messages[-1] if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "assistant" else None
        with interrupts.lock:
            if speak and not failed:
                last_spoken.clear()
                last_spoken.update(turn=my_turn, reply=reply.rstrip(" …").rstrip() if cancel.is_set() else reply,
                                   log=list(speech_log), complete=complete, msg=last_msg)
            if speak and not failed and (cancel.is_set() or spoken[0] >= 12):
                pending.clear()
                pending.update(turn=my_turn, reply=reply.rstrip(" …").rstrip() if cancel.is_set() else reply, log=list(speech_log),
                               when=(getattr(cancel, "when", None) or time.time()) if cancel.is_set() else 0.0,
                               heard=getattr(cancel, "heard", None), cancelled=cancel.is_set(), complete=complete,
                               at=time.time(), turns=0, noted=False, msg=last_msg)
                if cancel.is_set():
                    print("[interrupted] after", len(speech_log), "spoken pieces")
        reply_shown = strip_tags(reply)
        print(f"[timing] first words after {rel('token')}, first audio after {rel('audio')}, model done after {t_llm - t_start:.1f} s, "
              f"all done after {now - t_start:.1f} s (model: {model_config.llm['model']}, tools: {len(used)})")
        out_files = list(ctx["out"])
        save_turn(shown_user, reply_shown, thinking, used, failed, files=files_meta, out_files=out_files)
        if failed:
            emit({"type": "error", "message": reply, "rev": rev[0]})
        else:
            emit({"type": "done", "user": shown_user, "reply": reply_shown, "thinking": thinking, "tools": used, "rev": rev[0]})


def stream_job(job):
    out = queue.Queue()
    cancel = threading.Event()

    def runner():
        try:
            job(out.put, cancel)
        except Exception as e:
            out.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            out.put(None)

    threading.Thread(target=runner, daemon=True, name="turn").start()

    async def gen():
        try:
            while True:
                try:
                    ev = out.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.03)
                    continue
                if ev is None:
                    return
                yield (json.dumps(ev, ensure_ascii=False) + "\n").encode()
        finally:
            if not cancel.is_set():
                cancel.when = time.time()
            cancel.set()          # the page stopped listening (Stop button, new message, closed tab)

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── calls and Signal ──
def call_user(topic=""):
    """Rings you and starts a conversation. Returns (ok, info)."""
    if not twilio_call.configured():
        return False, "phone calls are not set up (notify.twilio_* in config.yaml)"
    if phone_bridge._busy.locked():
        return False, "a call is already in progress"
    topic = topic.strip().rstrip(".")
    greeting = f"Daemon here. {topic + '. ' if topic else 'You asked me to call. '}What can I do for you?"
    return twilio_call.place_talk_call(greeting)


CALL_ME = re.compile(r"^\s*(please\s+)?(call me|give me a call|ring me)\b[\s.!?]*$", re.I)


def signal_voice_to_text(data):
    """Bytes of a voice message -> text, with the same speech-to-text as the dashboard."""
    return voice.transcribe(voice.decode_audio_bytes(data), lang="")


SLASH = re.compile(r"^\s*/([^\W\d_]+)\b[ \t]*(.*)$", re.S)
HELP = """Commands (Signal):
/new                 start a new chat
/inbox <text>        save a note or link to the inbox (attach a photo or file to keep it too); alone: the latest items
/find <words>        search the inbox
/screen              send a picture of the laptop screen (asks for your OK first)
/job <what to do>    run something longer in the background; the result comes here (/jobs lists them, /job <id> shows one, /cancel <id> stops one)
/status              health of the server, laptop agent, backup, Tailscale
/memory              list what Daemon remembers, with ids
/forget <id>         remove one memory
/help                this list
Also: "call me" rings you. "yes" / "no" answers a tool that waits for your OK."""


def signal_screen():
    """/screen: asks for your OK like any screenshot, then sends the picture to this chat."""
    ctx = {"source": "signal", "emit": None, "out": []}
    token = toolguard.current.set(ctx)
    try:
        out = toolguard.run("screenshot", tools.available_functions["screenshot"], {}, agent.call_tool)
        m = re.search(r"File name: (\S+)", str(out))
        if not m:
            return str(out)[:300]
        ok, info = send_file(m.group(1), "Your screen", "")
        return "" if ok else f"The screenshot was taken but could not be sent: {info}"
    finally:
        toolguard.current.reset(token)


def signal_memory():
    rows = memstore.items()
    if not rows:
        return "The memory is empty."
    return f"Memory ({len(rows)}):\n" + "\n".join(f"[{x['id']}] {x['text'][:140]}" for x in rows[-40:]) + \
        ("\n(showing the newest 40)" if len(rows) > 40 else "") + "\n\nRemove one with: /forget <id>"


def signal_forget(arg):
    rid = arg.strip().strip("[]")
    if not rid:
        return "Usage: /forget <id>   (ids are shown by /memory)"
    try:
        memstore.delete(rid)
    except KeyError:
        return "No memory with that id."
    return "Forgotten."


def signal_slash(cmd, arg, files):
    """The commands that need no model. Returns the reply, or None when `cmd` is not one of them."""
    if cmd == "new":
        with lock:
            new_chat()
            rev[0] += 1
        return "Started a new chat."
    if cmd in ("help", "commands"):
        return HELP
    if cmd == "status":
        import monitor
        return monitor.report()
    if cmd in ("screen", "screenshot"):
        return signal_screen()
    if cmd == "job":
        return jobs.signal_job(arg)
    if cmd == "jobs":
        return jobs.signal_jobs()
    if cmd == "cancel":
        return jobs.signal_cancel(arg)
    if cmd == "memory":
        return signal_memory()
    if cmd == "forget":
        return signal_forget(arg)
    if cmd in ("inbox", "note", "find"):
        return signal_inbox("find" if cmd == "find" else "inbox", arg, files)
    return None


def signal_inbox(cmd, arg, files=None):
    if cmd == "find":
        if not arg:
            return "Usage: /find <words>"
        rows = inbox.search(arg, 6)
        return "\n".join(inbox.line(x, True) for x in rows) if rows else "Nothing in the inbox matches that."
    recs, problems = prepare_files(files) if files else ([], [])
    if not arg and not recs:
        rows = inbox.items(6)
        return ("Latest in the inbox:\n" + "\n".join(inbox.line(x) for x in rows)) if rows else "The inbox is empty. Send /inbox <text> (with a file or photo if you like)."
    try:
        x = inbox.add(arg, recs, src="signal")
    except ValueError:
        return "Not saved: " + ("; ".join(problems) or "nothing to save")
    return f"Saved to the inbox ({x['id']})." + (f" Skipped: {'; '.join(problems)}" if problems else "")


def signal_quick(text):
    """Answers that must not wait for the running turn (signal_bot calls this as soon as a message arrives): yes / no to
    a tool that is waiting for your approval. Returns the reply, or None when the message is a normal one."""
    return toolguard.answer_text(text)


def handle_signal(text, notice=None, files=None):
    """A message from you on Signal: runs one turn in the active chat and returns the reply text."""
    m = SLASH.match(text)
    if m:
        reply = signal_slash(m.group(1).lower(), m.group(2).strip(), files)
        if reply is not None:
            return reply or "(done)"
    if CALL_ME.match(text):                      # no need to ask the model
        ok, info = call_user()
        return "Calling you now." if ok else f"Could not call: {info}"
    if notice:
        text = f'(Re: "{notice}")\n{text}'
    box = {"reply": ""}

    def emit(ev):
        if ev.get("type") == "done":
            box["reply"] = ev.get("reply") or ""
        elif ev.get("type") == "error":
            box["reply"] = ev.get("message") or "Error"

    recs, problems = prepare_files(files) if files else ([], [])
    turn_job(text, False, emit, threading.Event(), attachments=recs, problems=problems, source="signal")
    return box["reply"] or "(no reply)"


# ── the wake word on this computer's microphone (wakeword.py); a laptop agent does this job instead when it is set up ──
wake = wakeword.WakeListener(
    transcribe=lambda audio, prompt: voice.transcribe(audio, prompt=prompt),
    run_turn=lambda text, emit, cancel: turn_job(text, True, emit, cancel, source="voice"),
)


def apply_wake():
    """The server's own microphone listener, unless a laptop agent does that job."""
    if satellite.enabled():
        wake.stop()
    else:
        wake.apply_config()


def wake_state():
    if satellite.enabled():
        h = satellite.hub.status()
        return {**wake.status(), "running": h["connected"], "error": "", "satellite": True, "name": h["name"]}
    return wake.status()
