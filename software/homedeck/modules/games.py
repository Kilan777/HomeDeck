"""Games: Alexa-style voice games and kid stuff, mirrored on the screen.

Voice: dice, coin, jokes, riddles, trivia (Open Trivia DB), math quiz, times tables, spelling bee, animal sounds,
stories (from the language model), would-you-rather, magic 8 ball, rock paper scissors. While a game waits for an
answer the voice module keeps listening (follow_up) so no wake word is needed. Touch games (tic-tac-toe, memory,
Simon) live entirely in web/apps/games.js; high scores are stored in config games.scores through api "score".

state(): {active, kind, prompt, options, score, round, total, expires, last: {...}, scores}
events: "game" (state changed, data = a copy of the visible state), "game_open" (a voice game started)
"""
import html, json, random, re, threading, time, urllib.request

NAME = "games"
DEFAULTS = {"scores": {}, "trivia_round": 5, "answer_window_s": 20}
UA = "HomeDeck/1.0"

ctx = None
_lock = threading.Lock()
_g = {"active": None, "kind": None, "prompt": "", "options": [], "answer": None, "accept": [], "score": 0, "round": 0,
      "total": 0, "expires": 0.0, "last": None, "extra": {}, "story": None}
_trivia_cache = {"general": [], "easy": []}

JOKES = [
    "Why don't eggs tell jokes? They'd crack each other up.",
    "I told my computer I needed a break, and it said no problem, it would go to sleep.",
    "Why did the scarecrow win an award? Because he was outstanding in his field.",
    "What do you call a fish with no eyes? A fsh.",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "Why can't you give Elsa a balloon? Because she'll let it go.",
    "What do you call cheese that isn't yours? Nacho cheese.",
    "Why did the bicycle fall over? It was two tired.",
    "How does a penguin build its house? Igloos it together.",
    "What did the ocean say to the beach? Nothing, it just waved.",
    "Why did the math book look sad? It had too many problems.",
    "What do you call a bear with no teeth? A gummy bear.",
    "Why don't scientists trust atoms? They make up everything.",
    "What's orange and sounds like a parrot? A carrot.",
    "Why did the cookie go to the doctor? It felt crummy.",
    "What do you call a sleeping dinosaur? A dino-snore.",
    "How do you make a tissue dance? Put a little boogie in it.",
    "What has ears but cannot hear? A cornfield.",
    "Why was six afraid of seven? Because seven eight nine.",
    "What do you call a dog magician? A labracadabrador.",
    "Why did the tomato blush? Because it saw the salad dressing.",
    "What kind of music do planets like? Neptunes.",
    "What did one wall say to the other? I'll meet you at the corner.",
    "Why do bees have sticky hair? They use honeycombs.",
    "What do you call a boomerang that won't come back? A stick.",
    "How do you organise a space party? You planet.",
    "What's a cat's favourite colour? Purr-ple.",
    "Why did the banana go to the doctor? It wasn't peeling well.",
    "What do you call a pile of cats? A meow-tain.",
    "Why did the golfer bring two pairs of pants? In case he got a hole in one.",
    "What do clouds wear under their clothes? Thunderwear.",
    "What did the zero say to the eight? Nice belt.",
    "Why did the student eat his homework? The teacher said it was a piece of cake.",
    "What do you call a snowman with a six pack? An abdominal snowman.",
    "How does the moon cut its hair? Eclipse it.",
    "What do you call a factory that makes okay products? A satisfactory.",
    "Why did the picture go to jail? Because it was framed.",
    "What do you get when you cross a snowman and a vampire? Frostbite.",
    "Why did the chicken join a band? Because it had the drumsticks.",
    "What did the left eye say to the right eye? Between us, something smells.",
]
RIDDLES = [
    ("What has keys but can't open locks?", ["piano", "keyboard"]),
    ("What has to be broken before you can use it?", ["egg"]),
    ("I'm tall when I'm young and short when I'm old. What am I?", ["candle"]),
    ("What has hands but can't clap?", ["clock"]),
    ("What gets wetter the more it dries?", ["towel"]),
    ("What has a neck but no head?", ["bottle", "shirt"]),
    ("What can you catch but not throw?", ["cold"]),
    ("What has one eye but can't see?", ["needle"]),
    ("What goes up but never comes down?", ["age", "your age"]),
    ("What has legs but doesn't walk?", ["table", "chair"]),
    ("What runs but never walks, has a mouth but never talks?", ["river"]),
    ("What building has the most stories?", ["library"]),
    ("What has teeth but can't bite?", ["comb", "zipper"]),
    ("The more you take, the more you leave behind. What are they?", ["footsteps", "steps", "footprints"]),
    ("What can travel around the world while staying in a corner?", ["stamp"]),
    ("What has a thumb and four fingers but isn't alive?", ["glove"]),
    ("What is full of holes but still holds water?", ["sponge"]),
    ("What comes once in a minute, twice in a moment, but never in a thousand years?", ["the letter m", "letter m", "m"]),
    ("What has a head and a tail but no body?", ["coin"]),
    ("What kind of room has no doors or windows?", ["mushroom"]),
    ("What is always in front of you but can't be seen?", ["the future", "future"]),
    ("What has words but never speaks?", ["book"]),
    ("What can you hold in your left hand but not your right?", ["your right hand", "right hand", "right elbow"]),
    ("I have branches but no fruit, trunk or leaves. What am I?", ["bank"]),
    ("What has many rings but no fingers?", ["tree", "telephone", "phone"]),
    ("What invention lets you look right through a wall?", ["window"]),
    ("What starts with T, ends with T, and has T in it?", ["teapot"]),
    ("What gets bigger the more you take away from it?", ["hole"]),
    ("What is so fragile that saying its name breaks it?", ["silence"]),
    ("Where does today come before yesterday?", ["dictionary", "in the dictionary"]),
]
WOULD_YOU_RATHER = [
    "be able to fly or be invisible", "have a pet dragon or a pet unicorn", "live on the moon or under the sea",
    "eat only pizza or only ice cream for a year", "be a superhero or a wizard", "talk to animals or speak every language",
    "have a jetpack or a submarine", "never have homework or never have chores", "be as tall as a giraffe or as small as a mouse",
    "swim with dolphins or ride an elephant", "have a robot butler or a robot dog", "visit the past or the future",
    "be super strong or super fast", "have a treehouse or a secret cave", "eat a bug or sing in front of the whole school",
    "always be too hot or always be too cold", "be a famous singer or a famous athlete", "have wings or gills",
    "live in a castle or on a pirate ship", "control the weather or control time",
]
EIGHT_BALL = ["It is certain.", "Without a doubt.", "Yes, definitely.", "You may rely on it.", "Most likely.", "Signs point to yes.",
              "Ask again later.", "Better not tell you now.", "Cannot predict now.", "Don't count on it.", "My reply is no.",
              "Very doubtful.", "Outlook good.", "Outlook not so good.", "Yes.", "No."]
ANIMALS = {"cow": ["moo"], "dog": ["woof", "bark", "ruff"], "cat": ["meow", "miaow"], "sheep": ["baa"], "pig": ["oink"], "duck": ["quack"],
           "horse": ["neigh"], "lion": ["roar"], "frog": ["ribbit", "croak"], "owl": ["hoot", "who"], "rooster": ["cock a doodle doo", "cockadoodledoo"],
           "bee": ["buzz"], "snake": ["hiss"], "mouse": ["squeak"], "elephant": ["trumpet"], "monkey": ["ooh", "ooh ooh"], "chicken": ["cluck", "bawk"]}
SPELL_WORDS = ["cat", "dog", "sun", "hat", "red", "big", "cup", "bed", "fish", "frog", "book", "milk", "tree", "star", "cake", "ship",
               "green", "house", "apple", "happy", "water", "chair", "train", "smile", "cloud", "tiger", "queen", "bread"]
CATEGORIES = {"science": 17, "history": 23, "geography": 22, "animals": 27, "sports": 21, "movies": 11, "music": 12, "video games": 15,
              "computers": 18, "math": 19, "books": 10, "cartoons": 32, "art": 25, "nature": 17}
LETTERS = ["A", "B", "C", "D"]


# ------------------------------------------------------------------ helpers
def _emit(kind="game"):
    ctx.emit(kind, _visible())


def _visible():
    with _lock:
        return {k: _g[k] for k in ("active", "kind", "prompt", "options", "score", "round", "total", "expires", "last", "story")}


def _listen(seconds=None):
    v = ctx.module("voice")
    secs = float(seconds or ctx.config.get("answer_window_s", 20))
    with _lock:
        _g["expires"] = time.time() + secs + 40
    if v and hasattr(v, "open_follow_up"):
        try:
            v.open_follow_up(secs)
        except Exception as e:
            ctx.log(f"follow_up failed: {e}")


def _start(kind, prompt="", options=None, answer=None, accept=None, total=0, extra=None, keep_score=False):
    with _lock:
        was = _g["active"]
        if not keep_score:
            _g["score"] = 0; _g["round"] = 0
        _g.update({"active": kind, "kind": kind, "prompt": prompt, "options": options or [], "answer": answer,
                   "accept": [a.lower() for a in (accept or [])], "total": total, "extra": extra or {}, "last": None})
    if was is None:
        ctx.emit("game_open", {"kind": kind})
    _emit()


def _end(message=None):
    with _lock:
        _g.update({"active": None, "kind": None, "prompt": "", "options": [], "answer": None, "accept": [], "expires": 0.0,
                   "extra": {}, "story": None})
        if message:
            _g["last"] = {"text": message}
    _emit()


def _set_last(text, ok=None):
    with _lock:
        _g["last"] = {"text": text, "ok": ok}


def _record_score(game, value):
    """High score per game in config games.scores (higher is better)."""
    scores = dict(ctx.config.get("scores") or {})
    best = scores.get(game)
    if best is None or value > best.get("best", -1):
        scores[game] = {"best": value, "at": time.time()}
        ctx.config["scores"] = scores
        ctx.save_config()
        return True
    return False


def _norm(t):
    t = (t or "").lower().strip().rstrip(".!?")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_WORDNUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
            "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}


def _numbers(t):
    """All integers in the text, digits or words ('twenty one' -> 21)."""
    out = []
    for m in re.finditer(r"\d+", t):
        out.append(int(m.group(0)))
    words = t.split()
    i = 0
    while i < len(words):
        if words[i] in _WORDNUM:
            v = _WORDNUM[words[i]]
            if v >= 20 and i + 1 < len(words) and words[i + 1] in _WORDNUM and _WORDNUM[words[i + 1]] < 10:
                v += _WORDNUM[words[i + 1]]; i += 1
            out.append(v)
        i += 1
    return out


# ------------------------------------------------------------------ content sources
def _joke():
    try:
        req = urllib.request.Request("https://icanhazdadjoke.com/", headers={"Accept": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=4) as r:
            j = json.load(r)
        if j.get("joke"):
            return j["joke"].strip()
    except Exception:
        pass
    return random.choice(JOKES)


def _trivia_batch(easy=False, category=None):
    key = f"{'easy' if easy else 'general'}:{category or ''}"
    with _lock:
        cached = _trivia_cache.get(key) or []
    if cached:
        return cached
    url = "https://opentdb.com/api.php?amount=20&type=multiple" + ("&difficulty=easy" if easy else "") + (f"&category={category}" if category else "")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=6) as r:
            j = json.load(r)
        qs = []
        for q in j.get("results", []):
            opts = [html.unescape(x) for x in q.get("incorrect_answers", [])] + [html.unescape(q.get("correct_answer", ""))]
            random.shuffle(opts)
            qs.append({"q": html.unescape(q.get("question", "")), "options": opts, "answer": html.unescape(q.get("correct_answer", "")),
                       "category": html.unescape(q.get("category", ""))})
        with _lock:
            _trivia_cache[key] = qs
        return qs
    except Exception as e:
        ctx.log(f"trivia fetch failed: {e}")
        return []


def _story(topic):
    v = ctx.module("voice")
    if not v or not hasattr(v, "ask_llm"):
        return None
    system = ("You write short bedtime stories for young children. Write exactly 7 sentences, plain text, one paragraph, "
              "gentle and fun, no violence, no lists, no title, no emoji. Every sentence ends with a period.")
    return v.ask_llm(f"Tell a story about {topic}.", system=system)


# ------------------------------------------------------------------ question makers
def _next_trivia():
    with _lock:
        pool = _g["extra"].get("pool") or []
        rnd = _g["round"]
    if not pool:
        return None
    q = pool.pop(0)
    with _lock:
        _g["round"] = rnd + 1
        _g["prompt"] = q["q"]; _g["options"] = q["options"]; _g["answer"] = q["answer"]; _g["accept"] = [q["answer"].lower()]
        _g["extra"]["category"] = q.get("category", "")
    _emit()
    _listen()
    letters = ", ".join(f"{LETTERS[i]}, {o}" for i, o in enumerate(q["options"]))
    return f"Question {rnd + 1}. {q['q']} {letters}."


def _next_math():
    with _lock:
        mode = _g["extra"].get("mode", "easy"); rnd = _g["round"]
    if mode == "tables":
        a, b = random.randint(2, 12), random.randint(2, 12); ans = a * b; text = f"What is {a} times {b}?"
    else:
        a, b = random.randint(1, 10), random.randint(1, 10)
        if random.random() < 0.5:
            ans = a + b; text = f"What is {a} plus {b}?"
        else:
            if a < b: a, b = b, a
            ans = a - b; text = f"What is {a} minus {b}?"
    with _lock:
        _g["round"] = rnd + 1; _g["prompt"] = text; _g["options"] = []; _g["answer"] = str(ans); _g["accept"] = [str(ans)]
    _emit(); _listen(15)
    return text


def _next_spell():
    word = random.choice(SPELL_WORDS)
    with _lock:
        _g["round"] += 1; _g["prompt"] = f"Spell the word {word}"; _g["options"] = []; _g["answer"] = word; _g["accept"] = [word]
    _emit(); _listen(25)
    return f"Spell the word: {word}."


def _next_animal():
    animal = random.choice(list(ANIMALS))
    with _lock:
        _g["round"] += 1; _g["prompt"] = f"What sound does a {animal} make?"; _g["options"] = []; _g["answer"] = ANIMALS[animal][0]
        _g["accept"] = ANIMALS[animal]
    _emit(); _listen(15)
    return f"What sound does a {animal} make?"


def _finish_round(label):
    with _lock:
        score, total = _g["score"], _g["round"]
    best = _record_score(label, score)
    _end(f"{score} out of {total}")
    return f"That's the round. You got {score} out of {total}." + (" A new high score!" if best and score > 0 else "")


# ------------------------------------------------------------------ answer checking
def _check_choice(t):
    """Pick an option from a spoken answer: letter, ordinal, or the option text."""
    with _lock:
        opts = list(_g["options"])
    if not opts:
        return None
    m = re.fullmatch(r"(?:the answer is |i think |its |it is |is it )?(?:option |letter )?([abcd])", t)
    if m:
        return opts[LETTERS.index(m.group(1).upper())] if LETTERS.index(m.group(1).upper()) < len(opts) else None
    ords = {"first": 0, "1st": 0, "one": 0, "second": 1, "2nd": 1, "two": 1, "third": 2, "3rd": 2, "three": 2, "fourth": 3, "4th": 3, "four": 3, "last": len(opts) - 1}
    m = re.search(r"\b(first|second|third|fourth|last|1st|2nd|3rd|4th)\b(?: one)?", t)
    if m and ords[m.group(1)] < len(opts):
        return opts[ords[m.group(1)]]
    for o in opts:
        on = _norm(o)
        if on and (on == t or on in t or (len(on) > 3 and t in on)):
            return o
    return None


def _answer_game(t):
    """t is normalised text while a game is active. Returns the reply or None if it isn't an answer."""
    with _lock:
        kind = _g["active"]; answer = _g["answer"]; accept = list(_g["accept"]); extra = dict(_g["extra"])
        rnd, total = _g["round"], _g["total"]
    if kind == "riddle":
        if re.search(r"\b(give up|i don t know|dont know|what is it|tell me|the answer|no idea)\b", t):
            _end(f"It was: {answer}")
            return f"It's {answer}."
        if any(a in t for a in accept):
            _record_score("riddles", 1)
            _end("Correct")
            return "Yes! That's right."
        _listen(15)
        return random.choice(["Not quite, try again.", "Nope. Want a hint? Say give up.", "Good guess, but no."])
    if kind == "trivia":
        if re.search(r"\b(skip|pass|next question|i don t know|dont know)\b", t):
            reply = f"It was {answer}. "
        else:
            pick = _check_choice(t)
            if pick is None:
                _listen(12)
                return "Say A, B, C or D."
            ok = _norm(pick) == _norm(answer)
            with _lock:
                if ok: _g["score"] += 1
            _set_last(f"{'Correct' if ok else 'Wrong'}: {answer}", ok)
            reply = ("Correct! " if ok else f"No, it was {answer}. ")
        if rnd >= total:
            return reply + _finish_round("trivia")
        nxt = _next_trivia()
        return reply + (nxt or _finish_round("trivia"))
    if kind == "math":
        nums = _numbers(t)
        if not nums:
            if re.search(r"\b(skip|pass|dont know|i don t know)\b", t):
                nums = [None]
            else:
                _listen(12); return "Just say the number."
        ok = str(nums[0]) == answer
        with _lock:
            if ok: _g["score"] += 1
        _set_last(f"{'Correct' if ok else 'The answer was ' + answer}", ok)
        reply = ("Yes! " if ok else f"It's {answer}. ")
        if rnd >= total:
            return reply + _finish_round("math")
        return reply + _next_math()
    if kind == "spell":
        said = t.replace(" ", "")
        ok = said == answer or _norm(t) == answer
        with _lock:
            if ok: _g["score"] += 1
        _set_last(f"{'Correct' if ok else 'It is spelled ' + ' '.join(answer)}", ok)
        reply = ("Perfect! " if ok else f"Close. It's spelled {', '.join(answer)}. ")
        if rnd >= total:
            return reply + _finish_round("spelling")
        return reply + _next_spell()
    if kind == "animal":
        ok = any(a in t for a in accept)
        with _lock:
            if ok: _g["score"] += 1
        _set_last(f"{'Correct' if ok else 'A ' + extra.get('animal', '') + ' says ' + answer}", ok)
        reply = ("That's it! " if ok else f"It says {answer}. ")
        if rnd >= total:
            return reply + _finish_round("animals")
        return reply + _next_animal()
    if kind == "rps":
        moves = {"rock": "rock", "paper": "paper", "scissors": "scissors", "scissor": "scissors"}
        mine = next((moves[w] for w in t.split() if w in moves), None)
        if not mine:
            _listen(10); return "Rock, paper or scissors?"
        theirs = random.choice(["rock", "paper", "scissors"])
        beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if mine == theirs:
            res, ok = "It's a tie.", None
        elif beats[mine] == theirs:
            res, ok = "You win!", True
            _record_score("rps", int((ctx.config.get("scores") or {}).get("rps", {}).get("best", 0)) + 1)
        else:
            res, ok = "I win!", False
        _set_last(f"You: {mine}. Jarvis: {theirs}. {res}", ok)
        _end(f"You {mine}, me {theirs}. {res}")
        return f"I picked {theirs}. {res}"
    if kind == "wyr":
        _end("Good choice")
        return random.choice(["Good choice.", "Interesting. I'd pick the same.", "Bold. I like it."])
    return None


_NEW_GAME = re.compile(r"\b(roll|flip a coin|toss a coin|coin flip|joke|riddle|trivia|quiz|times tables|multiplication|spelling|animal sounds?|"
                       r"story|would you rather|8 ball|eight ball|magic ball|rock paper scissors?)\b")


# ------------------------------------------------------------------ voice entry
def intent(text):
    raw = (text or "").strip()
    if not raw:
        return None
    t = _norm(raw)
    with _lock:
        active = _g["active"]; expired = _g["expires"] and time.time() > _g["expires"]
    if active and expired:
        _end()
        active = None
    if active:
        if re.search(r"\b(quit|stop|end|exit|cancel|done|finish)\b.*\b(game|playing|quiz|trivia)\b|\b(i m done|i am done|im done|that s enough|quit|never mind|no more)\b", t):
            _end("Game over")
            return "Okay, game over."
        if not _NEW_GAME.search(t):                 # a request for another game replaces the running one
            r = _answer_game(t)
            if r is not None:
                return r

    # dice and coin
    m = re.search(r"\broll\b.*\b(?:a |the |an )?(?:(\w+) )?(?:dice|die|d ?(\d+))", t) or re.search(r"\broll (?:a |the )?d ?(\d+)\b", t)
    if m or re.search(r"\broll (?:the |a |some )?dice\b", t):
        sides = 6; count = 1
        ms = re.search(r"\bd ?(\d+)\b", t)
        if ms: sides = max(2, min(100, int(ms.group(1))))
        nums = [n for n in _numbers(re.sub(r"\bd ?\d+\b", "", t)) if 1 <= n <= 10]
        if nums: count = nums[0]
        if re.search(r"\btwo dice\b|\b2 dice\b|\bpair\b", t): count = 2
        rolls = [random.randint(1, sides) for _ in range(count)]
        with _lock:
            _g["last"] = {"text": " + ".join(map(str, rolls)) + (f" = {sum(rolls)}" if count > 1 else ""), "dice": rolls, "sides": sides}
        _emit(); ctx.emit("game_open", {"kind": "dice"})
        if count == 1:
            return f"You rolled a {rolls[0]}."
        return f"You rolled {' and '.join(map(str, rolls))}, that's {sum(rolls)}."
    if re.search(r"\b(flip|toss) (?:a |the )?coin\b|\bheads or tails\b|\bcoin flip\b", t):
        side = random.choice(["Heads", "Tails"])
        with _lock:
            _g["last"] = {"text": side, "coin": side}
        _emit(); ctx.emit("game_open", {"kind": "coin"})
        return f"{side}."

    # jokes, riddles, would you rather, 8 ball
    if re.search(r"\b(tell me a joke|tell me another joke|another joke|say a joke|make me laugh|a joke please|joke)\b", t) and not re.search(r"\briddle\b", t):
        j = _joke()
        with _lock:
            _g["last"] = {"text": j}
        _emit()
        return j
    if re.search(r"\briddle\b", t):
        q, ans = random.choice(RIDDLES)
        _start("riddle", prompt=q, answer=ans[0], accept=ans)
        _listen(25)
        return q
    if re.search(r"\bwould you rather\b|\bwould i rather\b", t) and not active:
        q = random.choice(WOULD_YOU_RATHER)
        _start("wyr", prompt=f"Would you rather {q}?")
        _listen(15)
        return f"Would you rather {q}?"
    if re.search(r"\b(8 ball|eight ball|magic ball)\b", t):
        a = random.choice(EIGHT_BALL)
        with _lock:
            _g["last"] = {"text": a, "eightball": True}
        _emit(); ctx.emit("game_open", {"kind": "eightball"})
        return a

    # rounds
    if re.search(r"\btrivia\b|\bquiz me\b|\bplay a quiz\b", t) and not re.search(r"\bmath\b", t):
        easy = bool(re.search(r"\b(kid|kids|easy|children)\b", t))
        cat = next((v for k, v in CATEGORIES.items() if k in t), None)
        pool = list(_trivia_batch(easy=easy, category=cat))
        if not pool:
            return "I can't reach the trivia questions right now."
        random.shuffle(pool)
        n = int(ctx.config.get("trivia_round", 5))
        _start("trivia", total=n, extra={"pool": pool[:n + 2], "easy": easy})
        return "Let's play trivia. " + (_next_trivia() or "")
    if re.search(r"\b(math quiz|math game|maths quiz|times tables|multiplication|quiz me on math|math questions)\b", t):
        mode = "tables" if re.search(r"\b(times tables|multiplication)\b", t) else "easy"
        _start("math", total=5, extra={"mode": mode})
        return ("Times tables. " if mode == "tables" else "Math quiz. ") + _next_math()
    if re.search(r"\bspelling bee\b|\bspelling game\b|\bspell(?:ing)? quiz\b", t):
        _start("spell", total=5)
        return "Spelling bee. " + _next_spell()
    if re.search(r"\banimal sounds?\b|\banimal game\b", t):
        _start("animal", total=5)
        return "Animal sounds. " + _next_animal()
    if re.search(r"\brock paper scissors\b|\brock paper scissor\b", t):
        _start("rps", prompt="Rock, paper, scissors, shoot!")
        _listen(10)
        return "Rock, paper, scissors, shoot! Say your move."

    # stories
    m = re.search(r"\b(?:tell|read) (?:me |us )?a (?:bedtime )?story(?: about (.+))?$", t)
    if m:
        topic = (m.group(1) or random.choice(["a brave little robot", "a dragon who loved cookies", "a cat who went to the moon",
                                              "a lost puppy who found a friend", "a tiny boat on a big river"])).strip()
        s = _story(topic)
        if not s:
            return "I can't make up a story right now."
        sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", s) if x.strip()]
        with _lock:
            _g["story"] = {"topic": topic, "text": s, "pages": [" ".join(sents[i:i + 2]) for i in range(0, len(sents), 2)]}
            _g["last"] = {"text": f"A story about {topic}"}
        _emit(); ctx.emit("game_open", {"kind": "story"})
        return s
    return None


# ------------------------------------------------------------------ api / state / start
def state():
    v = _visible()
    v["scores"] = ctx.config.get("scores") or {}
    return v


def api(action, params):
    if action == "answer":
        # a tapped answer on the screen while a voice game runs
        r = _answer_game(_norm(str(params.get("text", ""))))
        if r is not None:
            voice = ctx.module("voice")
            if voice and hasattr(voice, "say") and params.get("speak", True):
                try: voice.say(r, blocking=False)
                except Exception: pass
        return {"ok": r is not None, "reply": r}
    if action == "start":
        r = intent(str(params.get("text", "")))
        if r is not None and params.get("speak", True):
            voice = ctx.module("voice")
            if voice and hasattr(voice, "say"):
                try: voice.say(r, blocking=False)
                except Exception: pass
        return {"ok": r is not None, "reply": r}
    if action == "end":
        _end()
        return {"ok": True}
    if action == "score":
        game = str(params.get("game", ""))[:30]
        try:
            value = int(params.get("value", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "value must be a number"}
        if not game:
            return {"ok": False, "error": "game required"}
        best = _record_score(game, value)
        return {"ok": True, "new_best": best, "scores": ctx.config.get("scores") or {}}
    if action == "joke":
        return {"ok": True, "joke": _joke()}
    if action == "state":
        return {"ok": True, **state()}
    return {"ok": False, "error": f"unknown action {action}"}


def _on_transcript(d):
    """A bare 'stop' is consumed by the voice module before intents; end a running game on it."""
    t = _norm((d or {}).get("text", ""))
    if _g["active"] and re.fullmatch(r"(stop|okay stop|jarvis stop|enough|cancel)", t):
        _end("Game over")


def start(c):
    global ctx
    ctx = c
    ctx.on("transcript", _on_transcript)
    while True:
        with _lock:
            if _g["active"] and _g["expires"] and time.time() > _g["expires"]:
                stale = True
            else:
                stale = False
        if stale:
            _end("Timed out")
        time.sleep(2)
