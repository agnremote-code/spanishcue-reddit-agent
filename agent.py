import argparse
import difflib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import praw
import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "alejandro:latest")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_COMMENTS_PER_DAY = int(os.getenv("MAX_COMMENTS_PER_DAY", "3"))
MIN_HOURS_BETWEEN_COMMENTS = float(os.getenv("MIN_HOURS_BETWEEN_COMMENTS", "4"))
POST_AGE_HOURS = int(os.getenv("POST_AGE_HOURS", "72"))
SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "60"))
SUBREDDITS = [
    x.strip()
    for x in os.getenv("SUBREDDITS", "SpanishTeachers,Preply,iTalki,Cambly").split(",")
    if x.strip()
]
DB_PATH = "agent.db"


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS interactions (
            post_id TEXT PRIMARY KEY,
            subreddit TEXT,
            post_title TEXT,
            reply_text TEXT,
            status TEXT,
            created_at TEXT
        )
        """
    )
    con.commit()
    return con


def ollama(prompt):
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=180,
    )
    response.raise_for_status()
    text = response.json()["response"].strip()
    text = re.sub(r"^\`\`\`(?:json)?", "", text).strip()
    text = re.sub(r"\`\`\`$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"No JSON returned:\n{text}")
    return json.loads(match.group(0))


def recent_replies(limit=20):
    con = db()
    rows = con.execute(
        """
        SELECT reply_text
        FROM interactions
        WHERE reply_text IS NOT NULL AND reply_text != ''
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def too_similar(text, previous):
    clean = " ".join(text.lower().split())
    for old in previous:
        old_clean = " ".join(old.lower().split())
        if difflib.SequenceMatcher(None, clean, old_clean).ratio() >= 0.72:
            return True
    return False


def evaluate_post(subreddit, title, body, rules_text="", previous=None):
    previous = previous or []
    previous_text = "\n\n".join(f"- {x}" for x in previous[-12:]) or "(none yet)"

    prompt = f"""
You are deciding whether the Reddit account u/SpanishCue should reply to a post.

u/SpanishCue is openly affiliated with SpanishCue, a commercial website for Spanish teachers.

STRICT TARGET:
Only engage with posts genuinely relevant to people TEACHING SPANISH or tutoring Spanish professionally.

Examples that MAY qualify:
- Spanish teachers asking for lesson ideas
- Spanish tutors discussing lesson preparation
- Spanish teachers looking for teaching materials
- Preply/italki/Cambly tutors specifically discussing teaching Spanish
- tutors asking how to structure Spanish classes
- teachers discussing Spanish conversation activities
- Spanish teaching resources

DO NOT engage with:
- Spanish learners asking how to learn Spanish
- students looking for tutors
- general platform complaints unrelated to teaching Spanish
- generic language-learning discussions
- unrelated Preply/italki/Cambly posts
- hiring spam
- promotional threads where participation would violate subreddit rules
- posts where SpanishCue would not genuinely add value

STYLE:
Write like a normal Reddit user.
Natural, casual, concise, useful.
Keep replies between 25 and 80 words unless the post clearly needs a little more context.
Prefer 1 to 3 short paragraphs.
No corporate tone.
No hype.
No fake enthusiasm.
No fake personal stories or fake first-person experience.
Avoid canned phrases like "Hope that helps", "A common approach is", "The key is", or "Consider".
Do not sound like a teacher-training manual or customer-support bot.
Never pretend to be an independent customer.
Never say or imply you "found", "discovered", "tried", "use", or "have been using" SpanishCue as an independent user.
Never hide the affiliation.
SpanishCue should NOT be mentioned in every reply.
Most useful participation should simply answer the person's question.
Only set mention_spanishcue=true when SpanishCue is genuinely relevant.

IMPORTANT:
- You ARE allowed to set mention_spanishcue=true even if the post did not already mention SpanishCue.
- Do this only when the post explicitly asks for Spanish-teaching materials, ready-to-use lessons, lesson-prep resources, classroom activities, teaching platforms, or similar resources that SpanishCue directly fits.
- If subreddit rules allow relevant self-promotion with disclosure, this is NOT a reason to reject the post.
- NEVER mention SpanishCue inside the reply field. The application will add a vetted disclosure sentence separately when mention_spanishcue=true.
- If mention_spanishcue=true and there is nothing useful to add beyond the vetted SpanishCue sentence, reply may be an empty string.

Do not recommend or name third-party websites, products, Slack groups, PDFs, courses, or resources unless they were already named in the Reddit post.
Do not invent product features, testimonials, prices, usage history, or external resources.
Do not include a link unless the person explicitly asks for websites, resources, platforms or materials AND subreddit rules allow it.
Do not reproduce or closely imitate previous replies.

SUBREDDIT:
r/{subreddit}

SUBREDDIT RULES:
{rules_text or "(rules unavailable)"}

POST TITLE:
{title}

POST BODY:
{body or "(no body)"}

RECENT REPLIES FROM THIS ACCOUNT:
{previous_text}

Return ONLY valid JSON:
{{
  "is_spanish_teacher_post": true,
  "quality": 0,
  "confidence": 0,
  "should_reply": false,
  "mention_spanishcue": false,
  "reason": "short internal reason",
  "reply": ""
}}

quality:
0 = junk or irrelevant
100 = substantive discussion worth joining

confidence:
confidence this is genuinely a Spanish-teaching/tutoring discussion.

Set should_reply=true ONLY if:
- is_spanish_teacher_post=true
- quality >= 75
- confidence >= 90
- subreddit rules do not appear to prohibit the participation
- EITHER the reply adds actual value OR mention_spanishcue=true because the post directly asks for relevant Spanish-teaching materials/resources

If should_reply=false, reply must be empty.
If should_reply=true and mention_spanishcue=true, reply is allowed to be empty because the application will append the vetted SpanishCue disclosure sentence.
"""
    return ollama(prompt)


def compose_final_reply(result, seed=""):
    base = (result.get("reply") or "").strip()
    if not result.get("mention_spanishcue"):
        return base

    templates = [
        "I run SpanishCue. It's a platform with ready-to-teach Spanish lessons you can open and use directly in class.",
        "I’m behind SpanishCue. It’s a platform with ready-to-teach Spanish lessons designed to be opened and used directly in class.",
        "I work on SpanishCue. It’s a platform for Spanish teachers with ready-to-teach lessons you can open and use directly in class.",
        "I run SpanishCue, a platform for Spanish teachers with ready-to-teach lessons that can be opened and used directly in class.",
    ]

    idx = sum(ord(ch) for ch in str(seed)) % len(templates)
    disclosure = templates[idx]

    if not base:
        return disclosure
    return f"{base}\n\n{disclosure}"


def reddit_client():
    required = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN"]
    missing = [x for x in required if not os.getenv(x)]
    if missing:
        raise RuntimeError("Missing Reddit credentials: " + ", ".join(missing))

    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        refresh_token=os.environ["REDDIT_REFRESH_TOKEN"],
        user_agent=os.getenv(
            "REDDIT_USER_AGENT",
            "SpanishCueRedditAgent/1.0 by u/SpanishCue",
        ),
    )


def subreddit_rules(subreddit):
    try:
        rules = []
        for rule in subreddit.rules():
            short = getattr(rule, "short_name", "") or ""
            desc = getattr(rule, "description", "") or ""
            rules.append(f"{short}: {desc}")
        return "\n".join(rules)
    except Exception:
        return ""


def already_processed(post_id):
    con = db()
    result = con.execute(
        "SELECT 1 FROM interactions WHERE post_id = ?", (post_id,)
    ).fetchone()
    con.close()
    return bool(result)


def comments_today():
    today = datetime.now(timezone.utc).date().isoformat()
    con = db()
    result = con.execute(
        """
        SELECT COUNT(*)
        FROM interactions
        WHERE status = 'posted'
          AND substr(created_at, 1, 10) = ?
        """,
        (today,),
    ).fetchone()[0]
    con.close()
    return result


def last_comment_timestamp():
    con = db()
    row = con.execute(
        """
        SELECT created_at
        FROM interactions
        WHERE status = 'posted'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    con.close()
    return datetime.fromisoformat(row[0]) if row else None


def spacing_ok():
    last = last_comment_timestamp()
    if not last:
        return True
    elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    return elapsed >= MIN_HOURS_BETWEEN_COMMENTS


def record(post, reply, status):
    con = db()
    con.execute(
        """
        INSERT OR REPLACE INTO interactions
        (post_id, subreddit, post_title, reply_text, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            post.id,
            str(post.subreddit),
            post.title,
            reply,
            status,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    con.commit()
    con.close()


def process_post(post):
    if already_processed(post.id):
        return
    if post.locked or post.archived or post.stickied:
        return
    if post.author and post.author.name.lower() == "spanishcue":
        return

    age_hours = (time.time() - post.created_utc) / 3600
    if age_hours > POST_AGE_HOURS:
        return

    rules = subreddit_rules(post.subreddit)
    previous = recent_replies()
    result = evaluate_post(
        subreddit=str(post.subreddit),
        title=post.title,
        body=post.selftext or "",
        rules_text=rules,
        previous=previous,
    )

    print("\n" + "=" * 70)
    print(f"r/{post.subreddit}")
    print(post.title)
    print(f"https://reddit.com{post.permalink}")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not result.get("should_reply"):
        record(post, "", "ignored")
        return
    if not result.get("is_spanish_teacher_post"):
        record(post, "", "ignored")
        return
    if int(result.get("quality", 0)) < 75:
        record(post, "", "ignored")
        return
    if int(result.get("confidence", 0)) < 90:
        record(post, "", "ignored")
        return

    reply = compose_final_reply(result, seed=post.id)
    if not reply:
        record(post, "", "ignored")
        return

    word_count = len(reply.split())
    if word_count > 100:
        print("SKIPPED: reply too long")
        record(post, reply, "length_block")
        return

    reply_lower = reply.lower()
    if "spanishcue" in reply_lower:
        disclosure_markers = (
            "i run spanishcue",
            "i'm behind spanishcue",
            "i am behind spanishcue",
            "i work on spanishcue",
            "i work for spanishcue",
            "i'm affiliated with spanishcue",
            "i am affiliated with spanishcue",
            "my project spanishcue",
        )
        if not any(marker in reply_lower for marker in disclosure_markers):
            print("SKIPPED: SpanishCue mentioned without explicit affiliation disclosure")
            record(post, reply, "disclosure_block")
            return
    if too_similar(reply, previous):
        print("SKIPPED: reply too similar to previous content")
        record(post, reply, "similarity_block")
        return
    if comments_today() >= MAX_COMMENTS_PER_DAY:
        print("SKIPPED: daily limit reached")
        return
    if not spacing_ok():
        print("SKIPPED: spacing limit")
        return

    if DRY_RUN:
        print("\nDRY RUN - WOULD POST:\n")
        print(reply)
        return

    comment = post.reply(reply)
    print(f"\nPOSTED: https://reddit.com{comment.permalink}")
    record(post, reply, "posted")


def run():
    reddit = reddit_client()
    print("Logged in as:", reddit.user.me())
    print("Watching:", ", ".join(SUBREDDITS))
    print("DRY_RUN:", DRY_RUN)

    multi = reddit.subreddit("+".join(SUBREDDITS))
    for post in multi.new(limit=SCAN_LIMIT):
        try:
            process_post(post)
        except Exception as exc:
            print(f"ERROR on {getattr(post, 'id', '?')}: {exc}")


def preflight():
    print("Ollama URL:", OLLAMA_URL)
    print("Ollama model:", OLLAMA_MODEL)
    print("Dry run:", DRY_RUN)
    print("Subreddits:", ", ".join(SUBREDDITS))

    response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    response.raise_for_status()
    models = [item.get("name") for item in response.json().get("models", [])]
    if OLLAMA_MODEL not in models:
        raise RuntimeError(f"Ollama model not found: {OLLAMA_MODEL}")
    print("Ollama: OK")

    required = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print("Reddit credentials: WAITING (" + ", ".join(missing) + ")")
        return

    reddit = reddit_client()
    print("Reddit login:", reddit.user.me())
    print("Reddit credentials: OK")


def local_status():
    con = db()
    total = con.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    posted = con.execute(
        "SELECT COUNT(*) FROM interactions WHERE status = 'posted'"
    ).fetchone()[0]
    ignored = con.execute(
        "SELECT COUNT(*) FROM interactions WHERE status = 'ignored'"
    ).fetchone()[0]
    con.close()

    print("Interactions:", total)
    print("Posted:", posted)
    print("Ignored:", ignored)
    print("Comments today:", comments_today())
    print("Dry run:", DRY_RUN)


def self_test():
    tests = [
        {
            "name": "relevant_spanish_teacher",
            "subreddit": "SpanishTeachers",
            "title": "What do you use when you have no time to prep a conversation class?",
            "body": (
                "I teach Spanish online and I'm spending way too much time "
                "making materials for B1/B2 students. Looking for things I can "
                "actually open and use during class without rebuilding everything."
            ),
            "rules": (
                "No spam. Self-promotion must be relevant to the discussion "
                "and affiliation must be disclosed."
            ),
        },
        {
            "name": "spanish_learner_not_teacher",
            "subreddit": "Spanish",
            "title": "How can I improve my Spanish listening?",
            "body": "I'm a learner around B1 and I want podcasts or videos to practice with.",
            "rules": "No spam or self-promotion.",
        },
        {
            "name": "generic_preply_complaint",
            "subreddit": "Preply",
            "title": "Why did my lesson get cancelled?",
            "body": "My tutor cancelled at the last minute and support hasn't replied yet.",
            "rules": "Keep posts related to Preply. No spam.",
        },
        {
            "name": "teacher_but_spanishcue_not_needed",
            "subreddit": "SpanishTeachers",
            "title": "How do you handle a student who keeps arriving 15 minutes late?",
            "body": "I teach Spanish online and this keeps happening with one adult student.",
            "rules": "No spam. Relevant self-promotion only.",
        },
    ]

    outputs = []
    for test in tests:
        result = evaluate_post(
            subreddit=test["subreddit"],
            title=test["title"],
            body=test["body"],
            rules_text=test["rules"],
            previous=[],
        )
        final_reply = compose_final_reply(result, seed=test["name"])
        outputs.append({"test": test["name"], **result, "final_reply": final_reply})

    print(json.dumps(outputs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    elif args.preflight:
        preflight()
    elif args.status:
        local_status()
    else:
        run()
