"""Aggregate native emotes and short text repeated by different chatters."""

from collections import defaultdict
from dataclasses import dataclass
from math import ceil, sqrt
import re
from statistics import median


EMOTE_ID = re.compile(r"(?:[0-9]+|emotesv2_[a-zA-Z0-9]+)")
SHORT_TEXT = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*(?: [a-z0-9]+(?:['-][a-z0-9]+)*){0,3}")


def emote_ids(tag):
    values = (part.partition(":")[0] for part in tag.split("/"))
    return tuple(dict.fromkeys(value for value in values if EMOTE_ID.fullmatch(value)))


def short_text(message):
    normalized = " ".join(message.casefold().split()).strip("!?., ")
    if len(normalized) > 36 or not SHORT_TEXT.fullmatch(normalized):
        return None
    words = normalized.split()
    return words[0] if len(set(words)) == 1 else normalized


class ChatSignals:
    def __init__(self):
        self.native = defaultdict(set)
        self.text = defaultdict(set)

    def add(self, user, message, emotes=()):
        if not user or message.startswith(("/", "!")):
            return
        for emote in emotes:
            self.native[emote].add(user)
        phrase = short_text(message)
        if phrase:
            self.text[phrase].add(user)

    def top(self, minimum=3, limit=4, *, participants=0, baseline=()):
        def counts(kind):
            signals = getattr(self, kind)
            reference = [(getattr(window, kind), max(1, people)) for window, people in baseline]
            ranked = sorted(((key, len(users)) for key, users in signals.items() if len(users) >= minimum),
                            key=lambda item: (-item[1], item[0]))
            if reference:
                ranked = [
                    (key, people) for key, people in ranked
                    if people / max(1, participants) > 1.5 * median(
                        len(window.get(key, ())) / total for window, total in reference
                    )
                ]
            return dict(ranked[:limit])

        return {"emotes": counts("native"), "text": counts("text")}


@dataclass(frozen=True)
class Activity:
    messages: int
    people: int


def chat_flow(current, history, viewers):
    """Score a burst from counts of messages and people, without looking at text."""
    if len(history) < 6 or not viewers:
        return None

    # Keep the adjacent window out of the baseline when testing a two-window rise.
    reference = history[:-1] if len(history) > 6 else history
    usual_people = median(item.people for item in reference)
    usual_messages = median(item.messages for item in reference)
    spread = median(abs(item.people - usual_people) for item in reference)
    minimum = max(12, ceil(sqrt(viewers) / 16), ceil(3 * spread))

    people_rate = current.people / max(1, usual_people)
    message_rate = current.messages / max(1, usual_messages)
    excess = current.people - usual_people
    diversity = current.people / max(1, current.messages)
    previous = history[-1]
    previous_excess = previous.people - usual_people
    rule = None
    if diversity >= 0.65:
        if people_rate >= 1.8 and message_rate >= 1.45 and excess >= minimum:
            rule = "pico de participantes"
        elif (
            len(history) > 6 and people_rate >= 1.35 and message_rate >= 1.25
            and previous.people >= 1.35 * max(1, usual_people)
            and previous.messages >= 1.25 * max(1, usual_messages)
            and previous.people / max(1, previous.messages) >= 0.65
            and min(excess, previous_excess) >= minimum / 2
            and excess + previous_excess >= 2 * minimum
        ):
            rule = "fluxo sustentado"
    return {
        "rule": rule, "peopleRate": round(people_rate, 2), "messageRate": round(message_rate, 2),
        "baselinePeople": usual_people, "excessPeople": excess, "diversity": round(diversity, 3),
    }
