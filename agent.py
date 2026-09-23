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
No corporate tone.
No hype.
No fake enthusiasm.
No fake personal stories or fake first-person experience.
Never pretend to be an independent customer.
Never say or imply you "found", "discovered", "tried", "use", or "have been using" SpanishCue as an independent user.
Never hide the affiliation.
SpanishCue should NOT be mentioned in every reply.
Most useful participation should simply answer the person's question.
Only mention SpanishCue when it is genuinely relevant.
If SpanishCue is mentioned, the SAME reply must explicitly disclose affiliation with wording such as "I run SpanishCue", "I'm behind SpanishCue", or "I work on SpanishCue".
Do not recommend or name third-party websites, products, Slack groups, PDFs, courses, or resources unless they were already named in the Reddit post.
Do not invent product features, testimonials, prices, usage history, or external resources.
Do not include a link unless the person explicitly asks for websites, resources, platforms or materials AND subreddit rules allow it.
Do not reproduce or closely imitate previous replies.

VERIFIED SPANISHCUE FACTS:
- SpanishCue is a commercial teaching-material platform for Spanish teachers.
- It provides ready-to-teach Spanish lessons intended to be opened and used directly in class.
- Website: https://spanishcue.com
Do not claim any SpanishCue feature that is not listed above.

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
- the reply adds actual value

If should_reply=false, reply must be empty.
"""
    return ollama(prompt)


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
    if age_hours > 72:
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

    reply = result.get("reply", "").strip()
    if not reply:
        record(post, "", "ignored")
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
    for post in multi.new(limit=60):
        try:
            process_post(post)
        except Exception as exc:
            print(f"ERROR on {getattr(post, 'id', '?')}: {exc}")


def self_test():
    result = evaluate_post(
        subreddit="SpanishTeachers",
        title="What do you use when you have no time to prep a conversation class?",
        body=(
            "I teach Spanish online and I'm spending way too much time "
            "making materials for B1/B2 students. Looking for things I can "
            "actually open and use during class without rebuilding everything."
        ),
        rules_text=(
            "No spam. Self-promotion must be relevant to the discussion "
            "and affiliation must be disclosed."
        ),
        previous=[],
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run()
