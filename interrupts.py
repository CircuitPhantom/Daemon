"""Interrupted replies: what you heard when you cut a spoken reply off, and going on from there.

When you cut a spoken reply off, Daemon remembers exactly what you heard (the page and the phone report how far the
audio got; otherwise it is worked out from when each sentence started playing). Then:
  "continue" / "go on" / "devam et"  -> the rest is spoken again from the start of the cut sentence, no model call
  "mm-hmm", "okay", a cough or noise right after it -> the same, you just keep listening
  anything else -> the model answers, and is told what you heard and what you missed. "continue" later still works
Very long answers (only the first 12 sentences are read out) can be continued the same way.
"""
import re
import threading
import time

from voice import strip_tags

pending = {}                    # the interrupted reply (see note_for_model / resume_text)
last_spoken = {}                # the last spoken reply, in case it is cut off after the server already sent all of it
heard_reports = {}              # turn number -> (clip seq, seconds into it), sent by the web page
turn_no = [0]
lock = threading.RLock()        # pending is changed by the turn and by the page's "heard" report at the same time
RESUME_TURNS, RESUME_MAX_AGE, BACKCHANNEL_AGE = 2, 900, 90

CONTINUE = re.compile(
    r"^\W*(?:(?:ok(?:ay)?|yes|yeah|sorry|alright|tamam|evet|pardon)\W+)*(?:please\W+)?"
    r"(?:continue|go on|keep going|carry on|go ahead|proceed|resume|you were saying|as you were saying|where were we|"
    r"finish(?: it| that| what you were saying)?|devam(?: et| edebilirsin| edin)?|kaldığın yerden(?: devam et)?|sen devam et)"
    r"(?:\W+(?:please|then|from there|where you (?:left off|were|stopped)|lütfen))*\W*$", re.I)
BACKCHANNEL = re.compile(
    r"^\W*(?:uh[- ]?huh|mhm+|mm+(?:[- ]?hmm+)?|hmm+|yeah|yes|yep|ok(?:ay)?|right|sure|i see|got it|cool|nice|go|"
    r"evet|tamam|hı ?hı|anladım|he)\W*$", re.I)


def _word_cut(text, frac):
    words = text.split()
    return " ".join(words[: int(len(words) * max(0.0, min(1.0, frac)))])


def _sentence_cut(raw, frac):
    """Where to go on inside one spoken piece (it can hold several sentences): the start of the sentence that was
    playing, or the next one when that sentence was nearly finished."""
    if frac <= 0:
        return 0
    bounds = [0] + [m.end() for m in re.finditer(r"[.!?…]+[\])\"']*\s+", raw)] + [len(raw)]
    at = frac * len(raw)
    for a, b in zip(bounds, bounds[1:]):
        if at < b:
            return b if at >= a + 0.85 * (b - a) else a
    return len(raw)


def _split(p):
    """Where the user stopped listening: heard text, the rest (from the start of the cut sentence), cut position."""
    reply, log = p["reply"], p["log"]
    rep = heard_reports.get(p["turn"]) or p.get("heard")
    k, frac = len(log), 0.0
    if rep is not None:
        hs, off = rep
        for i, e in enumerate(log):
            if e["seq"] >= hs:
                k = i
                if e["seq"] == hs:
                    frac = off / max(0.2, e["end"] - e["start"])
                break
    elif p["when"]:
        for i, e in enumerate(log):
            if e["end"] > p["when"]:
                k, frac = i, (p["when"] - e["start"]) / max(0.2, e["end"] - e["start"])
                break
    low, pos, starts = reply.lower(), 0, []
    for e in log:                                   # where each spoken piece sits in the reply text
        i = low.find(e["raw"].lower(), pos)
        if i < 0:
            starts = None
            break
        starts.append(i)
        pos = i + len(e["raw"])
    heard = " ".join(e["text"] for e in log[:k])
    part = _word_cut(log[k]["text"], frac) if k < len(log) and frac > 0 else ""
    if part:
        heard = f"{heard} {part} …".strip()
    if starts is None:
        cut = None
    elif k < len(log):
        cut = starts[k] + _sentence_cut(log[k]["raw"], frac)
    else:
        cut = pos if log else 0
    rest = reply[cut:].strip() if cut is not None else ""
    return {"heard": strip_tags(heard).strip(), "rest": rest, "cut": cut}


def note_for_model(p):
    sp = _split(p)
    rest = strip_tags(sp["rest"]).strip()
    if not p["cancelled"]:
        return (f'Your previous answer was long, so only part of it was read out. The rest, not heard yet: "{rest[:600]}" '
                "If the user asks for it, go on from there.") if rest else ""
    if not sp["heard"]:
        note = "The user interrupted your previous reply before they heard any of it."
    else:
        note = f'The user interrupted your previous reply while you were speaking. They heard: "{sp["heard"][-500:]}"'
    if not p["complete"]:
        note += " Your reply was cut off while you were still writing it."
    if rest:
        note += f' They did NOT hear the rest, from: "{rest[:600]}"'
    return note + " Answer what they say now; if they want you to continue, go on from where they stopped listening."


def resume_text(user_text, audio_turn):
    """The words to speak again when the user only wants you to go on (None = ask the model as usual)."""
    p = pending
    t = (user_text or "").strip()
    asked = bool(CONTINUE.match(t))
    why = ("nothing was cut off (the last reply was heard to the end)" if not p else
           "the reply was cut while the model was still writing it, so the model goes on" if not p["complete"] else
           "too long ago" if time.time() - p["at"] > RESUME_MAX_AGE or p["turns"] > RESUME_TURNS else "")
    if why:
        if asked:
            print("[resume] not replaying:", why)
        return None
    if CONTINUE.match(t):
        pass
    elif p["turns"] == 0 and p["cancelled"] and time.time() - p["at"] < BACKCHANNEL_AGE and (not t or BACKCHANNEL.match(t)):
        pass                                        # "mm-hmm" / noise right after the cut: just go on
    else:
        return None
    sp = _split(p)
    if not re.search(r"\w", strip_tags(sp["rest"])):
        if asked:
            print("[resume] not replaying:", "everything was already heard" if sp["cut"] is not None
                  else "could not find the cut sentence in the reply")
        return None
    lead = "So, as I was saying: " if p["turns"] else ""
    return lead + sp["rest"], sp


def drop_pending():
    pending.clear()


def mark_heard(turn, seq, offset):
    """The page or the phone says the voice was cut at clip `seq`, `offset` seconds in. Usually the reply was still
    playing after the server had sent all of it, so the turn itself never saw a cancel: make it pending here."""
    with lock:
        heard_reports[turn] = (seq, max(0.0, min(float(offset), 600.0)))
        for k in sorted(heard_reports)[:-20]:
            heard_reports.pop(k, None)
        ls = dict(last_spoken)
        if not ls or ls.get("turn") != turn or pending.get("turn") == turn:
            return
        p = dict(ls, cancelled=True, heard=heard_reports[turn], when=time.time(), at=time.time(), turns=0, noted=False)
        if re.search(r"\w", strip_tags(_split(p)["rest"])):
            pending.clear()
            pending.update(p)
            print(f"[interrupted] while playing piece {seq + 1} of {len(ls['log'])}")
