"""Made-up roster and labelled cases for the agent-overload evals.

The roster is a snapshot of a long-time user: 20 hand-written agents (the ones
the cases are about) plus seeded "distractor" agents doing the same everyday
chores, so a roster of any size looks like a real one.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from server.services.execution.roster import AgentRecord

# Fixed "now", so every run builds exactly the same prompts.
NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


def _ago(**delta: float) -> datetime:
    return NOW - timedelta(**delta)


def _agent(name: str, description: str, **ago: float) -> AgentRecord:
    last_active = _ago(**ago).isoformat(timespec="microseconds")
    return AgentRecord(name=name, description=description, last_active_at=last_active)


CASE_AGENTS = [
    # Used in the last few hours; the follow-up cases continue these.
    _agent("Email to Landlord", "Draft an email to Marcus about the leaking kitchen faucet and ask when a plumber can come. Wait for approval before sending.", minutes=20),
    _agent("Mom Birthday Gift", "Suggest three birthday gifts for mom under $80. She likes gardening and mystery novels.", hours=1),
    _agent("Weekly Team Sync", "Draft the agenda for Thursday's team sync with Daniel and Mei: roadmap review, hiring update and the Q4 budget.", hours=2),
    _agent("Gym Reminder", "Remind the user to go to the gym every Monday, Wednesday and Friday at 7am.", hours=3),
    _agent("Pharmacy Refill", "Remind the user on Saturday morning to pick up the prescription refill.", hours=5),
    # Older work the callback cases come back to.
    _agent("Email to Priya", "Email Priya Shah to confirm the venue deposit for the team offsite and ask if the caterer invoice is included.", days=41),
    _agent("Flight to Lisbon", "Find the TAP Air Portugal booking confirmation and extract the flight number, departure time and seat.", days=63),
    _agent("Visa Appointment", "Check the consulate's email for the visa interview date and add it to the calendar.", days=12),
    _agent("Tax Documents", "Search email for T4 slips and RRSP contribution receipts for the 2025 tax year and list what is still missing.", days=88),
    _agent("Car Insurance Renewal", "Find the auto insurance renewal notice and compare the new premium with last year's.", days=27),
    _agent("Electricity Bill", "Find this month's Hydro bill email and tell the user the amount and due date.", days=9),
    _agent("Dentist Appointment", "Find an opening at Dr. Okafor's dental office next week, preferably a morning, and book a cleaning.", days=34),
    _agent("Northwind Offer Letter", "Find the offer letter email from Northwind recruiting and summarize the salary, equity and response deadline.", days=19),
    _agent("Package Tracking", "Find the shipping confirmation for the standing desk order and get the tracking number and delivery date.", days=6),
    _agent("Book Club", "Reply to Hannah that the user can host book club on the 14th and suggest The Remains of the Day.", days=23),
    # Older agents that no case is about.
    _agent("Newsletter Cleanup", "List the senders of promotional newsletters from the last 30 days so the user can unsubscribe.", days=50),
    _agent("Recruiter Follow-up", "Email Jordan at Lumen Talent to thank them and say the user is no longer looking.", days=15),
    _agent("Wedding RSVP", "RSVP yes for two to Sam and Riley's wedding on June 6 and request one vegetarian meal.", days=70),
    _agent("Conference Talk Proposal", "Draft a 200-word abstract on agent memory for the Toronto ML Summit talk proposal.", days=30),
    _agent("Rent Reminder", "Remind the user on the 1st of every month to pay rent to Marcus.", days=3),
]

_PEOPLE = (
    "Aisha Ben Carlos Chloe Dev Elena Farid Grace Hiro Ines Jamal Kenji Lena Luca "
    "Maya Nadia Omar Paolo Quinn Rosa Sofia Tariq Uma Victor Wen Yara Zoe Amir "
    "Bianca Diego Ella Felix Gabe Iris Jonah Kira Leo Mateo Nora Owen"
).split()

_DISTRACTOR_TEMPLATES = [
    ("Email to {p}", "Draft a short reply to {p}'s last email and wait for approval."),
    ("Meeting with {p}", "Find a 30-minute slot next week for a call with {p} and send an invite."),
    ("{p} Birthday", "Remind the user two days before {p}'s birthday."),
    ("Invoice from {p}", "Find the latest invoice from {p} and note the amount due."),
    ("Coffee with {p}", "Confirm coffee with {p} on Tuesday at 10am at the usual place."),
    ("Notes for {p}", "Summarize the last email thread with {p} in three bullet points."),
    ("Follow up with {p}", "Follow up with {p} if there is no reply by Friday."),
    ("Intro for {p}", "Write a short introduction email from {p} to a colleague in design."),
]


def _distractors() -> list[AgentRecord]:
    """320 agents active at seeded times 1 to 120 days ago (older than the recent five)."""
    rng = random.Random(0)
    pairs = [(person, template) for template in _DISTRACTOR_TEMPLATES for person in _PEOPLE]
    rng.shuffle(pairs)
    return [
        _agent(name.format(p=person), description.format(p=person), days=rng.uniform(1, 120))
        for person, (name, description) in pairs
    ]


def build_roster(size: int) -> list[AgentRecord]:
    """The 20 case agents plus the first size-20 distractors, oldest first.

    Smaller rosters are subsets of larger ones, so sizes compare like a user's
    roster growing over time. Oldest first matches roster.json, which appends
    each new agent at the end.
    """
    extra = size - len(CASE_AGENTS)
    if not 0 <= extra <= len(_DISTRACTOR_TEMPLATES) * len(_PEOPLE):
        raise ValueError(f"roster size must be between {len(CASE_AGENTS)} and 340")
    agents = CASE_AGENTS + _distractors()[:extra]
    return sorted(agents, key=lambda agent: agent.last_active_at)


@dataclass(frozen=True)
class Case:
    id: str
    kind: str  # "recent" | "keyword" | "paraphrase" | "new"
    message: str
    expected_agent: Optional[str]  # None: the right move is a new agent
    history: str = ""  # conversation transcript, in poke_conversation.log's format


def _history(start: datetime, *turns: tuple[str, str]) -> str:
    """Transcript lines one minute apart, from when the agent was last used."""
    return "\n".join(
        f'<{tag} timestamp="{start + timedelta(minutes=i):%Y-%m-%d %H:%M:%S}">{text}</{tag}>'
        for i, (tag, text) in enumerate(turns)
    )


CASES = [
    # Recent follow-ups: the message alone does not name the task.
    Case("recent-send", "recent", "looks good, send it", "Email to Landlord", _history(_ago(minutes=20),
        ("user_message", "can you email Marcus about the kitchen faucet leak and ask when a plumber can come?"),
        ("agent_message", "[SUCCESS] Email to Landlord: Drafted: 'Hi Marcus, the kitchen faucet has been leaking since Sunday. Could a plumber come by this week?' Waiting for approval before sending."),
        ("poke_reply", "Here's the draft for Marcus. Want me to send it?"),
    )),
    Case("recent-time", "recent", "actually make it 6:30", "Gym Reminder", _history(_ago(hours=3),
        ("user_message", "remind me to hit the gym mon wed fri at 7am"),
        ("agent_message", "[SUCCESS] Gym Reminder: Reminder set for Monday, Wednesday and Friday at 7:00am."),
        ("poke_reply", "Done. You'll get a nudge at 7am on Mon, Wed and Fri."),
    )),
    Case("recent-choice", "recent", "let's go with the second one. where can I order it?", "Mom Birthday Gift", _history(_ago(hours=1),
        ("user_message", "need a bday gift for my mom, under 80 bucks. she loves gardening and mysteries"),
        ("agent_message", "[SUCCESS] Mom Birthday Gift: 1) Japanese garden tool set ($64) 2) signed Louise Penny hardcover ($45) 3) herb growing kit ($38)."),
        ("poke_reply", "Three ideas: a Japanese garden tool set ($64), a signed Louise Penny hardcover ($45), or a herb growing kit ($38)."),
    )),
    Case("recent-add", "recent", "add a 10 minute slot at the end for Mei's demo", "Weekly Team Sync", _history(_ago(hours=2),
        ("user_message", "draft the agenda for thursday's sync with Daniel and Mei"),
        ("agent_message", "[SUCCESS] Weekly Team Sync: Agenda drafted: roadmap review, hiring update, Q4 budget."),
        ("poke_reply", "Agenda for Thursday: roadmap review, hiring update, Q4 budget."),
    )),
    # Callbacks to older agents that share words with the message.
    Case("keyword-deposit", "keyword", "Did Priya get back to us about the venue deposit?", "Email to Priya"),
    Case("keyword-flight", "keyword", "What was my flight number to Lisbon again?", "Flight to Lisbon"),
    Case("keyword-visa", "keyword", "Any word from the consulate about the visa interview?", "Visa Appointment"),
    Case("keyword-tax", "keyword", "Which tax documents am I still missing?", "Tax Documents"),
    Case("keyword-insurance", "keyword", "Did the car insurance renewal premium go up a lot?", "Car Insurance Renewal"),
    Case("keyword-hydro", "keyword", "When is the Hydro bill due?", "Electricity Bill"),
    # Callbacks that share no words with the agent: keyword matching misses these.
    Case("paraphrase-teeth", "paraphrase", "When are my teeth getting cleaned?", "Dentist Appointment"),
    Case("paraphrase-job", "paraphrase", "Did that job I was offered say how long I have to decide?", "Northwind Offer Letter"),
    Case("paraphrase-delivery", "paraphrase", "When does the thing I ordered for my office show up?", "Package Tracking"),
    Case("paraphrase-reading", "paraphrase", "Am I on the hook for the reading group next month?", "Book Club"),
    # New tasks: no existing agent has useful context.
    Case("new-restaurant", "new", "Find a good Italian restaurant near the office for lunch on Friday.", None),
    Case("new-plants", "new", "Remind me to water the plants every Sunday evening.", None),
    Case("new-library", "new", "Is the downtown public library open this Sunday?", None),
    Case("new-weather", "new", "What's the weather going to be like in Montreal this weekend?", None),
    Case("new-drive", "new", "How long is the drive from Toronto to Ottawa?", None),
    Case("new-spanish", "new", "Find a beginner Spanish class that meets on weekday evenings.", None),
]

# Spellings a model might use for an existing agent, paired with that agent.
# The last three differ by more than case and punctuation.
NAME_VARIANTS = [
    ("email to priya", "Email to Priya"),
    ("Email to Priya!", "Email to Priya"),
    ("EMAIL TO PRIYA", "Email to Priya"),
    ("Email-to-Priya", "Email to Priya"),
    ("gym reminder", "Gym Reminder"),
    ("Gym Reminder.", "Gym Reminder"),
    ("Tax documents", "Tax Documents"),
    ("Email Priya", "Email to Priya"),
    ("Gym Reminders", "Gym Reminder"),
    ("Dentist Appt", "Dentist Appointment"),
]
