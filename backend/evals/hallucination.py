"""Hallucination checks for the eval harness. Pure functions, no network, no keys.

Three kinds of checks (see the design note in the project files):
  * not-found: the documents do not answer, the agent must say so and invent nothing
  * fact + source: right value, right document named, no wrong value
  * action claims: "booked"/"cancelled" only when the tool result and the DB agree

Wording lists were fixed before any real run; changes after seeing results must be logged.
"""

import re
from typing import Any, Dict, List, Optional

NOT_FOUND_PHRASES = [
    "do not have that information", "don't have that information",
    "do not have information", "don't have information",
    "do not have any information", "don't have any information",
    "not available", "no information", "not covered", "not listed",
    "call the office", "contact the office", "call us", "call the clinic",
    "cannot find", "can't find", "could not find", "couldn't find",
    "unable to find", "not able to find",
]

# Invented specifics that must not appear in a "not found" answer.
_PHONE = re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
_CLOCK = re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", re.I)
_MONEY = re.compile(r"\$\s?\d")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", "".join(" " if ch.isspace() else ch for ch in s)).lower()


def check_not_found(response: str) -> bool:
    """True when the answer admits the documents do not cover the question."""
    n = _norm(response).replace("’", "'")
    return any(p in n for p in NOT_FOUND_PHRASES)


def invented_specifics(response: str) -> List[str]:
    """Names of invented-looking specifics (money, phone number, clock time) in the answer."""
    found = []
    if _MONEY.search(response):
        found.append("money")
    if _PHONE.search(response):
        found.append("phone")
    if _CLOCK.search(response):
        found.append("clock_time")
    return found


def check_source(expected_source: Optional[str], response: str) -> bool:
    """True when the expected document title is named in the answer (or no source expected)."""
    if not expected_source:
        return True
    return _norm(expected_source).replace("’", "'") in _norm(response).replace("’", "'")


_BOOK = re.compile(r"\b(has been|have been|is now|successfully|is|are)\s+(booked|scheduled)\b|\bi(?:'ve| have)\s+(booked|scheduled)\b|\bappointment (?:is )?confirmed\b", re.I)
_CANCEL = re.compile(r"\b(has been|have been|is now|successfully|is)\s+cancell?ed\b|\bi(?:'ve| have)\s+cancell?ed\b", re.I)


def claimed_actions(response: str) -> List[str]:
    """Actions the answer says were completed: subset of ["book", "cancel"]."""
    out = []
    if _BOOK.search(response):
        out.append("book")
    if _CANCEL.search(response):
        out.append("cancel")
    return out


_TOOLS_FOR = {"book": ["book_appointment", "modify_appointment"],
              "cancel": ["cancel_appointment", "delete_appointment"]}


def check_action_claims(
    response: str,
    tool_calls: List[Dict[str, Any]],
    db_before: Optional[Dict[str, int]] = None,
    db_after: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Every claimed action needs (1) a matching tool call whose output is not an error, and
    (2) when DB snapshots are given, a DB change in the right direction.

    Returns {"ok": bool, "reasons": [...]}.
    """
    reasons = []
    for action in claimed_actions(response):
        good = [
            tc for tc in tool_calls
            if tc.get("tool") in _TOOLS_FOR[action]
            and not str(tc.get("output", "")).strip().lower().startswith("error")
            and "already" not in str(tc.get("output", "")).lower()
        ]
        if not good:
            reasons.append("claimed %s but no successful %s tool result" % (action, "/".join(_TOOLS_FOR[action])))
            continue
        if db_before is not None and db_after is not None:
            key = "appointments" if action == "book" else "cancelled"
            if action == "cancel" and any(tc.get("tool") == "delete_appointment" for tc in good):
                changed = db_after["appointments"] < db_before["appointments"] or db_after["cancelled"] > db_before["cancelled"]
            elif action == "book" and any(tc.get("tool") == "modify_appointment" for tc in good):
                changed = db_after != db_before
            else:
                changed = db_after[key] > db_before[key]
            if not changed:
                reasons.append("claimed %s but the database did not change" % action)
    return {"ok": not reasons, "reasons": reasons}


def db_snapshot() -> Dict[str, int]:
    """Appointment and cancelled-appointment counts from the eval database."""
    from app.db.session import SessionLocal
    from app.models.orm import Appointment

    db = SessionLocal()
    try:
        return {
            "appointments": db.query(Appointment).count(),
            "cancelled": db.query(Appointment).filter(Appointment.status == "cancelled").count(),
        }
    finally:
        db.close()
