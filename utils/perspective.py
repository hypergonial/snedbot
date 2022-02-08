from __future__ import annotations

import abc
import asyncio
import enum
import json
import os
import sys
import traceback
from typing import Any, Coroutine, Dict, List, Optional, Union

import aiohttp


class AttributeType(enum.Enum):
    """An enum of possible comment attributes."""

    TOXICITY = "TOXICITY"
    SEVERE_TOXICITY = "SEVERE_TOXICITY"
    IDENTITY_ATTACK = "IDENTITY_ATTACK"
    INSULT = "INSULT"
    PROFANITY = "PROFANITY"
    THREAT = "THREAT"


class ScoreType(enum.Enum):
    """An enum that contains alls possible score types."""

    NONE = "NONE"
    SPAN = "SPAN"
    SUMMARY = "SUMMARY"


class Attribute:
    """Represents a Perspective Attribute that can be requested."""

    def __init__(
        self,
        name: Union[AttributeType, str],
        *,
        score_type: str = "PROBABILITY",
        score_threshold: Optional[float] = None,
    ) -> None:
        self.name = AttributeType(name)
        self.score_type: str = str(score_type)
        self.score_threshold: float = float(score_threshold) if score_threshold else None

    def to_dict(self) -> dict:
        """Convert this attribute to a dict before sending it to the API."""
        payload = {self.name.value: {"scoreType": self.score_type, "scoreThreshold": self.score_threshold}}
        return payload


class AnalysisResponse:
    """Represents an Analysis Response received through the API."""

    def __init__(self, response: Dict[str, Any]) -> None:
        self.response: Dict[str, Any] = response

        self.languages: List[str] = self.response["languages"]

        self.detected_languages: Optional[List[str]] = (
            self.response["detected_languages"] if "detected_languages" in self.response.keys() else None
        )

        self.client_token: str = self.response["clientToken"] if "clientToken" in self.response.keys() else None

        self.attribute_scores: List[AttributeScore] = []

        for name, data in self.response["attributeScores"].items():
            self.attribute_scores.append(AttributeScore(name, data))


class AttributeScore:
    """Represents an AttributeScore received through the API."""

    def __init__(self, name: str, score_data: Dict[str, Any]) -> None:
        self.name: AttributeType = AttributeType(name)
        self.span: List[SpanScore] = []
        for score_type, data in score_data.items():

            if score_type == "spanScores":
                for span_data in data:
                    self.span.append(SpanScore(span_data))

            elif score_type == "summaryScore":
                self.summary: SummaryScore = SummaryScore(data)


class Score(abc.ABC):
    """Generic base class for scores."""

    def __init__(self) -> None:
        self.score_type: ScoreType.NONE


class SummaryScore(Score):
    """Represents a summary score rating for an AttributeScore."""

    def __init__(self, score_data: Dict[str, Any]) -> None:
        super().__init__()
        self.score_type: ScoreType = ScoreType.SUMMARY
        self.value: float = score_data["value"]
        self.type: str = score_data["type"]


class SpanScore(Score):
    """Represents a span score rating for an AttributeScore."""

    def __init__(self, score_data: Dict[str, Any]) -> None:
        super().__init__()
        self.score_type: ScoreType = ScoreType.SPAN
        self.value: float = score_data["score"]["value"]
        self.type: str = score_data["score"]["type"]
        self.begin: Optional[int] = score_data["begin"] if "begin" in score_data.keys() else None
        self.end: Optional[int] = score_data["end"] if "end" in score_data.keys() else None


class Client:
    """The client that handles making requests to the Perspective API.

    Parameters
    ----------
    api_key : str
        The API key provided by perspective.
    qps : int
        The maximum allowed amount of requests per second
        set in the Google Cloud Console. Defaults to 1.
    do_not_store : bool
        If True, sends a doNotStore request with the payload.
        This should be used when handling confidential data,
        or data of persons under the age of 13.
    """

    def __init__(self, api_key: str, qps: int = 1, do_not_store: bool = False) -> None:

        self.api_key = api_key
        self.qps = qps
        self.do_not_store = do_not_store
        self._queue = []
        self._values = {}
        self._current_task: Optional[asyncio.Task] = None

    async def _iter_queue(self):
        """Iterate queue and return values to _values"""
        try:
            while len(self._queue) > 0:
                queue_data: Dict[str, tuple] = self._queue.pop(0)
                key: str = list(queue_data.keys())[0]
                data: tuple = queue_data[key]

                coro: Coroutine = data[0]
                event: asyncio.Event = data[1]

                resp = await coro
                self._values[key] = resp

                event.set()
                await asyncio.sleep(1 / self.qps)
            self._current_task = None

        except Exception as e:
            print(f"Ignoring error in perspective._iter_queue: {e}", file=sys.stderr)
            print(traceback.format_exc())

    async def _execute_ratelimited(self, coro: Coroutine):
        """Execute a function with the ratelimits in mind."""
        key = os.urandom(16).hex()  # Identifies value in _values
        event = asyncio.Event()

        self._queue.append({key: (coro, event)})

        if not self._current_task:
            self._current_task = asyncio.create_task(self._iter_queue())

        await event.wait()
        return self._values.pop(key)

    async def analyze(
        self,
        text: str,
        languages: List[str],
        requested_attributes: List[Attribute],
        *,
        session_id: Optional[str] = None,
        client_token: Optional[str] = None,
    ) -> AnalysisResponse:
        return await self._execute_ratelimited(
            self._make_request(text, languages, requested_attributes, session_id=session_id, client_token=client_token)
        )

    async def _make_request(
        self,
        text: str,
        languages: List[str],
        requested_attributes: List[Attribute],
        *,
        session_id: Optional[str] = None,
        client_token: Optional[str] = None,
    ) -> AnalysisResponse:
        # TODO: Reuse session
        async with aiohttp.ClientSession() as session:

            attributes = {}
            for attribute in requested_attributes:
                attributes.update(attribute.to_dict())

            payload = {
                "comment": {
                    "text": text,
                    "type": "PLAIN_TEXT",
                },
                "languages": languages,
                "requestedAttributes": attributes,
                "doNotStore": self.do_not_store,
                "sessionId": session_id,
                "clientToken": client_token,
            }
            url = f"https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze?key={self.api_key}"
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return AnalysisResponse(await resp.json())
                raise ConnectionError(
                    f"Connection to Perspective API failed:\nResponse code: {resp.status}\n\n{json.dumps(await resp.json(), indent=4)}"
                )
